# -*- coding: utf-8 -*-
"""通用 REST 客户端（framework 内核）。

职责：
1. 统一发请求、计时、解析响应，屏蔽各系统 ``{code,message,data}`` 包装差异；
2. 把每次调用写进 pytest-html 报告（可折叠明细、慢请求高亮、token 脱敏）；
3. 失败请求自动存档，便于事后复盘。

业务系统只需配置 ``Envelope`` 的字段映射和成功码，不需要改客户端代码。
"""
import html
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence
from uuid import uuid4

import requests
from pytest_html import extras as html_extras

from framework.auth import AuthSpec
from framework.config import ROOT, env

# 慢请求阈值（毫秒）：超过则在报告明细中高亮
SLOW_MS = 1000
DEFAULT_REPORTS_DIR = ROOT / 'reports'

# 仅对幂等方法重试；业务失败被包成 HTTP 200 + code≠200 时不重试（负向用例需原样返回）
RETRYABLE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS', 'PUT', 'DELETE'})
DEFAULT_RETRY_STATUSES = (429, 500, 502, 503, 504)


@dataclass
class Envelope:
    """响应包装的字段映射。

    - code_key / message_key / data_key：顶层字段名；
    - code_path：可选点分路径，适用于 ``{'meta': {'code': 0}}`` 这类嵌套结构；
    - success_code：业务成功码（可为 int 或 str）；
    - success_statuses：被视为成功的 HTTP 状态码集合。
    """

    code_key: str = 'code'
    message_key: str = 'message'
    data_key: str = 'data'
    code_path: str = ''
    success_code: Any = 200
    success_statuses: Sequence[int] = (200, 201, 202, 204)

    def code_of(self, payload: Any) -> Any:
        if not isinstance(payload, dict):
            return None
        if self.code_path:
            node: Any = payload
            for part in self.code_path.split('.'):
                node = node.get(part) if isinstance(node, dict) else None
            return node
        return payload.get(self.code_key)

    def message_of(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ''
        return str(payload.get(self.message_key) or '')

    def data_of(self, payload: Any) -> Any:
        if not isinstance(payload, dict):
            return payload
        return payload.get(self.data_key)

    def is_success_code(self, code: Any) -> bool:
        return code == self.success_code

    def is_success(self, result: 'ApiResult') -> bool:
        return result.status in self.success_statuses and self.is_success_code(result.code)


@dataclass
class ApiResult:
    status: int
    code: Any
    message: str
    data: Any
    elapsed_ms: int
    raw: str
    url: str
    content_type: str = ''
    envelope: Optional[Envelope] = None
    payload: Any = None  # 原始响应 dict，供鉴权提取嵌套 token
    trace_id: str = ''   # 本次请求的链路追踪 ID
    attempts: int = 1    # 实际请求次数（含首次，重试后 >1）

    @property
    def ok(self) -> bool:
        if self.envelope is not None:
            return self.envelope.is_success(self)
        return self.status == 200 and self.code == 200

    def __repr__(self) -> str:
        return '<ApiResult %s status=%s code=%s message=%r url=%s trace=%s attempts=%s>' % (
            'OK' if self.ok else 'FAIL', self.status, self.code,
            self.message, self.url, self.trace_id or '-', self.attempts,
        )

    def describe(self) -> str:
        """一行摘要（HTTP 状态 / 业务码 / 消息）：异常消息与进度日志用，别塞整段 repr。"""
        code = self.code if self.code is not None else '-'
        return 'HTTP %s / code %s / %s' % (self.status, code, self.message or '无消息')


def mask_token(token: Optional[str]) -> str:
    if not token:
        return '-'
    return token[:10] + '…' + token[-4:] if len(token) > 16 else token


# 报告与失败存档中按「键名」脱敏的字段（JSON 请求体 / 响应体 / query 参数）。
# 报告是最常被转发分享的产物，登录请求体的密码、登录响应里的 token 都不能明文出现。
# 可用环境变量 API_SENSITIVE_KEYS 覆盖（逗号分隔键名，大小写不敏感）。
DEFAULT_SENSITIVE_KEYS = (
    'password', 'passwd', 'pwd', 'secret', 'token', 'access_token', 'refresh_token',
    'session_id', 'authorization', 'credit_card', 'id_card',
)
MASK = '******'


def mask_sensitive(value: Any, keys: frozenset) -> Any:
    """递归把 dict/list 中键名命中敏感清单的值替换为固定掩码；不修改原数据。"""
    if isinstance(value, dict):
        return {
            key: (MASK if str(key).lower() in keys else mask_sensitive(val, keys))
            for key, val in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [mask_sensitive(item, keys) for item in value]
    return value


def shorten(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else text[:limit] + '\n…（已截断，共 %d 字符）' % len(text)


class ApiClient:
    def __init__(self, base_url: str = '', timeout: float = 10.0, *,
                 envelope: Envelope | None = None,
                 auth_header: str = 'Authorization',
                 auth_scheme: str = 'Bearer',
                 auth: AuthSpec | None = None,
                 default_token: str | None = None,
                 reports_dir: Path | str | None = None,
                 slow_ms: int = SLOW_MS,
                 archive_failures: bool = True,
                 retry_enabled: bool | None = None,
                 max_retries: int | None = None,
                 retry_backoff: float | None = None,
                 retry_statuses: Sequence[int] | None = None,
                 trace_enabled: bool | None = None,
                 trace_header: str | None = None):
        if not base_url:
            base_url = env('API_BASE_URL', 'http://127.0.0.1:8080')
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.envelope = envelope or Envelope()
        self.auth = auth
        self.default_token = default_token
        if auth is not None:
            auth_header, auth_scheme = auth.header, auth.scheme
        self.auth_header = auth_header
        self.auth_scheme = auth_scheme
        self.reports_dir = Path(reports_dir) if reports_dir else DEFAULT_REPORTS_DIR
        self.slow_ms = slow_ms
        self.archive_failures = archive_failures

        # 重试与链路追踪：全部可用环境变量覆盖，换系统不需改代码
        self.retry_enabled = (
            env('API_RETRY_ENABLED', '1') == '1' if retry_enabled is None else retry_enabled
        )
        self.max_retries = (
            int(env('API_MAX_RETRIES', '1')) if max_retries is None else max_retries
        )
        self.retry_backoff = (
            float(env('API_RETRY_BACKOFF', '0.2')) if retry_backoff is None else retry_backoff
        )
        if retry_statuses is None:
            retry_statuses = tuple(
                int(x) for x in env('API_RETRY_STATUSES', '429,500,502,503,504').split(',')
                if x.strip().isdigit()
            )
        self.retry_statuses = tuple(retry_statuses) or DEFAULT_RETRY_STATUSES
        self.trace_enabled = (
            env('API_TRACE_ENABLED', '1') == '1' if trace_enabled is None else trace_enabled
        )
        self.trace_header = (
            env('API_TRACE_HEADER', 'X-Trace-Id') if trace_header is None else trace_header
        )
        sensitive = env('API_SENSITIVE_KEYS', ','.join(DEFAULT_SENSITIVE_KEYS))
        self.sensitive_keys = frozenset(
            key.strip().lower() for key in sensitive.split(',') if key.strip()
        )

        self.session = requests.Session()
        self.extras = None  # 由 conftest 绑定 pytest-html 的 extras fixture
        self.last_login: Optional[ApiResult] = None  # 最近一次登录响应，供取用户信息

    def clear_cookies(self) -> 'ApiClient':
        """清空本会话累积的 Cookie。

        同一个 ApiClient 共用一个 requests.Session，登录 / 注册返回的 Set-Cookie
        会一直带着。若被测服务 Cookie 优先于 ``Authorization`` 头（本项目的
        shopping 后端就是：CookieUtil.token 先读 Cookie 再用请求头兜底），
        那么"一个客户端先后登录两个身份"时，后一个身份的 Cookie 会覆盖前一个
        请求头，造成**静默串号**——断言看起来在测 A，实际请求的是 B。

        多身份场景（越权 / 会话隔离）应各用独立 ApiClient；确实要复用同一
        客户端时，切换身份前先调用本方法。
        """
        self.session.cookies.clear()
        return self

    # ---------- 请求 ----------

    def request(self, method: str, path: str, *, json_body: Any = None,
                params: Optional[Dict[str, Any]] = None, token: Optional[str] = None,
                files: Optional[Dict] = None, data: Any = None,
                headers: Optional[Dict[str, str]] = None,
                cookies: Optional[Dict[str, str]] = None) -> ApiResult:
        method = method.upper()
        url = self.base_url + (path if path.startswith('/') else '/' + path)
        req_headers = dict(headers or {})
        trace_id = uuid4().hex if self.trace_enabled else ''
        if trace_id:
            req_headers[self.trace_header] = trace_id
        explicit = token is not None
        actual_token = token if explicit else self.default_token
        # 显式 token 始终生效；cookie/none 模式下不主动注入请求头
        if actual_token and (explicit or self.auth is None or self.auth.uses_header()):
            value = (self.auth_scheme + ' ' + actual_token).strip() if self.auth_scheme else actual_token
            req_headers[self.auth_header] = value
        if json_body is not None:
            req_headers.setdefault('Content-Type', 'application/json; charset=utf-8')

        started = time.perf_counter()
        response = None
        last_error: Exception | None = None
        attempts = 0
        can_retry = self.retry_enabled and method in RETRYABLE_METHODS
        for attempt in range(1, self.max_retries + 2):
            attempts = attempt
            try:
                response = self.session.request(
                    method, url, json=json_body, params=params,
                    data=data, files=files, headers=req_headers, cookies=cookies,
                    timeout=self.timeout,
                )
                last_error = None
            except requests.RequestException as exc:
                last_error = exc
                response = None

            # HTTP 层可重试（网络异常或指定 5xx/429）；业务 code 失败不重试
            retryable_http = (
                response is not None and response.status_code in self.retry_statuses
            )
            retryable = can_retry and attempt <= self.max_retries and (
                response is None or retryable_http
            )
            if not retryable:
                break
            if self.retry_backoff:
                time.sleep(self.retry_backoff * attempt)
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        if response is None:
            result = ApiResult(
                status=0, code=None, message='请求异常: %s' % last_error,
                data=None, elapsed_ms=elapsed_ms, raw='', url=url,
                envelope=self.envelope, trace_id=trace_id, attempts=attempts,
            )
        else:
            content_type = response.headers.get('Content-Type', '')
            if 'application/json' in content_type:
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
            else:
                payload = None

            if isinstance(payload, dict):
                code = self.envelope.code_of(payload)
                message = self.envelope.message_of(payload)
                body = self.envelope.data_of(payload)
                # raw 仅供展示（报告、存档、断言失败消息），构造时统一按敏感键脱敏
                raw = json.dumps(
                    mask_sensitive(payload, self.sensitive_keys),
                    ensure_ascii=False, indent=2,
                )
            else:
                code = None
                message = ''
                body = payload if payload is not None else response.text
                raw = shorten(response.text, 2000)

            result = ApiResult(
                status=response.status_code, code=code, message=message,
                data=body, elapsed_ms=elapsed_ms, raw=raw, url=response.url,
                content_type=content_type, envelope=self.envelope, payload=payload,
                trace_id=trace_id, attempts=attempts,
            )
        if not result.ok:
            self._archive_failure(method, url, result)
        self._attach(method, path, req_headers, json_body, params, result)
        return result

    def login(self, username: str, password: str, **extra):
        """按 AuthSpec 自动登录：提取 token、探测 auto 模式，返回 token 或 None。

        登录与后续请求共用同一个 Session，因此 cookie 模式无需额外处理。
        """
        if self.auth is None:
            raise RuntimeError('ApiClient 未配置 auth，无法自动登录')
        body = self.auth.login_body(username, password)
        body.update(extra)
        result = self.post(self.auth.login_path, json_body=body)
        if not result.ok:
            # 用一行摘要而不是 repr：登录失败最常被体检消息引用，要能一眼读完
            raise AssertionError('登录失败：%s；%s' % (result.describe(), result.url))
        self.last_login = result
        token = self.auth.token_from(result.payload)
        if self.auth.mode == 'auto':
            self.auth.mode = (
                'header' if token else
                'cookie' if self.session.cookies else 'none'
            )
        self.default_token = token
        return token

    def get(self, path, **kw):
        return self.request('GET', path, **kw)

    def post(self, path, **kw):
        return self.request('POST', path, **kw)

    def put(self, path, **kw):
        return self.request('PUT', path, **kw)

    def patch(self, path, **kw):
        return self.request('PATCH', path, **kw)

    def delete(self, path, **kw):
        return self.request('DELETE', path, **kw)

    # ---------- 失败存档 ----------

    def _archive_failure(self, method, url, result):
        if not self.archive_failures:
            return
        try:
            target = self.reports_dir / 'failed_requests'
            target.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime('%Y%m%d-%H%M%S')
            safe = re.sub(r'[^A-Za-z0-9._-]', '_', url.replace(self.base_url, '').strip('/'))[:80]
            name = '%s_%s_%s.json' % (stamp, method.lower(), safe or 'root')
            payload = {
                'method': method, 'url': result.url, 'status': result.status,
                'code': result.code, 'message': result.message,
                'elapsed_ms': result.elapsed_ms, 'response': result.raw,
                'trace_id': result.trace_id, 'attempts': result.attempts,
            }
            (target / name).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8',
            )
        except Exception:  # noqa: BLE001 - 存档失败不应影响测试结论
            pass

    # ---------- 报告明细 ----------

    @staticmethod
    def _highlight(text: str) -> str:
        """给 JSON 文本做轻量着色；先转义再着色，避免 XSS。"""
        escaped = html.escape(text)
        escaped = re.sub(
            r'(&quot;(?:[^&]|&(?!quot;))*?&quot;)(?=\s*:)',
            r'<span class="enh-j-key">\1</span>', escaped,
        )
        escaped = re.sub(
            r'(?<=:\s)(-?\d+(?:\.\d+)?)(?=\s*[,}\]])',
            r'<span class="enh-j-num">\1</span>', escaped,
        )
        escaped = re.sub(
            r'(?<=:\s)(true|false|null)(?=\s*[,}\]])',
            r'<span class="enh-j-bool">\1</span>', escaped,
        )
        return escaped

    def _attach(self, method, path, headers, json_body, params, result: ApiResult):
        if self.extras is None:
            return

        req_lines = ['%s %s' % (method, path)]
        if params:
            req_lines.append('query: ' + json.dumps(
                mask_sensitive(params, self.sensitive_keys), ensure_ascii=False))
        if json_body is not None:
            req_lines.append('body: ' + json.dumps(
                mask_sensitive(json_body, self.sensitive_keys), ensure_ascii=False, indent=2))
        if headers.get(self.auth_header):
            raw = headers[self.auth_header]
            token = raw[len(self.auth_scheme):].strip() if self.auth_scheme else raw
            req_lines.append('%s: %s %s' % (
                self.auth_header, self.auth_scheme, mask_token(token),
            ))
        if headers.get('Content-Type'):
            req_lines.append('Content-Type: ' + headers['Content-Type'])
        if headers.get(self.trace_header):
            req_lines.append('%s: %s' % (self.trace_header, headers[self.trace_header]))
        if result.attempts > 1:
            req_lines.append('retry: 重试 %d 次（共 %d 次请求）'
                             % (result.attempts - 1, result.attempts))

        resp_text = result.raw  # 构造时已按敏感键脱敏
        if result.content_type.startswith('image/'):
            resp_text = '<二进制图片 %s>' % result.content_type

        if 200 <= result.status < 300:
            status_cls = 'enh-s-ok'
        elif result.status < 500:
            status_cls = 'enh-s-warn'
        else:
            status_cls = 'enh-s-err'
        code_cls = 'enh-c-ok' if self.envelope.is_success_code(result.code) else 'enh-c-bad'
        slow_cls = ' enh-slow' if result.elapsed_ms >= self.slow_ms else ''
        base_path = path.split('?', 1)[0]

        detail = (
            '<details class="enh-call" data-method="{method}" data-path="{base_path}" '
            'data-status="{status}" data-code="{code}" data-ms="{ms}" data-ok="{ok}">'
            '<summary>'
            '<span class="enh-method enh-m-{method_lower}">{method}</span>'
            '<span class="enh-path">{path}</span>'
            '<span class="enh-spacer"></span>'
            '<span class="enh-status {status_cls}">HTTP {status}</span>'
            '<span class="enh-code {code_cls}">code {code}</span>'
            '<span class="enh-ms{slow_cls}">{ms} ms</span>'
            '</summary>'
            '<div class="enh-call-body">'
            '<div class="enh-call-col"><div class="enh-call-title">请求 <span>REQUEST</span></div>'
            '<pre>{req}</pre></div>'
            '<div class="enh-call-col"><div class="enh-call-title">响应 <span>RESPONSE</span></div>'
            '<pre>{resp}</pre></div>'
            '</div></details>'
        ).format(
            method=html.escape(method), method_lower=method.lower(),
            base_path=html.escape(base_path, quote=True), path=html.escape(path),
            status=result.status, status_cls=status_cls,
            code=result.code if result.code is not None else '-', code_cls=code_cls,
            ms=result.elapsed_ms, slow_cls=slow_cls, ok=str(result.ok).lower(),
            req=self._highlight(shorten('\n'.join(req_lines))),
            resp=self._highlight(shorten(resp_text)),
        )
        self.extras.append(html_extras.html(detail))

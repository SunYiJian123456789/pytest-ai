# -*- coding: utf-8 -*-
"""通用权限矩阵（framework 内核）：登录后权限校验的数据驱动模板。

解决的问题：把"谁（角色/匿名）在什么状态下访问哪些接口、应该被允许还是拒绝"
从散落在各测试文件的断言，收敛成一份 YAML 矩阵 + 一个参数化用例。

设计约束：
- 角色名与 token 的映射由业务项目提供（``role_tokens`` fixture），内核不认识
  "admin/user/reviewer" 这些业务角色；
- 每条用例描述"请求要素 + 期望结果"，支持 HTTP 状态与业务 code 双层断言；
- 跨用户资源场景（A 的 token 访问 B 的资源）通过 ``token_from`` 指向另一个
  角色变量，同样是数据驱动，无需写业务代码。

YAML 行格式（数据集里的每条映射）::

    - label: 未登录访问管理端商品
      role: anonymous          # role_tokens 里的 key；anonymous 表示不带 token
      method: GET
      path: /api/private/resource
      expect_http: 401         # 可选，期望 HTTP 状态
      expect_code: 401         # 可选，期望业务 code
      message_has: 未登录      # 可选，响应消息包含
      params: {}               # 可选，query 参数
      json_body: null          # 可选，请求体
"""
from typing import Any, Callable, Dict, Optional

from framework.client import ApiClient, ApiResult
from framework.extract import MISSING

ANONYMOUS = 'anonymous'


class PermissionRow:
    """一行权限用例，把 YAML 映射包装成带默认值的对象。"""

    FIELDS = ('label', 'role', 'method', 'path', 'expect_http', 'expect_code',
              'message_has', 'params', 'json_body', 'token_from')

    def __init__(self, raw: dict):
        if not isinstance(raw, dict):
            raise TypeError('权限矩阵行必须是 dict，实际 %s' % type(raw).__name__)
        self.raw = raw
        self.label = raw.get('label') or '%s %s' % (raw.get('method', '?'), raw.get('path', '?'))
        self.role = raw.get('role', ANONYMOUS)
        self.method = raw.get('method', 'GET').upper()
        self.path = raw.get('path', '')
        self.expect_http = raw.get('expect_http', MISSING)
        self.expect_code = raw.get('expect_code', MISSING)
        self.message_has = raw.get('message_has', '')
        self.params = raw.get('params')
        self.json_body = raw.get('json_body', MISSING)
        self.token_from = raw.get('token_from', '')  # 跨用户：取另一个角色的 token

    def describe(self) -> str:
        expect = []
        if self.expect_http is not MISSING:
            expect.append('HTTP %s' % self.expect_http)
        if self.expect_code is not MISSING:
            expect.append('code %s' % self.expect_code)
        if self.message_has:
            expect.append('消息含 %r' % self.message_has)
        return '[%s] %s %s（%s）' % (
            self.label, self.method, self.path, ' / '.join(expect) or '仅断言可达'
        )


def check_permission(api: ApiClient, row: dict | PermissionRow,
                     role_tokens: Dict[str, str], *,
                     token_resolver: Optional[Callable[[str], str]] = None) -> ApiResult:
    """执行一行权限用例并按期望断言，返回 ApiResult 供业务层追加断言。

    - ``role_tokens``：角色名 → token 字符串，由业务项目提供；
    - ``token_from``：跨用户场景时，从 role_tokens 取该 key 的 token 覆盖当前角色；
    - ``token_resolver``：可选回调，业务项目自定义"角色→凭证"逻辑（如现场注册用户）。
    """
    case = row if isinstance(row, PermissionRow) else PermissionRow(row)
    if not case.path:
        raise ValueError('权限用例缺少 path：%r' % case.raw)

    if token_resolver is not None:
        token = token_resolver(case.token_from or case.role)
    elif case.token_from:
        if case.token_from not in role_tokens:
            raise KeyError('用例 %s 引用了未定义的 token_from=%r；可选：%s'
                           % (case.label, case.token_from, sorted(role_tokens)))
        token = role_tokens[case.token_from]
    elif case.role == ANONYMOUS:
        token = None
    else:
        if case.role not in role_tokens:
            available = sorted(set(role_tokens) | {ANONYMOUS})
            raise KeyError('用例 %s 引用了未定义的角色 %r；可选：%s'
                           % (case.label, case.role, available))
        token = role_tokens[case.role]

    kw: Dict[str, Any] = {'token': token}
    if case.params is not None:
        kw['params'] = case.params
    if case.json_body is not MISSING:
        kw['json_body'] = case.json_body

    result = api.request(case.method, case.path, **kw)
    hint = case.describe()
    if case.expect_http is not MISSING:
        assert result.status == case.expect_http, (
            '%s → HTTP 期望 %s，实际 %s；%r' % (hint, case.expect_http, result.status, result)
        )
    if case.expect_code is not MISSING:
        assert result.code == case.expect_code, (
            '%s → 业务 code 期望 %s，实际 %s；%r' % (hint, case.expect_code, result.code, result)
        )
    if case.message_has:
        assert case.message_has in (result.message or ''), (
            '%s → 消息应包含 %r，实际 %r；%r'
            % (hint, case.message_has, result.message, result)
        )
    return result


def run_matrix(api: ApiClient, rows, role_tokens: Dict[str, str], **kwargs):
    """批量执行一组权限用例；失败信息自动带行描述，便于定位 YAML 行。"""
    results = []
    for raw in rows:
        results.append(check_permission(api, raw, role_tokens, **kwargs))
    return results

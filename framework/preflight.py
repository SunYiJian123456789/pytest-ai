# -*- coding: utf-8 -*-
"""启动体检（framework 内核）：环境没准备好时立刻中止，不让用例逐个变红。

要解决的问题：后端没启动、MySQL 连不上、账号密码写错时，上百条用例会各报一次
``ConnectionRefused``。看报告的人要翻完全部红叉，才能发现根因其实是「服务没起」。

做法：把「服务可达 → 服务自检 → 依赖可用 → 登录可用」收敛成一组有序检查，
在 ``pytest_sessionstart``（用例收集之前）跑一次。任一必检项失败就抛
``pytest.UsageError``，终端只输出一条 ``ERROR: ...`` 并以退出码 4 结束，
**一条用例都不执行**。

用法::

    from framework.preflight import Check, Preflight

    def pytest_sessionstart(session):
        if session.config.getoption('collectonly', False):
            return
        Preflight([
            Check('后端可达', ping_backend, hint='先启动被测服务'),
            Check('数据库可用', ping_db, required=DB_STRICT),  # 本地无库不阻断
            Check('登录可用', login_all),
        ]).run_or_exit()

检查函数约定：

- 正常返回 → 通过，返回值（str）作为明细，如 ``HTTP 200 · code 200 · 8 ms``；
- 返回 ``False`` → 失败（无明细）；
- 抛异常 → 失败，异常消息作为原因（推荐 ``AssertionError``，消息直接可读）；
- 抛 ``Skipped`` → 跳过：前置条件没满足（如后端不可达时没必要再逐个账号登录），
  不算失败也不阻断，汇总里单独标注，避免把「没测」显示成「失败」。

只捕获 ``Exception``：``KeyboardInterrupt`` / ``SystemExit`` 照常中断，
Ctrl+C 不会被体检吞掉。

开关（无前缀，所有项目共用，与 ``API_*`` 请求层配置一致）：

- ``API_PREFLIGHT_ENABLED=0``：关闭体检（``--collect-only`` 始终跳过）；
- ``API_PREFLIGHT_STRICT=0``：必检项失败只告警不中止（应急放行，不推荐常用）。
"""
import time
import warnings
from dataclasses import asdict, dataclass
from typing import Any, Callable, List, Optional

import pytest

from framework.config import env

# 失败原因截断长度：体检信息要能一眼看完，不把整段堆栈塞进一行
DETAIL_LIMIT = 300

OK, WARN, FAIL, SKIP = 'OK', 'WARN', 'FAIL', 'SKIP'
MARKERS = {OK: '[ OK ]', WARN: '[WARN]', FAIL: '[FAIL]', SKIP: '[SKIP]'}

# 最近一次体检结果：进程内全局，供 run_summary 等沉淀入口采集（xdist 下各 worker 独立）
RECORDS: List[dict] = []

# 本轮是否因体检未通过而中止（用例零执行）。覆盖率等沉淀入口据此跳过，
# 避免「环境没备好」被渲染成「覆盖率从 100% 掉到 3%」的假回归。
ABORTED = False


def records() -> List[dict]:
    """返回最近一次体检结果的副本（未被执行过时为空列表）。"""
    return [dict(row) for row in RECORDS]


def aborted() -> bool:
    """本轮是否被启动体检中止（用例一条都没跑）。"""
    return ABORTED


@dataclass
class Check:
    """一项检查：名称 + 执行函数；required=False 的失败降级为告警。"""

    name: str
    func: Callable[[], Any]
    required: bool = True
    hint: str = ''


class Skipped(Exception):
    """检查项跳过：前置条件没满足（如后端不可达时没必要再逐个账号登录）。

    跳过不是失败，不阻断；在汇总里单独标注，避免把「没测」显示成「失败」。
    """


@dataclass
class CheckResult:
    name: str
    state: str
    detail: str = ''
    hint: str = ''
    elapsed_ms: int = 0

    @property
    def blocking(self) -> bool:
        """是否阻断本轮运行（只有必检项失败且开启 strict 才阻断）。"""
        return self.state == FAIL


def _flag(name: str, default: bool) -> bool:
    value = env(name, '1' if default else '0').strip().lower()
    return value in ('1', 'true', 'yes', 'on')


def _norm(text: Any) -> str:
    """压成单行并截断：体检结果要能一眼看完，不把多行堆栈铺开。"""
    return ' '.join(str(text).split())[:DETAIL_LIMIT]


def _detail_of(exc: BaseException) -> str:
    text = _norm(exc)
    if isinstance(exc, AssertionError):
        return text or 'AssertionError'
    return _norm('%s: %s' % (type(exc).__name__, text))


class Preflight:
    """一组有序检查；执行完统一汇总，失败即中止。"""

    def __init__(self, checks, *, strict: Optional[bool] = None,
                 enabled: Optional[bool] = None):
        self.checks = list(checks)
        self.strict = _flag('API_PREFLIGHT_STRICT', True) if strict is None else strict
        self.enabled = _flag('API_PREFLIGHT_ENABLED', True) if enabled is None else enabled
        self.results: List[CheckResult] = []

    # ---------- 执行 ----------

    def run(self) -> List[CheckResult]:
        """顺序执行全部检查（不在第一个失败处停下，一轮就把问题说全）。"""
        self.results = []
        if not self.enabled:
            return self.results
        for check in self.checks:
            started = time.perf_counter()
            state, detail = self._run_one(check)
            elapsed = int((time.perf_counter() - started) * 1000)
            self.results.append(
                CheckResult(check.name, state, detail, check.hint, elapsed))
        RECORDS[:] = [asdict(row) for row in self.results]
        return self.results

    def _run_one(self, check: Check):
        try:
            value = check.func()
        except Skipped as exc:
            return SKIP, _norm(exc)
        except Exception as exc:  # noqa: BLE001 - 失败原因要原样呈现给使用者
            return self._failed_state(check), _detail_of(exc)
        if value is False:
            return self._failed_state(check), '检查返回 False'
        return OK, '' if value is None else _norm(value)

    def _failed_state(self, check: Check) -> str:
        return FAIL if (check.required and self.strict) else WARN

    # ---------- 结果 ----------

    @property
    def blocking(self) -> List[CheckResult]:
        return [row for row in self.results if row.blocking]

    @property
    def warnings(self) -> List[CheckResult]:
        return [row for row in self.results if row.state == WARN]

    @property
    def passed(self) -> bool:
        return not self.blocking

    @staticmethod
    def _row_line(row: CheckResult) -> str:
        detail = ' — %s' % row.detail if row.detail else ''
        return '  %s %s%s（%d ms）' % (
            MARKERS[row.state], row.name, detail, row.elapsed_ms)

    def summary(self) -> str:
        """失败时给终端看的一段话：逐项状态 + 失败原因 + 排查提示。"""
        failed = self.blocking
        if not failed:
            return ''
        head = '启动体检未通过：%d 项检查中 %d 项失败' % (len(self.results), len(failed))
        extras = []
        if self.warnings:
            extras.append('%d 项告警' % len(self.warnings))
        skipped = [row for row in self.results if row.state == SKIP]
        if skipped:
            extras.append('%d 项跳过' % len(skipped))
        if extras:
            head += '、' + '、'.join(extras)
        head += '，本次未执行任何用例。'
        lines = [head, '']
        for row in self.results:
            lines.append(self._row_line(row))
            if row.state == FAIL and row.hint:
                lines.append('         提示：%s' % row.hint)
        lines += ['', '修好环境后重跑；若只想先跑与后端无关的用例，'
                      '可设 API_PREFLIGHT_STRICT=0 只告警不中止。']
        return '\n'.join(lines)

    def warn_summary(self) -> str:
        """未阻断但有告警时，给 warnings 汇总用的一行摘要。"""
        rows = self.warnings
        if not rows or self.blocking:
            return ''
        return '启动体检有 %d 项告警（不中止）：%s' % (
            len(rows), '；'.join('%s — %s' % (row.name, row.detail) for row in rows))

    def run_or_exit(self) -> List[CheckResult]:
        """执行体检：必检项失败抛 ``pytest.UsageError``（退出码 4），否则返回结果。"""
        global ABORTED
        ABORTED = False
        self.run()
        if self.blocking:
            ABORTED = True
            raise pytest.UsageError(self.summary())
        message = self.warn_summary()
        if message:
            warnings.warn(message, UserWarning, stacklevel=2)
        return self.results

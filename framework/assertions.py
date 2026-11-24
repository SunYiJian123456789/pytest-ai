# -*- coding: utf-8 -*-
"""通用接口断言库（framework 内核）。

把项目里反复出现的断言模式收敛到这里，换系统后用例仍可复用同一套断言。
失败信息统一用 ``ApiResult.describe()`` 的一行摘要（HTTP / code / message / url），
不再整段 repr，报告里一屏能放下多条失败。

两类断言：

- **硬断言** ``assert_ok / assert_code / ...``：首个不符即中断，适合「前提条件」；
- **软断言** ``SoftAssert``：累积多条失败，末尾 ``assert_all()`` 一次抛出，
  适合「一条响应要核对多个字段」——避免第一个字段错了就看不到后面还有哪些问题。
"""
from typing import Any, Iterable

from framework.config import env


def describe_result(result) -> str:
    """失败信息里优先用 ApiResult.describe() 的一行摘要，退化时回落到 repr。"""
    describe = getattr(result, 'describe', None)
    if callable(describe):
        try:
            return describe()
        except Exception:  # noqa: BLE001 - 摘要失败不能掩盖原始断言失败
            pass
    return repr(result)


def _detail(result, hint: str) -> str:
    text = describe_result(result)
    return ('%s → %s' % (hint, text)) if hint else text


def sla_scale() -> float:
    """耗时预算的整体放宽倍数，来自 API_SLA_SCALE，非法值回落到 1.0。

    慢机器、CI、容器环境下用它整体放大预算，避免把性能断言写成 flaky 源；
    正常环境保持 1.0，改的是环境而不是用例。
    """
    raw = env('API_SLA_SCALE', '').strip()
    if not raw:
        return 1.0
    try:
        scale = float(raw)
    except ValueError:
        return 1.0
    return scale if scale > 0 else 1.0


def assert_elapsed(result, max_ms: float, hint: str = ''):
    """断言单次请求耗时不超过预算（毫秒），预算 = max_ms × API_SLA_SCALE。

    只用在高价值链路（健康检查、登录、列表、加购、支付），阈值按本机实测
    中位数留出两个数量级余量，目的是抓「功能没坏但慢到不可用」的劣化，
    不是压着真实值卡秒表。
    """
    scale = sla_scale()
    budget = max_ms * scale
    assert result.elapsed_ms <= budget, (
        '%s：耗时 %d ms 超出预算 %.0f ms（基准 %.0f ms × API_SLA_SCALE %.2f）→ %s'
        % (hint or '响应耗时', result.elapsed_ms, budget, max_ms, scale, describe_result(result))
    )
    return result


def assert_ok(result, hint: str = ''):
    assert result.ok, _detail(result, hint or '期望接口成功')
    return result


def assert_status(result, expected: int, hint: str = ''):
    assert result.status == expected, '%s HTTP 状态应为 %s，实际 %s → %s' % (
        hint, expected, result.status, describe_result(result),
    )
    return result


def assert_code(result, expected: Any, hint: str = ''):
    assert result.code == expected, '%s 业务 code 应为 %s，实际 %s → %s' % (
        hint, expected, result.code, describe_result(result),
    )
    return result


def assert_code_not(result, unexpected: Any, hint: str = ''):
    assert result.code != unexpected, '%s 业务 code 不应为 %s → %s' % (
        hint, unexpected, describe_result(result),
    )
    return result


def assert_message_contains(result, fragment: str, hint: str = ''):
    assert fragment in (result.message or ''), '%s 响应消息应包含 %r，实际 %r → %s' % (
        hint, fragment, result.message, describe_result(result),
    )
    return result


def assert_fields(data: Any, *fields: str, hint: str = ''):
    assert isinstance(data, dict), '%s 期望字典响应，实际 %s' % (hint, type(data).__name__)
    missing = [f for f in fields if f not in data]
    assert not missing, '%s 响应缺少字段 %s：%r' % (hint, missing, data)
    return data


def assert_numeric_fields(data: Any, *fields: str, hint: str = ''):
    assert_fields(data, *fields, hint=hint)
    for field in fields:
        assert isinstance(data[field], (int, float)) and not isinstance(data[field], bool), \
            '%s 字段 %s 应为数字，实际 %r' % (hint, field, data[field])
    return data


def assert_list_not_empty(data: Any, hint: str = ''):
    assert isinstance(data, list) and data, '%s 期望非空列表，实际 %r' % (hint, data)
    return data


def assert_contains_row(rows: Iterable[dict], key: str, value: Any, hint: str = ''):
    rows = list(rows)
    assert any(row.get(key) == value for row in rows), \
        '%s 未在列表中找到 %s=%r，共 %d 条' % (hint, key, value, len(rows))
    return rows


class SoftAssert:
    """软断言收集器：累积多条失败，末尾 ``assert_all()`` 一次抛出。

    典型用法::

        def test_pay(soft, api):
            result = api.post('/api/pay', json_body={'amount': 100})
            soft.ok(result, '支付')
            soft.equal(result.data.get('status'), 'SUCCESS', '订单状态')
            soft.equal(result.data.get('amount'), 100, '订单金额')
            soft.assert_all()          # 三处问题一起报出来

    方法返回布尔值，需要分支时仍可 ``if not soft.equal(...): ...``。
    """

    def __init__(self, hint: str = ''):
        self.hint = hint
        self.failures: list[str] = []

    # ---------- 通用 ----------
    def check(self, condition: Any, message: str) -> bool:
        ok = bool(condition)
        if not ok:
            self.failures.append(message)
        return ok

    def equal(self, actual: Any, expected: Any, label: str) -> bool:
        return self.check(actual == expected,
                          '%s：期望 %r，实际 %r' % (label, expected, actual))

    def contains(self, container: Any, expected: Any, label: str) -> bool:
        try:
            found = expected in container
        except TypeError:
            found = False
        return self.check(found, '%s：期望包含 %r，实际 %r' % (label, expected, container))

    def fields_present(self, data: Any, *fields: str, label: str = '响应') -> bool:
        missing = [f for f in fields if not isinstance(data, dict) or f not in data]
        return self.check(not missing, '%s：缺少字段 %s' % (label, missing))

    # ---------- 针对 ApiResult ----------
    def ok(self, result, hint: str = '') -> bool:
        return self.check(result.ok, _detail(result, hint or '期望接口成功'))

    def status(self, result, expected: int, hint: str = '') -> bool:
        return self.check(result.status == expected,
                          '%s：HTTP 状态期望 %s，实际 %s → %s'
                          % (hint or 'HTTP 状态', expected, result.status, describe_result(result)))

    def code(self, result, expected: Any, hint: str = '') -> bool:
        return self.check(result.code == expected,
                          '%s：业务 code 期望 %s，实际 %s → %s'
                          % (hint or '业务 code', expected, result.code, describe_result(result)))

    # ---------- 收口 ----------
    @property
    def passed(self) -> bool:
        return not self.failures

    def assert_all(self) -> None:
        """把累积的失败合并成一条 AssertionError；全部通过则什么都不做。"""
        if not self.failures:
            return
        head = '%d 项断言失败' % len(self.failures)
        if self.hint:
            head = '%s：%s' % (self.hint, head)
        raise AssertionError(head + '：\n' + '\n'.join('  · %s' % row for row in self.failures))

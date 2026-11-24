# -*- coding: utf-8 -*-
"""通用接口断言库（framework 内核）。

把项目里反复出现的断言模式收敛到这里，换系统后用例仍可复用同一套断言。
断言失败信息统一带上 ApiResult 的 URL / status / code，便于定位。
"""
from typing import Any, Iterable

from framework.config import env


def _detail(result, hint: str) -> str:
    return ('%s → %r' % (hint, result)) if hint else repr(result)


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
        % (hint or '响应耗时', result.elapsed_ms, budget, max_ms, scale, result.describe())
    )
    return result


def assert_ok(result, hint: str = ''):
    assert result.ok, _detail(result, hint or '期望接口成功')
    return result


def assert_status(result, expected: int, hint: str = ''):
    assert result.status == expected, '%s HTTP 状态应为 %s，实际 %s：%r' % (
        hint, expected, result.status, result,
    )
    return result


def assert_code(result, expected: Any, hint: str = ''):
    assert result.code == expected, '%s 业务 code 应为 %s，实际 %s：%r' % (
        hint, expected, result.code, result,
    )
    return result


def assert_code_not(result, unexpected: Any, hint: str = ''):
    assert result.code != unexpected, '%s 业务 code 不应为 %s：%r' % (
        hint, unexpected, result,
    )
    return result


def assert_message_contains(result, fragment: str, hint: str = ''):
    assert fragment in (result.message or ''), '%s 响应消息应包含 %r，实际 %r：%r' % (
        hint, fragment, result.message, result,
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

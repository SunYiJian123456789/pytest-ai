# -*- coding: utf-8 -*-
"""通用接口断言库（framework 内核）。

把项目里反复出现的断言模式收敛到这里，换系统后用例仍可复用同一套断言。
断言失败信息统一带上 ApiResult 的 URL / status / code，便于定位。
"""
from typing import Any, Iterable


def _detail(result, hint: str) -> str:
    return ('%s → %r' % (hint, result)) if hint else repr(result)


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

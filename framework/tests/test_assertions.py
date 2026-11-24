# -*- coding: utf-8 -*-
"""内核单测：耗时预算、失败信息摘要、软断言，不依赖真实服务。"""
import pytest

from framework.assertions import (
    SoftAssert, assert_code, assert_elapsed, describe_result, sla_scale,
)
from framework.client import ApiResult, Envelope


def make_result(elapsed_ms=10):
    return ApiResult(
        status=200, code=200, message='success', data={'id': 1},
        elapsed_ms=elapsed_ms, raw='{"code":200}', url='http://fake/api/x',
        envelope=Envelope(), payload={'code': 200, 'message': 'success', 'data': {'id': 1}},
    )


class TestSlaScale:
    def test_defaults_to_one(self, monkeypatch):
        monkeypatch.delenv('API_SLA_SCALE', raising=False)
        assert sla_scale() == 1.0

    def test_reads_env(self, monkeypatch):
        monkeypatch.setenv('API_SLA_SCALE', '2.5')
        assert sla_scale() == 2.5

    @pytest.mark.parametrize('raw', ['abc', '', '0', '-3'])
    def test_invalid_value_falls_back_to_one(self, monkeypatch, raw):
        monkeypatch.setenv('API_SLA_SCALE', raw)
        assert sla_scale() == 1.0


class TestAssertElapsed:
    def test_passes_within_budget(self):
        assert assert_elapsed(make_result(120), 500, '列表') is not None

    def test_passes_exactly_on_budget(self):
        assert_elapsed(make_result(500), 500)

    def test_fails_over_budget(self):
        with pytest.raises(AssertionError) as exc:
            assert_elapsed(make_result(501), 500, '列表')
        message = str(exc.value)
        assert '列表' in message
        assert '501' in message and '500' in message

    def test_scale_widens_budget(self, monkeypatch):
        monkeypatch.setenv('API_SLA_SCALE', '3')
        assert_elapsed(make_result(1400), 500)  # 预算放大到 1500

    def test_scale_still_fails_beyond_widened_budget(self, monkeypatch):
        monkeypatch.setenv('API_SLA_SCALE', '3')
        with pytest.raises(AssertionError):
            assert_elapsed(make_result(1501), 500)

    def test_message_uses_one_line_describe(self):
        with pytest.raises(AssertionError) as exc:
            assert_elapsed(make_result(900), 100, '支付')
        message = str(exc.value)
        assert 'API_SLA_SCALE' in message
        assert 'HTTP 200' in message  # describe() 的一行摘要，而非整段 repr


def make_failure(status=500, code=None):
    return ApiResult(
        status=status, code=code, message='', data=None,
        elapsed_ms=5, raw='{"status":500}', url='http://fake/api/x', envelope=Envelope(),
    )


class TestDescribeResult:
    def test_uses_one_line_summary(self):
        assert describe_result(make_result(5)).startswith('HTTP 200')

    def test_falls_back_to_repr(self):
        class Plain:
            def __repr__(self):
                return 'RAW-REPR'

        assert describe_result(Plain()) == 'RAW-REPR'

    def test_hard_assert_message_uses_describe(self):
        with pytest.raises(AssertionError) as exc:
            assert_code(make_result(5), 400, '下单')
        text = str(exc.value)
        assert 'HTTP 200' in text
        assert 'ApiResult(' not in text, '失败信息不应再带整段 repr'


class TestSoftAssert:
    def test_collects_every_failure_then_raises_once(self):
        soft = SoftAssert()
        soft.equal(1, 2, '状态')
        soft.equal(3, 3, '命中')
        soft.equal('x', 'y', '金额')
        assert not soft.passed and len(soft.failures) == 2

        with pytest.raises(AssertionError) as exc:
            soft.assert_all()
        text = str(exc.value)
        assert '2 项断言失败' in text
        assert '状态：期望 2，实际 1' in text
        assert '金额：期望' in text
        assert '命中' not in text

    def test_passes_silently(self):
        soft = SoftAssert()
        soft.equal(1, 1, 'a')
        soft.contains([1, 2], 2, 'b')
        soft.assert_all()  # 不抛

    def test_result_helpers(self):
        soft = SoftAssert()
        soft.ok(make_failure())
        soft.status(make_failure(), 200)
        soft.code(make_failure(), 200)
        assert len(soft.failures) == 3
        with pytest.raises(AssertionError) as exc:
            soft.assert_all()
        assert 'HTTP 500' in str(exc.value)

    def test_result_helpers_pass(self):
        soft = SoftAssert()
        soft.ok(make_result(5))
        soft.status(make_result(5), 200)
        soft.code(make_result(5), 200)
        assert soft.passed

    def test_fields_present(self):
        soft = SoftAssert()
        soft.fields_present({'a': 1}, 'a', 'b', label='响应')
        assert len(soft.failures) == 1 and 'b' in soft.failures[0]

    def test_hint_is_prefixed(self):
        soft = SoftAssert(hint='支付')
        soft.equal(1, 2, '金额')
        with pytest.raises(AssertionError) as exc:
            soft.assert_all()
        assert str(exc.value).startswith('支付：1 项断言失败')

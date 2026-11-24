# -*- coding: utf-8 -*-
"""内核单测：响应耗时断言（预算、放宽倍数、非法配置兜底），不依赖真实服务。"""
import pytest

from framework.assertions import assert_elapsed, sla_scale
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

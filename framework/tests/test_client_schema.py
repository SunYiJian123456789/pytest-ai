# -*- coding: utf-8 -*-
"""内核单测：请求重试 / trace_id / 响应契约校验 / 敏感信息脱敏，不依赖真实服务。"""
import requests
import pytest

from framework.client import (
    DEFAULT_SENSITIVE_KEYS, MASK, ApiClient, ApiResult, Envelope, mask_sensitive,
)
from framework.schema import assert_data_schema, assert_schema, schema_from_yaml


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.url = 'http://fake/test'
        self.headers = {'Content-Type': 'application/json'}

    def json(self):
        return self._payload


OK = {'code': 200, 'message': 'success', 'data': {'id': 1}}


def result(payload=OK):
    return ApiResult(
        status=200, code=200, message='success', data=payload.get('data'),
        elapsed_ms=1, raw=str(payload), url='http://fake/test',
        envelope=Envelope(), payload=payload,
    )


class TestRetryAndTrace:
    def test_trace_header_injected(self):
        client = ApiClient('http://fake', retry_backoff=0)
        seen = {}

        def fake(method, url, **kw):
            seen.update(kw['headers'])
            return FakeResponse(payload=OK)

        client.session.request = fake
        r = client.get('/test')
        assert len(r.trace_id) == 32
        assert seen['X-Trace-Id'] == r.trace_id
        assert r.attempts == 1

    def test_trace_can_be_disabled_and_renamed(self):
        client = ApiClient('http://fake', trace_enabled=False, retry_backoff=0)
        seen = {}

        def fake(method, url, **kw):
            seen.update(kw['headers'])
            return FakeResponse(payload=OK)

        client.session.request = fake
        client.get('/test')
        assert 'X-Trace-Id' not in seen

        client = ApiClient('http://fake', trace_header='X-Request-ID', retry_backoff=0)
        client.session.request = lambda method, url, **kw: (seen.update(kw['headers']) or FakeResponse(payload=OK))
        client.get('/test')
        assert 'X-Request-ID' in seen

    def test_network_error_retries_with_same_trace(self):
        client = ApiClient('http://fake', retry_backoff=0)
        traces = []
        calls = []

        def fake(method, url, **kw):
            traces.append(kw['headers']['X-Trace-Id'])
            calls.append(1)
            if len(calls) == 1:
                raise requests.ConnectionError('boom')
            return FakeResponse(payload=OK)

        client.session.request = fake
        r = client.get('/test')
        assert r.attempts == 2 and r.ok
        assert len(set(traces)) == 1 and traces[0] == r.trace_id

    def test_get_5xx_retries_but_post_does_not(self):
        client = ApiClient('http://fake', retry_backoff=0)
        calls = []

        def fake(method, url, **kw):
            calls.append(method)
            return FakeResponse(500, {'code': 500, 'message': 'err', 'data': None})

        client.session.request = fake
        assert client.get('/test').attempts == 2
        assert client.post('/test').attempts == 1
        assert calls.count('GET') == 2 and calls.count('POST') == 1

    def test_business_code_failure_is_not_retried(self):
        client = ApiClient('http://fake', retry_backoff=0)
        calls = []

        def fake(method, url, **kw):
            calls.append(1)
            return FakeResponse(payload={'code': 400, 'message': 'bad', 'data': None})

        client.session.request = fake
        r = client.get('/test')
        assert r.attempts == 1 and not r.ok and len(calls) == 1


class TestSchema:
    def test_valid_schema_passes(self):
        assert_schema(result(), {
            'type': 'object', 'required': ['code', 'data'],
            'properties': {'code': {'const': 200}},
        })

    def test_missing_field_reports_exact_path(self):
        schema = {
            'type': 'object',
            'properties': {'data': {'type': 'object', 'required': ['token']}},
        }
        with pytest.raises(AssertionError) as exc:
            assert_schema(result(), schema, label='登录响应')
        assert '登录响应' in str(exc.value)
        assert 'data.token' in str(exc.value)
        assert '响应体' in str(exc.value)

    def test_data_root(self):
        assert_data_schema(result(), {
            'type': 'object', 'required': ['id'],
            'properties': {'id': {'type': 'integer', 'minimum': 1}},
        })

    def test_schema_from_yaml_missing_name(self):
        with pytest.raises(KeyError) as exc:
            schema_from_yaml({'health': {}}, 'unknown')
        assert 'unknown' in str(exc.value)
        assert 'health' in str(exc.value)


class TestSensitiveMasking:
    def test_mask_nested_body_without_mutating_source(self):
        body = {'username': 'demo', 'password': 'p@ss',
                'items': [{'name': 'x', 'token': 'T'}]}
        masked = mask_sensitive(body, frozenset(DEFAULT_SENSITIVE_KEYS))
        assert masked['username'] == 'demo' and masked['password'] == MASK
        assert masked['items'][0]['name'] == 'x' and masked['items'][0]['token'] == MASK
        assert body['password'] == 'p@ss' and body['items'][0]['token'] == 'T'  # 原数据不变

    def test_login_body_and_token_masked_in_report(self):
        client = ApiClient('http://fake', retry_backoff=0, archive_failures=False)
        captured = []
        client.extras = captured

        def fake(method, url, **kw):
            return FakeResponse(payload={'code': 200, 'message': 'ok',
                                         'data': {'token': 'SECRET-TOKEN', 'id': 1}})

        client.session.request = fake
        client.post('/login', json_body={'username': 'u', 'password': 'p'})
        detail = captured[-1]['content']
        assert MASK in detail and ': &quot;******&quot;' in detail  # 敏感值被掩码替换
        assert 'SECRET-TOKEN' not in detail                         # token 值未泄漏
        assert '&quot;username&quot;' in detail and '&quot;u&quot;' in detail  # 非敏感键值正常展示

    def test_result_raw_is_masked_for_failure_messages(self):
        """断言失败消息（extract/schema）会带响应体，raw 必须在构造时就脱敏。"""
        client = ApiClient('http://fake', retry_backoff=0, archive_failures=False)
        client.session.request = lambda method, url, **kw: FakeResponse(
            payload={'code': 401, 'message': 'bad', 'data': {'token': 'SECRET-TOKEN'}})
        r = client.get('/secure')
        assert 'SECRET-TOKEN' not in r.raw and MASK in r.raw

    def test_sensitive_keys_overridable_via_env(self, monkeypatch):
        monkeypatch.setenv('API_SENSITIVE_KEYS', 'card_no')
        client = ApiClient('http://fake', retry_backoff=0)
        assert 'card_no' in client.sensitive_keys
        assert 'password' not in client.sensitive_keys  # 显式覆盖即完全替换默认清单

# -*- coding: utf-8 -*-
"""内核单测：Cookie 优先后端的身份串号守护，不依赖真实服务。

守护检测「同一客户端换 token 但会话残留 Cookie」的高危条件：
- off：静默；
- warn（默认）：发 UserWarning，不阻断（兼容既有用例）；
- strict：抛 IdentityConflictError，把静默假绿变成显式失败。

二次登录、显式传 token 切换、clear_cookies 后复用都要覆盖。
"""
import warnings

import pytest

from framework.auth import AuthSpec
from framework.client import ApiClient, IdentityConflictError


class FakeCookie:
    pass


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {'code': 200, 'data': {}}
        self.url = 'http://fake/test'
        self.headers = {'Content-Type': 'application/json'}

    def json(self):
        return self._payload


def _client(guard='warn', token=None):
    """建一个带独立 session 的客户端，请求用 fake 响应。"""
    client = ApiClient('http://fake', cookie_guard=guard, default_token=token)
    client.session.request = lambda method, url, **kw: FakeResponse()
    return client


class TestIdentityGuardModes:
    def test_switch_token_with_cookie_warns_by_default(self):
        client = _client(token='userAAAAAAAA')
        client.session.cookies.set('session', 'old')
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            client.get('/api/auth/me', token='adminBBBBBBBB')
        assert any('身份串号风险' in str(w.message) for w in caught)

    def test_switch_token_with_cookie_fails_in_strict(self):
        client = _client(guard='strict', token='userAAAAAAAA')
        client.session.cookies.set('session', 'old')
        with pytest.raises(IdentityConflictError, match='身份串号风险'):
            client.get('/api/auth/me', token='adminBBBBBBBB')

    def test_switch_token_with_cookie_silent_in_off(self):
        client = _client(guard='off', token='userAAAAAAAA')
        client.session.cookies.set('session', 'old')
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            client.get('/api/auth/me', token='adminBBBBBBBB')
        assert not [w for w in caught if '身份串号风险' in str(w.message)]

    def test_invalid_guard_mode_rejected(self):
        with pytest.raises(ValueError, match='API_COOKIE_GUARD'):
            ApiClient('http://fake', cookie_guard='loud')


class TestNoFalsePositive:
    def test_first_token_request_no_warning(self):
        client = _client(guard='strict')
        client.session.cookies.set('session', 'anon')
        # 首条带 token 的请求不算切换
        client.get('/api/auth/me', token='userAAAAAAAA')

    def test_same_token_repeat_no_warning(self):
        client = _client(guard='strict', token='userAAAAAAAA')
        client.session.cookies.set('session', 'old')
        client.get('/api/auth/me')
        client.get('/api/products')

    def test_switch_without_cookie_no_warning(self):
        client = _client(guard='strict', token='userAAAAAAAA')
        assert len(client.session.cookies) == 0
        client.get('/api/auth/me', token='adminBBBBBBBB')

    def test_clear_cookies_allows_switch(self):
        client = _client(guard='strict', token='userAAAAAAAA')
        client.session.cookies.set('session', 'old')
        client.clear_cookies()
        client.get('/api/auth/me', token='adminBBBBBBBB')

    def test_env_guard_mode(self, monkeypatch):
        monkeypatch.setenv('API_COOKIE_GUARD', 'strict')
        assert ApiClient('http://fake').cookie_guard == 'strict'

    def test_register_then_use_returned_token_no_warning(self):
        """注册产生 Cookie，随后首次用注册返回的 token 请求属同一身份，不该告警。"""
        client = ApiClient('http://fake', cookie_guard='strict')
        def fake(method, url, **kw):
            if 'register' in url:
                client.session.cookies.set('session', 'new-user')
            return FakeResponse(payload={'code': 200, 'data': {'token': 'freshTOKEN1234'}})
        client.session.request = fake
        client.post('/api/auth/register', json_body={})
        # default_token 仍为空，首次显式传 token 不算切换
        client.get('/api/auth/me', token='freshTOKEN1234')

    def test_explicit_token_switch_after_login_warns(self):
        """登录确立身份后，显式切到他人 token 且带 Cookie，应触发守护。"""
        client = ApiClient('http://fake', cookie_guard='strict', auth=AuthSpec(),
                           default_token='aliceTOKEN1234')
        client.session.cookies.set('session', 'alice-cookie')
        with pytest.raises(IdentityConflictError, match='身份串号风险'):
            client.get('/api/resource', token='bobTOKEN5678')


class TestRepeatedLogin:
    def _authed_client(self, guard):
        client = ApiClient('http://fake', cookie_guard=guard, auth=AuthSpec())
        client.session.cookies.set('session', 'user-cookie')
        def fake(method, url, **kw):
            body = kw.get('json') or {}
            return FakeResponse(payload={'code': 200, 'data': {'token': body.get('username', '') + '-token'}})
        client.session.request = fake
        return client

    def test_second_login_same_user_ok(self):
        client = self._authed_client('strict')
        client.login('alice', 'pw')
        client.login('alice', 'pw')  # 同一身份，不告警

    def test_second_login_other_user_fails_in_strict(self):
        client = self._authed_client('strict')
        client.login('alice', 'pw')
        with pytest.raises(IdentityConflictError, match='身份串号风险'):
            client.login('bob', 'pw')

    def test_second_login_other_user_warns_by_default(self):
        client = self._authed_client('warn')
        client.login('alice', 'pw')
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            client.login('bob', 'pw')
        assert any('身份串号风险' in str(w.message) for w in caught)

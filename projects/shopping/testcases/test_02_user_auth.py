# -*- coding: utf-8 -*-
"""商城用户端：注册、登录、登录态、token 边界。"""
import pytest

from projects.shopping.helpers import uid
from projects.shopping.config import STORE_PASSWORD, STORE_USERNAME
from projects.shopping.data import cases


@pytest.mark.auth
def test_register_creates_user_and_returns_session(api, cleaner):
    username = uid('APIU')
    result = api.post('/api/auth/register', json_body={
        'username': username,
        'password': 'Test@123456',
        'nickname': '接口测试用户',
        'phone': '13800000000',
    })
    cleaner.user(username)
    assert result.ok, result
    assert result.data.get('token'), result.data
    assert result.data['user'].get('username') == username, result.data
    assert not result.data['user'].get('passwordHash'), result.data['user']


@pytest.mark.auth
def test_registered_token_can_read_me(api, cleaner):
    username = uid('APIU')
    registered = api.post('/api/auth/register', json_body={
        'username': username, 'password': 'Test@123456',
    })
    cleaner.user(username)
    assert registered.ok, registered
    me = api.get('/api/auth/me', token=registered.data['token'])
    assert me.ok and me.data['username'] == username, me


@pytest.mark.auth
@pytest.mark.parametrize('username,password', cases('register_short_credentials', 'username', 'password'))
def test_register_rejects_short_credentials(api, username, password):
    result = api.post('/api/auth/register', json_body={
        'username': username, 'password': password,
    })
    assert result.code == 400, result
    assert '至少' in result.message, result.message


@pytest.mark.auth
def test_register_rejects_duplicate_username(api, cleaner):
    username = uid('APIU')
    first = api.post('/api/auth/register', json_body={
        'username': username, 'password': 'Test@123456',
    })
    cleaner.user(username)
    assert first.ok, first
    again = api.post('/api/auth/register', json_body={
        'username': username, 'password': 'Test@123456',
    })
    assert again.code == 400 and '已被注册' in again.message, again


@pytest.mark.auth
@pytest.mark.smoke
def test_login_with_demo_account(api):
    result = api.post('/api/auth/login', json_body={
        'username': STORE_USERNAME, 'password': STORE_PASSWORD,
    })
    assert result.ok, result
    assert len(result.data['token']) == 32, result.data
    assert result.data['user']['username'] == STORE_USERNAME, result.data
    assert not result.data['user'].get('passwordHash'), result.data['user']


@pytest.mark.auth
def test_login_wrong_password(api):
    result = api.post('/api/auth/login', json_body={
        'username': STORE_USERNAME, 'password': 'wrong-password',
    })
    assert result.code == 401, result
    assert '不正确' in result.message, result.message


@pytest.mark.auth
def test_login_requires_both_fields(api):
    for body in ({}, {'username': STORE_USERNAME}, {'password': STORE_PASSWORD}):
        result = api.post('/api/auth/login', json_body=body)
        assert result.code == 400, (body, result)
        assert '请输入用户名和密码' in result.message, result.message


@pytest.mark.auth
def test_me_requires_valid_token(api):
    assert api.get('/api/auth/me').code == 401
    assert api.get('/api/auth/me', token='not-a-token').code == 401


@pytest.mark.auth
def test_logout_invalidates_token(api):
    login = api.post('/api/auth/login', json_body={
        'username': STORE_USERNAME, 'password': STORE_PASSWORD,
    })
    token = login.data['token']
    assert api.get('/api/auth/me', token=token).ok
    assert api.post('/api/auth/logout', token=token).ok
    assert api.get('/api/auth/me', token=token).code == 401


@pytest.mark.auth
def test_admin_token_cannot_read_store_me(api, admin_token):
    result = api.get('/api/auth/me', token=admin_token)
    assert result.code == 401, result

# -*- coding: utf-8 -*-
"""管理端独立登录与 token 隔离。"""
import pytest

from projects.shopping.config import ADMIN_ACCOUNTS, STORE_PASSWORD, STORE_USERNAME
from projects.shopping.data import cases


@pytest.mark.auth
@pytest.mark.admin
def test_admin_login_success(api):
    username, password = ADMIN_ACCOUNTS['admin']
    result = api.post('/api/admin/auth/login', json_body={
        'username': username, 'password': password,
    })
    assert result.ok, result
    assert result.data['token'].startswith('adm_'), result.data
    assert result.data['admin']['username'] == username, result.data
    assert not result.data['admin'].get('passwordHash'), result.data['admin']


@pytest.mark.auth
def test_admin_login_wrong_password(api):
    result = api.post('/api/admin/auth/login', json_body={
        'username': 'admin', 'password': 'wrong-password',
    })
    assert result.code == 401 and '不正确' in result.message, result


@pytest.mark.auth
def test_admin_login_requires_both_fields(api):
    for body in ({}, {'username': 'admin'}, {'password': 'admin123'}):
        result = api.post('/api/admin/auth/login', json_body=body)
        assert result.code == 400, (body, result)


@pytest.mark.auth
def test_store_user_cannot_login_admin(api):
    result = api.post('/api/admin/auth/login', json_body={
        'username': STORE_USERNAME, 'password': STORE_PASSWORD,
    })
    assert result.code == 401, result


@pytest.mark.auth
@pytest.mark.admin
def test_admin_me_returns_current_admin(api, admin_token):
    result = api.get('/api/admin/auth/me', token=admin_token)
    assert result.ok, result
    assert result.data['username'] == 'admin', result.data
    assert not result.data.get('passwordHash'), result.data


@pytest.mark.admin
@pytest.mark.parametrize('path', cases('admin_endpoints_require_login', 'path'))
def test_admin_endpoints_require_login(api, path):
    result = api.get(path)
    assert result.status == 401 and result.code == 401, (path, result)
    assert '管理端未登录' in result.message, result.message


@pytest.mark.auth
def test_user_token_cannot_access_admin(api, user_token):
    result = api.get('/api/admin/stats', token=user_token)
    assert result.status == 401, result


@pytest.mark.auth
def test_admin_token_cannot_access_store_me(api, admin_token):
    result = api.get('/api/auth/me', token=admin_token)
    assert result.code == 401, result


@pytest.mark.auth
def test_admin_logout_invalidates_token(api):
    login = api.post('/api/admin/auth/login', json_body={
        'username': 'admin', 'password': 'admin123',
    })
    token = login.data['token']
    assert api.get('/api/admin/auth/me', token=token).ok
    assert api.post('/api/admin/auth/logout', token=token).ok
    assert api.get('/api/admin/auth/me', token=token).code == 401


@pytest.mark.auth
def test_all_demo_admin_accounts_can_login(api):
    for role, (username, password) in ADMIN_ACCOUNTS.items():
        result = api.post('/api/admin/auth/login', json_body={
            'username': username, 'password': password,
        })
        assert result.ok, (role, result)

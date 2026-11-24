# -*- coding: utf-8 -*-
"""{{PROJECT}} 冒烟用例：演示通用断言 + YAML 数据驱动的写法。"""
import pytest

from framework.assertions import assert_ok
from projects.{{PROJECT}}.config import AUTH, BASE_URL
from projects.{{PROJECT}}.data import cases


@pytest.mark.smoke
def test_service_reachable(api):
    """健康检查返回 2xx 即可，不绑定具体响应结构。"""
    result = api.get('/api/health')
    assert 200 <= result.status < 300, result


@pytest.mark.smoke
def test_authenticated_request(api, token):
    result = api.get('/api/auth/me', token=token)
    assert_ok(result, '登录后访问个人信息')


@pytest.mark.parametrize('path', cases('smoke_paths', 'path'))
def test_paths_have_no_server_error(api, path):
    result = api.get(path)
    assert result.status < 500, result


def test_config_points_to_expected_host():
    assert BASE_URL.startswith(('http://', 'https://'))
    assert AUTH.login_path.startswith('/')

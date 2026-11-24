# -*- coding: utf-8 -*-
"""服务健康与统一响应结构。"""
import pytest

from framework.assertions import assert_elapsed
from projects.shopping.config import BASE_URL


@pytest.mark.smoke
def test_health_status_up(api):
    result = api.get('/api/health')
    assert result.status == 200, result
    assert result.ok, result
    assert result.data.get('status') == 'UP', result.data
    assert_elapsed(result, 500, '健康检查')


@pytest.mark.smoke
def test_health_declares_mysql_and_local_images(api):
    data = api.get('/api/health').data
    assert 'shopping_db' in data.get('database', ''), data
    assert 'local filesystem' in data.get('imageStorage', ''), data


def test_response_envelope_is_uniform(api):
    for path in ('/api/health', '/api/categories', '/api/banners'):
        result = api.get(path)
        assert result.status == 200, (path, result)
        assert result.code == 200, (path, result)
        assert result.message == 'success', (path, result)
        assert 'data' in result.raw, (path, result.raw[:200])


def test_undefined_endpoint_returns_404(api):
    result = api.get('/api/__definitely_not_exists__')
    assert result.status == 404, result


def test_targets_spring_boot_not_vite():
    assert ':8080' in BASE_URL, '接口测试应直连 Spring Boot 后端：' + BASE_URL

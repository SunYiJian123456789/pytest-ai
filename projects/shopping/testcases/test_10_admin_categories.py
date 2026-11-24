# -*- coding: utf-8 -*-
"""管理端分类管理：增删改查与引用保护。"""
import pytest

from projects.shopping.config import DEFAULT_CATEGORY_ID
from projects.shopping.helpers import uid


@pytest.mark.admin
def test_category_list_has_product_count(api, admin_token):
    result = api.get('/api/admin/categories', token=admin_token)
    assert result.ok and result.data, result
    for row in result.data:
        assert 'productCount' in row and 'name' in row, row
        assert isinstance(row['productCount'], int), row


@pytest.mark.admin
def test_create_category(api, tokens, cleaner):
    name = uid('APIC')
    result = api.post('/api/admin/categories', json_body={
        'name': name, 'icon': '🧪', 'description': '接口自动化分类',
        'sortOrder': 99,
    }, token=tokens['admin'])
    assert result.ok, result
    cleaner.category(result.data['id'])
    assert result.data['name'] == name, result.data
    assert any(row['id'] == result.data['id']
               for row in api.get('/api/admin/categories', token=tokens['admin']).data)


@pytest.mark.admin
def test_duplicate_category_name_rejected(api, tokens, cleaner):
    name = uid('APIC')
    first = api.post('/api/admin/categories', json_body={'name': name}, token=tokens['admin'])
    assert first.ok, first
    cleaner.category(first.data['id'])
    again = api.post('/api/admin/categories', json_body={'name': name}, token=tokens['admin'])
    assert again.code == 400 and '已存在' in again.message, again


@pytest.mark.admin
def test_update_category(api, tokens, cleaner):
    name = uid('APIC')
    created = api.post('/api/admin/categories', json_body={'name': name}, token=tokens['admin'])
    assert created.ok, created
    cleaner.category(created.data['id'])
    renamed = name + '-改'
    result = api.put('/api/admin/categories/%s' % created.data['id'], json_body={
        'name': renamed, 'icon': '🏷️', 'sortOrder': 98,
    }, token=tokens['admin'])
    assert result.ok and result.data['name'] == renamed, result


@pytest.mark.admin
def test_delete_empty_category(api, tokens, cleaner):
    name = uid('APIC')
    created = api.post('/api/admin/categories', json_body={'name': name}, token=tokens['admin'])
    assert created.ok, created
    result = api.delete('/api/admin/categories/%s' % created.data['id'], token=tokens['admin'])
    assert result.ok, result
    assert not any(row['id'] == created.data['id']
                   for row in api.get('/api/admin/categories', token=tokens['admin']).data)


@pytest.mark.admin
def test_delete_category_with_products_rejected(api, admin_token):
    result = api.delete('/api/admin/categories/%s' % DEFAULT_CATEGORY_ID, token=admin_token)
    assert result.code == 400 and '商品' in result.message, result


@pytest.mark.admin
def test_category_name_too_long_rejected(api, tokens, cleaner):
    result = api.post('/api/admin/categories', json_body={
        'name': 'X' * 65,
    }, token=tokens['admin'])
    if result.ok:
        cleaner.category(result.data['id'])
    assert result.code == 400 and '64' in result.message, result


@pytest.mark.admin
def test_category_not_found_returns_404(api, admin_token):
    result = api.put('/api/admin/categories/999999999',
                     json_body={'name': uid('APIC')}, token=admin_token)
    assert result.code == 404, result

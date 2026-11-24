# -*- coding: utf-8 -*-
"""购物车：鉴权、增删改查与数量合并。"""
import pytest

from projects.shopping.helpers import register_isolated_user
from projects.shopping.data import cases


@pytest.fixture
def isolated_token(api, cleaner):
    """每个购物车用例独立注册用户，购物车按 user_id 隔离，可安全并行。"""
    return register_isolated_user(api, cleaner, prefix='APICART')


@pytest.fixture
def first_product(api):
    products = api.get('/api/products').data
    assert products, '演示库至少应有一件在售商品'
    return products[0]


@pytest.mark.cart
@pytest.mark.parametrize('method,path,extra', cases('cart_requires_login', 'method', 'path', 'extra'))
def test_cart_requires_login(api, method, path, extra):
    result = getattr(api, method)(path, **extra)
    assert result.code == 401, (method, path, result)


@pytest.mark.cart
@pytest.mark.smoke
def test_add_product_to_cart(api, isolated_token, first_product):
    result = api.post('/api/cart/add', json_body={
        'productId': first_product['id'], 'quantity': 1,
    }, token=isolated_token)
    assert result.ok, result
    assert len(result.data) == 1, result.data
    assert result.data[0]['productId'] == first_product['id'], result.data
    assert result.data[0]['quantity'] == 1, result.data


@pytest.mark.cart
def test_adding_same_product_accumulates_quantity(api, isolated_token, first_product):
    body = {'productId': first_product['id'], 'quantity': 2}
    api.post('/api/cart/add', json_body=body, token=isolated_token)
    result = api.post('/api/cart/add', json_body=body, token=isolated_token)
    assert result.ok, result
    assert len(result.data) == 1, result.data
    assert result.data[0]['quantity'] == 4, result.data


@pytest.mark.cart
def test_update_quantity(api, isolated_token, first_product):
    added = api.post('/api/cart/add', json_body={
        'productId': first_product['id'], 'quantity': 1,
    }, token=isolated_token)
    item_id = added.data[0]['id']
    result = api.put('/api/cart/%s' % item_id, json_body={'quantity': 5}, token=isolated_token)
    assert result.ok, result
    assert result.data[0]['quantity'] == 5, result.data


@pytest.mark.cart
def test_update_quantity_to_zero_removes_item(api, isolated_token, first_product):
    added = api.post('/api/cart/add', json_body={
        'productId': first_product['id'], 'quantity': 1,
    }, token=isolated_token)
    item_id = added.data[0]['id']
    result = api.put('/api/cart/%s' % item_id, json_body={'quantity': 0}, token=isolated_token)
    assert result.ok and result.data == [], result


@pytest.mark.cart
def test_remove_item_by_id(api, isolated_token, first_product):
    added = api.post('/api/cart/add', json_body={
        'productId': first_product['id'], 'quantity': 1,
    }, token=isolated_token)
    item_id = added.data[0]['id']
    result = api.delete('/api/cart/%s' % item_id, token=isolated_token)
    assert result.ok and result.data == [], result


@pytest.mark.cart
def test_clear_cart(api, isolated_token, first_product):
    api.post('/api/cart/add', json_body={'productId': first_product['id']}, token=isolated_token)
    result = api.delete('/api/cart', token=isolated_token)
    assert result.ok and result.data == [], result
    assert api.get('/api/cart', token=isolated_token).data == []


@pytest.mark.cart
def test_add_nonexistent_product_is_rejected(api, isolated_token):
    result = api.post('/api/cart/add', json_body={
        'productId': 999999999, 'quantity': 1,
    }, token=isolated_token)
    assert result.code == 400 and '商品不存在' in result.message, result

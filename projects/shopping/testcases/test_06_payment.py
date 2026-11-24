# -*- coding: utf-8 -*-
"""虚拟支付：¥1000 上限、成功清车、失败留车、订单落库。

隔离策略：每个需要购物车的用例注册独立用户，购物车按 user_id 隔离，
用例间不再共享 demo 账号的购物车，可安全并行（xdist）执行。
"""
import pytest

from framework.assertions import assert_elapsed
from projects.shopping.helpers import assert_order_persisted, register_isolated_user
from projects.shopping.data import cases


@pytest.fixture
def isolated_token(api, cleaner):
    """专属用户 token；购物车、订单均归属该用户，与其他用例隔离。"""
    return register_isolated_user(api, cleaner, prefix='APIPAY')


@pytest.fixture
def filled_cart(api, isolated_token):
    products = api.get('/api/products').data
    assert products, '需要至少一件在售商品用于支付'
    product = products[0]
    added = api.post('/api/cart/add', json_body={
        'productId': product['id'], 'quantity': 1,
    }, token=isolated_token)
    assert added.ok, added
    return product


@pytest.mark.payment
def test_payment_requires_login(api):
    result = api.post('/api/pay', json_body={'amount': 100})
    assert result.code == 401, result


@pytest.mark.payment
def test_payment_records_require_login(api):
    assert api.get('/api/pay/records').code == 401


@pytest.mark.payment
def test_empty_cart_cannot_be_paid(api, isolated_token):
    result = api.post('/api/pay', json_body={'amount': 100}, token=isolated_token)
    assert result.code == 400 and '购物车为空' in result.message, result


@pytest.mark.smoke
@pytest.mark.payment
def test_payment_succeeds_at_exactly_1000(api, isolated_token, filled_cart, cleaner):
    result = api.post('/api/pay', json_body={
        'amount': 1000, 'payMethod': 'wechat',
    }, token=isolated_token)
    cleaner.order(result.data.get('orderNo') if result.data else None)
    assert result.ok, result
    data = result.data
    assert data['status'] == 'SUCCESS', data
    assert data['amount'] == 1000.0, data
    assert data['cartCleared'] is True, data
    assert data['payMethodLabel'] == '微信支付', data
    assert api.get('/api/cart', token=isolated_token).data == [], '成功后应清空购物车'
    assert_order_persisted(data['orderNo'], status='SUCCESS', amount=1000)


@pytest.mark.payment
def test_payment_fails_above_1000_and_keeps_cart(api, isolated_token, filled_cart, cleaner):
    result = api.post('/api/pay', json_body={'amount': 1001}, token=isolated_token)
    cleaner.order(result.data.get('orderNo') if result.data else None)
    assert result.ok, result
    data = result.data
    assert data['status'] == 'FAILED', data
    assert data['cartCleared'] is False, data
    assert '1000' in data['failReason'], data
    assert len(api.get('/api/cart', token=isolated_token).data) == 1, '失败后应保留购物车'
    assert_order_persisted(data['orderNo'], status='FAILED', amount=1001,
                           fail_reason=data['failReason'])


@pytest.mark.payment
def test_payment_succeeds_below_limit(api, isolated_token, filled_cart, cleaner):
    result = api.post('/api/pay', json_body={'amount': 999.99}, token=isolated_token)
    cleaner.order(result.data.get('orderNo') if result.data else None)
    assert result.ok and result.data['status'] == 'SUCCESS', result
    assert result.data['amount'] == 999.99, result.data
    assert_elapsed(result, 1200, '虚拟支付')
    assert_order_persisted(result.data['orderNo'], status='SUCCESS', amount=999.99)


@pytest.mark.payment
@pytest.mark.parametrize('amount', cases('payment_invalid_amounts', 'amount'))
def test_payment_rejects_invalid_amount(api, isolated_token, filled_cart, amount):
    result = api.post('/api/pay', json_body={'amount': amount}, token=isolated_token)
    assert result.code == 400, (amount, result)


@pytest.mark.payment
def test_unknown_pay_method_falls_back_to_wechat(api, isolated_token, filled_cart, cleaner):
    result = api.post('/api/pay', json_body={
        'amount': 100, 'payMethod': 'not-a-method',
    }, token=isolated_token)
    cleaner.order(result.data.get('orderNo') if result.data else None)
    assert result.ok and result.data['payMethod'] == 'wechat', result


@pytest.mark.payment
def test_paid_order_appears_in_records(api, isolated_token, filled_cart, cleaner):
    paid = api.post('/api/pay', json_body={'amount': 100}, token=isolated_token)
    cleaner.order(paid.data.get('orderNo') if paid.data else None)
    assert paid.ok, paid
    records = api.get('/api/pay/records', params={'limit': 50}, token=isolated_token)
    assert records.ok, records
    numbers = [row.get('orderNo') for row in records.data]
    assert paid.data['orderNo'] in numbers, numbers[:5]

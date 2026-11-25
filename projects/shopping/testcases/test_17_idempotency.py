# -*- coding: utf-8 -*-
"""幂等与并发：重复支付、重复删除、同一购物车并发支付。

购物车与订单都按 user_id 归属，每条用例注册独立用户，互不干扰，
因此可在 ``-n 4`` 下安全并行。
"""
import threading

import pytest

from projects.shopping.helpers import register_user

# 并发用例的规模：线程数 × 轮数。轮数是为了不让「刚好没撞上」把缺陷误判成已修复
CONCURRENT_THREADS = 3
CONCURRENT_ROUNDS = 3


@pytest.fixture
def buyer(api, cleaner):
    """独立用户：购物车与订单都归属它，用例结束统一清理。"""
    return register_user(api, cleaner, prefix='APIIDM')


@pytest.fixture
def cart_item(api, buyer):
    """给买家加一件在售商品，返回 (商品, 购物车项 id)。"""
    products = api.get('/api/products').data
    assert products, '需要至少一件在售商品'
    product = products[0]
    added = api.post('/api/cart/add', json_body={
        'productId': product['id'], 'quantity': 1,
    }, token=buyer['token'])
    assert added.ok, added.describe()
    return product, added.data[0]['id']


def _success_orders(api, token):
    records = api.get('/api/pay/records', params={'limit': 50}, token=token).data
    assert isinstance(records, list), records
    return [row for row in records if row.get('status') == 'SUCCESS']


@pytest.mark.idempotency
def test_second_payment_on_same_cart_is_rejected(api, buyer, cart_item, cleaner):
    """同一购物车连续支付两次：第二次必须被拒，且不产生第二张订单。"""
    token = buyer['token']

    first = api.post('/api/pay', json_body={'amount': 100}, token=token)
    assert first.ok, '首次支付应成功：%s' % first.describe()
    assert first.data['status'] == 'SUCCESS', first.data
    cleaner.order(first.data['orderNo'])

    second = api.post('/api/pay', json_body={'amount': 100}, token=token)
    assert second.code == 400, '购物车已清空，第二次支付应被拒：%s' % second.describe()
    assert '购物车为空' in second.message, second.message
    assert second.data in (None, {}), '被拒的支付不应返回订单数据：%r' % (second.data,)

    assert len(_success_orders(api, token)) == 1, '连续支付两次只应产生一张成功订单'


@pytest.mark.idempotency
def test_repeated_delete_of_cart_item_is_idempotent(api, buyer, cart_item):
    """DELETE 是幂等方法：删两次都不报错，购物车保持为空。"""
    token = buyer['token']
    _, item_id = cart_item

    first = api.delete('/api/cart/%s' % item_id, token=token)
    assert first.ok, first.describe()

    second = api.delete('/api/cart/%s' % item_id, token=token)
    assert second.status < 500, '重复删除同一项不应打成 5xx：%s' % second.describe()
    assert second.code in (200, 404), '重复删除应成功或明确不存在，实际 code=%s' % second.code

    assert api.get('/api/cart', token=token).data == [], '重复删除后购物车应保持为空'


@pytest.mark.xfail(
    strict=True,
    reason='[DEF-003] 已知缺陷（后端）：支付链路没有幂等键也没有行锁——PayController 先 '
           'cartMapper.findByUser 再 PayService.record，多个请求同时读到非空购物车就会'
           '各自插入订单。实测 3 线程并发支付同一购物车会生成 3 张 SUCCESS 订单（重复扣款）。'
           '预期：同一购物车并发支付只应成功一单，其余返回「购物车为空」。',
)
@pytest.mark.idempotency
def test_concurrent_payment_creates_single_order(api, buyer, cleaner, new_client):
    """同一购物车被并发支付时，只应产生一张订单（幂等键或行锁保证）。

    竞态窗口很窄（SELECT 购物车 → INSERT 订单之间），线程启动时间差几毫秒就错过。
    所以用栅栏让三个请求**同时**发出，并跑多轮——任何一轮出现重复订单即判定缺陷存在，
    避免「这轮刚好没撞上」把缺陷误判成已修复（strict xfail 会把误判变 XPASS 报错）。
    """
    token = buyer['token']
    product = api.get('/api/products').data
    assert product, '需要至少一件在售商品'
    product_id = product[0]['id']

    duplicated = []
    for round_no in range(CONCURRENT_ROUNDS):
        added = api.post('/api/cart/add', json_body={
            'productId': product_id, 'quantity': 1,
        }, token=token)
        assert added.ok, added.describe()

        barrier = threading.Barrier(CONCURRENT_THREADS)
        responses: list = []
        lock = threading.Lock()

        def pay():
            # 每个线程独立客户端：后端 Cookie 优先于 Authorization，共用 session 会串号
            client = new_client(token)
            barrier.wait(timeout=10)  # 等齐后同时发出，命中同一次竞态窗口
            result = client.post('/api/pay', json_body={'amount': 100}, token=token)
            with lock:
                responses.append(result)

        threads = [threading.Thread(target=pay) for _ in range(CONCURRENT_THREADS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(responses) == CONCURRENT_THREADS, '每个线程都应拿到响应'
        for result in responses:
            if isinstance(result.data, dict) and result.data.get('orderNo'):
                cleaner.order(result.data['orderNo'])

        succeeded = [r for r in responses if r.ok]
        if len(succeeded) != 1:
            duplicated.append('第 %d 轮成功 %d 单' % (round_no + 1, len(succeeded)))

    assert not duplicated, (
        '并发支付同一购物车只应成功一单，实际出现重复下单：%s' % '；'.join(duplicated)
    )

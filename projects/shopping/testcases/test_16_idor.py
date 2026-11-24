# -*- coding: utf-8 -*-
"""越权访问（IDOR）：用自己的合法 token 去操作别人名下的资源。

为什么单独成文件：权限矩阵只管「角色 × 接口」的准入，管不了「同一角色下
A 能不能动 B 的数据」。用户端唯一带客户端可控 id 的资源是购物车项
（`/api/cart/{id}`），其余接口（`/api/pay/records`、`/api/auth/me`）都只按
token 解析归属——所以这里的判定标准是：

1. **不泄漏**：攻击者看不到受害者的数据；
2. **不落地**：拿受害者的真实 id 去改 / 删，受害者的数据必须原样；
3. **不串号**：两个 token 各自 `/api/auth/me` 返回自己。

断言刻意不锁死 HTTP 状态码：后端把越权实现成「200 + 静默无效」也好、
「403/404 明确拒绝」也好，都算合格；只有「受害者的数据被改了」才算失败。
反过来，越权请求把服务打成 500 也要报错——那是未处理异常，不是拒绝。

会话隔离注意：本后端 Cookie 优先于 Authorization 头，而 requests.Session
会累积 Set-Cookie，所以两个身份必须各用一个独立客户端（new_client fixture），
否则请求头写着受害者、服务端却按最后一次注册的 Cookie 认成攻击者。
"""
import pytest

from framework.permissions import PermissionRow, check_permission
from projects.shopping.data import records
from projects.shopping.helpers import register_user

VICTIM = 'victim'
ATTACKER = 'attacker'
QUANTITY = 2


@pytest.fixture
def foreign_users(new_client, cleaner):
    """受害者 + 攻击者：各自独立客户端与 cookie jar；购物车按 user_id 隔离，可 -n 并行。"""
    users = {}
    for who, prefix in ((VICTIM, 'IDORV'), (ATTACKER, 'IDORA')):
        client = new_client()
        users[who] = register_user(client, cleaner, prefix=prefix)
        client.default_token = users[who]['token']  # 该客户端此后只代表这个人
        users[who]['client'] = client
    return users


@pytest.fixture
def victim_cart(foreign_users, cleaner):
    """受害者的购物车：1 件商品 × 2，返回项 id 供越权用例引用。"""
    victim = foreign_users[VICTIM]['client']
    products = victim.get('/api/products').data
    assert products, '演示库至少应有一件在售商品'
    product = products[0]
    added = victim.post('/api/cart/add', json_body={
        'productId': product['id'], 'quantity': QUANTITY,
    })
    cleaner.cart(foreign_users[VICTIM]['token'])
    assert added.ok and added.data, added
    return {'item_id': added.data[0]['id'], 'quantity': QUANTITY,
            'product_id': product['id']}


def cart_of(users, who):
    result = users[who]['client'].get('/api/cart')
    assert result.ok, result
    return result.data or []


def item_of(cart, item_id):
    for row in cart:
        if row.get('id') == item_id:
            return row
    return None


def assert_victim_untouched(users, cart, label):
    """越权后受害者的购物车项必须还在、数量未变。"""
    after = cart_of(users, VICTIM)
    row = item_of(after, cart['item_id'])
    assert row is not None, (
        '%s → 受害者的购物车项 %s 被越权删除；受害者购物车=%r'
        % (label, cart['item_id'], after))
    assert row['quantity'] == cart['quantity'], (
        '%s → 受害者购物车项数量被越权改动：期望 %s，实际 %s'
        % (label, cart['quantity'], row['quantity']))


@pytest.mark.idor
@pytest.mark.auth
def test_cart_list_does_not_expose_other_users_items(foreign_users, victim_cart):
    """攻击者的购物车列表里不应出现受害者的项（响应体不泄漏资源 id）。"""
    attacker_cart = cart_of(foreign_users, ATTACKER)
    assert attacker_cart == [], '新建用户的购物车应为空，实际 %r' % (attacker_cart,)
    assert item_of(attacker_cart, victim_cart['item_id']) is None
    assert_victim_untouched(foreign_users, victim_cart, '读取他人购物车列表')


@pytest.mark.idor
@pytest.mark.auth
@pytest.mark.parametrize('row', records('idor_matrix'),
                         ids=lambda row: row.get('label') or row.get('path'))
def test_foreign_cart_item_write_has_no_effect(foreign_users, victim_cart, row):
    """拿受害者的购物车项 id 做改数量 / 删除：请求可成功，但数据不许变。"""
    case = PermissionRow(row)
    role_tokens = {who: users['token'] for who, users in foreign_users.items()}
    # 用攻击者自己的客户端发起（其 cookie 也是攻击者），路径里的 id 指向受害者资源
    result = check_permission(
        foreign_users[ATTACKER]['client'], case, role_tokens,
        variables={'cart_item_id': victim_cart['item_id']},
    )
    assert result.status != 500, (
        '%s → 越权请求触发服务端异常（HTTP %s）：未处理就不是「拒绝」；%r'
        % (case.label, result.status, result))
    assert_victim_untouched(foreign_users, victim_cart, case.label)
    # 反向确认：攻击者自己的购物车也不该凭空多出这项（说明请求被错算到别人账上）
    assert item_of(cart_of(foreign_users, ATTACKER), victim_cart['item_id']) is None


@pytest.mark.idor
@pytest.mark.cart
def test_clear_cart_only_affects_self(foreign_users, victim_cart):
    """清空购物车是按 token 解析用户，不能波及他人。"""
    cleared = foreign_users[ATTACKER]['client'].delete('/api/cart')
    assert cleared.ok and cleared.data == [], cleared
    assert_victim_untouched(foreign_users, victim_cart, '清空自己的购物车')


@pytest.mark.idor
@pytest.mark.payment
def test_payment_settles_own_cart_only(foreign_users, victim_cart):
    """支付不接收购物车 id：攻击者无购物车时应被拒，而不是去结算受害者的车。"""
    result = foreign_users[ATTACKER]['client'].post('/api/pay', json_body={'amount': 100})
    assert result.code == 400 and '购物车为空' in result.message, (
        '攻击者购物车为空却支付成功，说明结算未按 token 归属：%r' % (result,))
    assert_victim_untouched(foreign_users, victim_cart, '用空购物车发起支付')


@pytest.mark.idor
@pytest.mark.payment
def test_payment_records_do_not_leak_across_users(foreign_users, victim_cart, cleaner):
    """受害者的订单号不能出现在攻击者的支付记录里。"""
    paid = foreign_users[VICTIM]['client'].post('/api/pay', json_body={'amount': 100})
    cleaner.order(paid.data.get('orderNo') if paid.data else None)
    assert paid.ok, paid
    order_no = paid.data['orderNo']

    def rows_of(who):
        result = foreign_users[who]['client'].get('/api/pay/records', params={'limit': 50})
        assert result.ok, result
        return result.data or []

    victim_rows = rows_of(VICTIM)
    attacker_rows = rows_of(ATTACKER)
    assert order_no in [r.get('orderNo') for r in victim_rows], '本人支付记录里应能看到自己的订单'
    assert order_no not in [r.get('orderNo') for r in attacker_rows], (
        '攻击者支付记录里出现了受害者订单 %s' % order_no)

    victim_id = foreign_users[VICTIM]['user']['id']
    attacker_id = foreign_users[ATTACKER]['user']['id']
    assert all(r.get('userId') == attacker_id for r in attacker_rows), (
        '攻击者支付记录里混入了他人订单：%r' % (attacker_rows[:3],))
    assert all(r.get('userId') == victim_id for r in victim_rows), (
        '受害者支付记录里混入了他人订单：%r' % (victim_rows[:3],))


@pytest.mark.idor
@pytest.mark.auth
def test_me_returns_own_identity(foreign_users):
    """两个 token 各自解析出自己，不出现会话串号。"""
    victim_me = foreign_users[VICTIM]['client'].get('/api/auth/me')
    attacker_me = foreign_users[ATTACKER]['client'].get('/api/auth/me')
    assert victim_me.ok and attacker_me.ok, (victim_me, attacker_me)
    assert victim_me.data['username'] == foreign_users[VICTIM]['username'], victim_me.data
    assert attacker_me.data['username'] == foreign_users[ATTACKER]['username'], attacker_me.data
    assert victim_me.data['id'] != attacker_me.data['id'], '两个账号拿到了同一个 user id'

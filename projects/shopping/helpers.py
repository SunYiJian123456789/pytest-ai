# -*- coding: utf-8 -*-
"""shopping 业务助手：构造商品、注册隔离用户、落库断言。"""
import uuid

from framework.extract import extract

from projects.shopping import dbclean
from projects.shopping.config import DEFAULT_CATEGORY_ID, DEFAULT_IMAGE


def uid(prefix: str = '') -> str:
    return prefix + uuid.uuid4().hex[:8].upper()


def register_isolated_user(api, cleaner, prefix='APIU'):
    """注册一个专属测试用户并返回其 token。

    购物车按 user_id 存储而非 token，因此共享 demo 账号时各用例的购物车会互相
    干扰。需要操作购物车的用例应各自注册独立用户，由 cleaner 统一删除。
    """
    username = uid(prefix)
    resp = api.post('/api/auth/register', json_body={
        'username': username, 'password': 'Test@123456',
    })
    assert resp.ok, '注册隔离用户失败: %r' % (resp,)
    cleaner.user(username)
    return extract(resp, 'data.token')


def product_payload(name: str, **overrides):
    """构造一份合法的商品表单；默认值与后端 validateProduct 对齐。"""
    payload = {
        'name': name,
        'subtitle': '接口自动化构造商品',
        'description': '由 shopping-api-automation 创建，用例结束后自动清理',
        'categoryId': DEFAULT_CATEGORY_ID,
        'price': 199,
        'originalPrice': 299,
        'flashPrice': 99,
        'image': DEFAULT_IMAGE,
        'stock': 30,
        'sales': 0,
        'tags': '接口测试,自动化',
        'badge': 'AUTO',
        'isHot': 0,
        'isFlash': 0,
        'status': 1,
    }
    payload.update(overrides)
    return payload


def create_product(api, tokens, cleaner, name: str, ctx=None, **overrides):
    """走真实审批链路创建商品：admin 提交 → reviewer 通过 → 入库。

    这是"上游响应值传给下游请求"的标准链路：用 ``extract`` 按路径提取，
    拿到 ID 立刻登记清理；传入 ctx 时同步记录到用例上下文与报告。
    """
    payload = product_payload(name, **overrides)
    submitted = api.post('/api/admin/products', json_body=payload, token=tokens['admin'])
    assert submitted.ok, '提交新增申请失败: %r' % (submitted,)
    approval_id = extract(submitted, 'data.id')
    cleaner.approval(approval_id)

    approved = api.post(
        '/api/admin/approvals/%s/approve' % approval_id,
        json_body={'remark': 'API 自动化审批通过'},
        token=tokens['reviewer'],
    )
    assert approved.ok, '审批通过失败: %r' % (approved,)
    product_id = extract(approved, 'data.id')
    cleaner.product(product_id)

    if ctx is not None:
        ctx.remember('approval_id', value=approval_id)
        ctx.remember('product_id', value=product_id)
        ctx.remember('product_name', value=name)
    return {'id': product_id, 'approval_id': approval_id, 'payload': payload}


def submit_application(api, token, name: str, cleaner=None, **overrides):
    """只提交申请、不审批，用于审批流本身或「未入库」断言。"""
    payload = product_payload(name, **overrides)
    result = api.post('/api/admin/products', json_body=payload, token=token)
    assert result.ok, '提交申请失败: %r' % (result,)
    if cleaner is not None:
        cleaner.approval(extract(result, 'data.id'))
    return result.data


def find_approval(api, token, name: str):
    result = api.get(
        '/api/admin/approvals',
        params={'keyword': name, 'page': 1, 'pageSize': 100},
        token=token,
    )
    assert result.ok, '查询申请单失败: %r' % (result,)
    for row in result.data.get('list') or []:
        if row.get('name') == name:
            return row
    return None


def front_products(api, keyword: str):
    result = api.get('/api/products', params={'keyword': keyword})
    assert result.ok, '前台商品查询失败: %r' % (result,)
    return result.data or []


def front_has(api, name: str) -> bool:
    return any(row.get('name') == name for row in front_products(api, name))


def first_category_id(api):
    result = api.get('/api/categories')
    assert result.ok and result.data, '分类接口不可用'
    return extract(result, 'data[0].id')


def assert_order_persisted(order_no: str, *, status: str, amount: float,
                           item_count: int = 1, fail_reason: str | None = None):
    """校验支付订单真实落库，而不只信接口回显。

    数据库不可用时的策略由 DB_STRICT 决定：CI（或显式配置）硬失败，
    本地开发默认跳过；查询报错则直接失败，绝不静默。
    """
    import pytest

    if not dbclean.available():
        if dbclean.STRICT:
            pytest.fail('数据库不可用（DB_STRICT=1）：落库断言无法执行，请检查 MySQL 配置')
        pytest.skip('数据库不可用，跳过落库校验')
    row = dbclean.query_order(order_no)
    assert row is not None, '订单 %s 未写入 payment_order 表' % order_no
    assert row['status'] == status, (row, status)
    assert row['amount'] == float(amount), (row['amount'], amount)
    assert row['failReason'] == fail_reason, (row['failReason'], fail_reason)
    items = dbclean.count_order_items(order_no)
    assert items == item_count, ('payment_order_item 快照数', items, item_count)
    return row

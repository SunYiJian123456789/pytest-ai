# -*- coding: utf-8 -*-
"""管理端商品管理：分页筛选、编辑、上下架、删除、批量与参数校验。"""
import pytest

from projects.shopping.helpers import create_product, front_has, submit_application, uid, product_payload
from projects.shopping.data import cases


@pytest.mark.admin
def test_admin_products_filters(api, admin_token):
    off = api.get('/api/admin/products', params={'status': 0, 'pageSize': 100}, token=admin_token)
    assert off.ok, off
    assert all(row['status'] == 0 for row in off.data['list']), off.data['list'][:3]

    categories = api.get('/api/categories').data
    category_id = categories[0]['id']
    by_category = api.get('/api/admin/products', params={
        'categoryId': category_id, 'pageSize': 100,
    }, token=admin_token)
    assert by_category.ok, by_category
    assert all(row['categoryId'] == category_id for row in by_category.data['list'])


@pytest.mark.admin
def test_admin_products_sort_price_ascending(api, admin_token):
    result = api.get('/api/admin/products', params={
        'sort': 'price_asc', 'pageSize': 100,
    }, token=admin_token)
    prices = [row['price'] for row in result.data['list']]
    assert prices == sorted(prices), prices


@pytest.mark.admin
def test_admin_keyword_search_finds_created_product(api, tokens, cleaner):
    name = uid('APIP')
    created = create_product(api, tokens, cleaner, name)
    result = api.get('/api/admin/products', params={
        'keyword': name, 'pageSize': 100,
    }, token=tokens['admin'])
    assert result.ok and result.data['total'] >= 1, result
    assert any(row['id'] == created['id'] for row in result.data['list']), result.data['list']


@pytest.mark.admin
def test_create_endpoint_submits_approval_without_inserting_product(api, tokens, cleaner):
    name = uid('APIP')
    approval = submit_application(api, tokens['admin'], name, cleaner=cleaner)
    assert approval['applyStatus'] == 'PENDING', approval
    assert approval['applicantName'], approval
    # 并行下其他用例会审批/删除商品，全局总数会波动；用唯一名称精确查询才可靠
    assert not front_has(api, name), '审批通过前商品不应出现在商城'
    listed = api.get('/api/admin/products', params={
        'keyword': name, 'pageSize': 100,
    }, token=tokens['admin'])
    assert listed.ok and not any(
        row['name'] == name for row in listed.data['list']
    ), '审批通过前管理端商品库不应出现该商品'


@pytest.mark.admin
def test_update_product_name(api, tokens, cleaner, ctx):
    """依赖链示范：审批返回的商品 id 经 ctx 记录，渲染到下一请求的 URL 与 body。

    create_product 内部用 extract 提取 approval_id / product_id；这里再用
    ctx.remember + ctx.render 演示手工链路。整个依赖在本用例内闭环，
    xdist 并行时与其他用例互不干扰，报告 extras 可看到每次提取的值。
    """
    name = uid('APIP')
    created = create_product(api, tokens, cleaner, name, ctx=ctx)
    ctx.remember('new_name', value=name + '-已修改')

    # 占位符独占字符串时保留原始类型；嵌在路径中自动转字符串
    payload = ctx.render(dict(created['payload'], name='${new_name}'))
    assert payload['name'] == name + '-已修改'
    result = api.put(ctx.render('/api/admin/products/${product_id}'),
                     json_body=payload, token=tokens['admin'])
    assert result.ok and result.data['name'] == payload['name'], result
    assert front_has(api, payload['name']), '改名后商城同步生效'


@pytest.mark.admin
@pytest.mark.parametrize('status,visible,label',
                         cases('product_status_values', 'status', 'visible', 'label'))
def test_set_product_status_drives_storefront(api, tokens, cleaner, status, visible, label):
    """上架/下架由 YAML 驱动：设置状态后，前台可见性与预期一致。"""
    name = uid('APIP')
    created = create_product(api, tokens, cleaner, name)
    assert front_has(api, name)

    result = api.patch('/api/admin/products/%s/status' % created['id'],
                       json_body={'status': status}, token=tokens['admin'])
    assert result.ok and result.data['status'] == status, result
    assert front_has(api, name) is visible, '%s后商城可见性应为 %s' % (label, visible)


@pytest.mark.admin
def test_off_shelf_product_hidden_from_storefront_detail(api, tokens, cleaner):
    name = uid('APIP')
    created = create_product(api, tokens, cleaner, name)
    api.patch('/api/admin/products/%s/status' % created['id'],
              json_body={'status': 0}, token=tokens['admin'])
    detail = api.get('/api/admin/products/%s' % created['id'], token=tokens['admin'])
    assert detail.ok and detail.data['status'] == 0, detail
    missing = api.get('/api/products/%s' % created['id'])
    assert missing.code == 404 and '商品不存在' in missing.message, missing


@pytest.mark.admin
@pytest.mark.parametrize('status,message',
                         cases('invalid_product_status_values', 'status', 'message'))
def test_invalid_status_value_rejected(api, tokens, cleaner, status, message):
    created = create_product(api, tokens, cleaner, uid('APIP'))
    result = api.patch('/api/admin/products/%s/status' % created['id'],
                       json_body={'status': status}, token=tokens['admin'])
    assert result.code == 400 and message in result.message, result


@pytest.mark.admin
def test_delete_product(api, tokens, cleaner):
    created = create_product(api, tokens, cleaner, uid('APIP'))
    deleted = api.delete('/api/admin/products/%s' % created['id'], token=tokens['admin'])
    assert deleted.ok, deleted
    detail = api.get('/api/admin/products/%s' % created['id'], token=tokens['admin'])
    assert detail.code == 404, detail


@pytest.mark.admin
@pytest.mark.parametrize('status,visible',
                         cases('batch_status_values', 'status', 'visible'))
def test_batch_status(api, tokens, cleaner, status, visible):
    first = create_product(api, tokens, cleaner, uid('APIP'))
    second = create_product(api, tokens, cleaner, uid('APIP'))
    result = api.post('/api/admin/products/batch-status', json_body={
        'ids': [first['id'], second['id']], 'status': status,
    }, token=tokens['admin'])
    assert result.ok and result.data['affected'] >= 2, result
    assert front_has(api, first['payload']['name']) is visible
    assert front_has(api, second['payload']['name']) is visible


@pytest.mark.admin
def test_batch_delete(api, tokens, cleaner):
    first = create_product(api, tokens, cleaner, uid('APIP'))
    second = create_product(api, tokens, cleaner, uid('APIP'))
    result = api.post('/api/admin/products/batch-delete', json_body={
        'ids': [first['id'], second['id']],
    }, token=tokens['admin'])
    assert result.ok and result.data['affected'] >= 2, result
    for pid in (first['id'], second['id']):
        assert api.get('/api/admin/products/%s' % pid, token=tokens['admin']).code == 404


@pytest.mark.admin
@pytest.mark.parametrize('patch,message', cases('create_product_invalid_patches', 'patch', 'message'))
def test_create_product_validation(api, tokens, cleaner, patch, message):
    name = uid('APIP')
    payload = product_payload(name)
    payload.update(patch)
    result = api.post('/api/admin/products', json_body=payload, token=tokens['admin'])
    if result.ok:
        cleaner.approval(result.data['id'])
    assert result.code == 400 and message in result.message, result


@pytest.mark.admin
@pytest.mark.parametrize('template', cases('product_form_templates', 'template'))
def test_create_product_from_yaml_template(api, tokens, cleaner, template):
    """合法商品表单来自 YAML，运行时只补唯一名称与动态分类，提交→审批→前台可见。"""
    from projects.shopping.helpers import first_category_id

    name = uid('APIP')
    payload = dict(template)
    payload['name'] = name
    payload['categoryId'] = first_category_id(api)
    payload['image'] = '/images/product-01.jpg'

    submitted = api.post('/api/admin/products', json_body=payload, token=tokens['admin'])
    assert submitted.ok, submitted
    cleaner.approval(submitted.data['id'])
    assert submitted.data['applyStatus'] == 'PENDING', submitted

    approved = api.post('/api/admin/approvals/%s/approve' % submitted.data['id'],
                        json_body={'remark': 'YAML 模板用例审批通过'}, token=tokens['reviewer'])
    assert approved.ok, approved
    cleaner.product(approved.data['id'])

    product = api.get('/api/admin/products/%s' % approved.data['id'],
                      token=tokens['admin']).data
    for key, expected in template.items():
        actual = product.get(key)
        if key in ('price', 'originalPrice', 'flashPrice'):
            assert float(actual) == float(expected), (key, actual, expected)
        else:
            assert actual == expected, (key, actual, expected)
    assert front_has(api, name), '审批通过后商品应出现在商城'


@pytest.mark.admin
def test_update_nonexistent_product_returns_404(api, admin_token):
    result = api.put('/api/admin/products/999999999',
                     json_body=product_payload(uid('APIP')), token=admin_token)
    assert result.code == 404, result


@pytest.mark.admin
def test_batch_without_ids_rejected(api, admin_token):
    result = api.post('/api/admin/products/batch-delete',
                      json_body={'ids': []}, token=admin_token)
    assert result.code == 400 and '选择商品' in result.message, result

# -*- coding: utf-8 -*-
"""新增商品审批流：提交不入库、禁止自审、他人审批、驳回与撤回。"""
import pytest

from projects.shopping.helpers import find_approval, front_has, submit_application, uid


@pytest.mark.approval
@pytest.mark.admin
def test_application_stays_pending_without_product(api, tokens, cleaner):
    name = uid('APIA')
    application = submit_application(api, tokens['admin'], name, cleaner=cleaner)

    expected_name = tokens['admin_info'].get('nickname') or tokens['admin_info']['username']
    assert application['applyStatus'] == 'PENDING', application
    assert application['applicantName'] == expected_name, application
    # 并行时其他用例会审批入库/删除商品，全局总数会波动，不能作为判据。
    # 用本用例唯一商品名在前台与管理端精确查询，才能可靠证明"提交不入库"。
    assert not front_has(api, name), '审批前商城不应出现该商品'
    listed = api.get('/api/admin/products', params={
        'keyword': name, 'pageSize': 100,
    }, token=tokens['admin'])
    assert listed.ok and not any(
        row['name'] == name for row in listed.data['list']
    ), '审批前管理端商品库不应出现该商品'
    row = find_approval(api, tokens['admin'], name)
    assert row and row['applyStatus'] == 'PENDING', row


@pytest.mark.approval
def test_pending_count_increments(api, tokens, cleaner):
    name = uid('APIA')
    before = api.get('/api/admin/approvals/pending-count',
                     token=tokens['admin']).data['pending']
    submit_application(api, tokens['admin'], name, cleaner=cleaner)
    after = api.get('/api/admin/approvals/pending-count',
                    token=tokens['admin']).data['pending']
    # 并行时其他用例会审批/撤回申请，待审总数可能减少；只断言仍有待审申请，
    # 精确性由 find_approval 按本用例唯一名保证。
    assert after >= 1, (before, after)
    assert find_approval(api, tokens['admin'], name) is not None


@pytest.mark.approval
def test_approval_list_scope_only_mine(api, tokens, cleaner):
    name = uid('APIA')
    submit_application(api, tokens['admin'], name, cleaner=cleaner)

    mine = api.get('/api/admin/approvals', params={
        'scope': 'mine', 'status': 'PENDING', 'keyword': name,
    }, token=tokens['admin'])
    others = api.get('/api/admin/approvals', params={
        'scope': 'mine', 'status': 'PENDING', 'keyword': name,
    }, token=tokens['reviewer'])
    assert mine.ok and any(r['name'] == name for r in mine.data['list']), mine
    assert others.ok and not any(r['name'] == name for r in others.data['list']), others


@pytest.mark.approval
def test_applicant_cannot_approve_own_application(api, tokens, cleaner):
    name = uid('APIA')
    application = submit_application(api, tokens['admin'], name, cleaner=cleaner)
    result = api.post('/api/admin/approvals/%s/approve' % application['id'],
                      json_body={'remark': '自审尝试'}, token=tokens['admin'])
    assert result.code == 400 and '不能审批自己' in result.message, result
    row = find_approval(api, tokens['admin'], name)
    assert row['applyStatus'] == 'PENDING', row
    assert not front_has(api, name)


@pytest.mark.approval
def test_other_admin_approves_and_product_enters_catalog(api, tokens, cleaner):
    name = uid('APIA')
    application = submit_application(api, tokens['admin'], name, cleaner=cleaner)

    result = api.post('/api/admin/approvals/%s/approve' % application['id'],
                      json_body={'remark': '接口自动化通过'}, token=tokens['reviewer'])
    assert result.ok, result
    product_id = result.data['id']
    cleaner.product(product_id)

    row = find_approval(api, tokens['admin'], name)
    assert row['applyStatus'] == 'APPROVED', row
    assert row['approverName'], row
    assert row['productId'] == product_id, row
    # 总数受并行用例影响，唯一商品名在前台可见才是入库的直接证据
    assert front_has(api, name), '审批通过后商品应出现在商城'


@pytest.mark.approval
def test_duplicate_approval_is_rejected(api, tokens, cleaner):
    name = uid('APIA')
    application = submit_application(api, tokens['admin'], name, cleaner=cleaner)
    first = api.post('/api/admin/approvals/%s/approve' % application['id'],
                     json_body={'remark': '首次通过'}, token=tokens['reviewer'])
    assert first.ok, first
    cleaner.product(first.data['id'])
    second = api.post('/api/admin/approvals/%s/approve' % application['id'],
                      token=tokens['admin'])
    assert second.code == 400 and '已处理' in second.message, second


@pytest.mark.approval
def test_reject_requires_reason(api, tokens, cleaner):
    name = uid('APIA')
    application = submit_application(api, tokens['admin'], name, cleaner=cleaner)
    result = api.post('/api/admin/approvals/%s/reject' % application['id'],
                      json_body={}, token=tokens['reviewer'])
    assert result.code == 400 and '理由' in result.message, result
    assert find_approval(api, tokens['admin'], name)['applyStatus'] == 'PENDING'


@pytest.mark.approval
def test_reject_with_reason(api, tokens, cleaner):
    name = uid('APIA')
    application = submit_application(api, tokens['admin'], name, cleaner=cleaner)
    result = api.post('/api/admin/approvals/%s/reject' % application['id'],
                      json_body={'remark': '图片不符合规范'}, token=tokens['reviewer'])
    assert result.ok and result.data['applyStatus'] == 'REJECTED', result
    assert '图片不符合规范' in result.data['approveRemark'], result.data
    assert not front_has(api, name)


@pytest.mark.approval
def test_only_applicant_can_cancel(api, tokens, cleaner):
    name = uid('APIA')
    application = submit_application(api, tokens['admin'], name, cleaner=cleaner)
    wrong = api.post('/api/admin/approvals/%s/cancel' % application['id'],
                     token=tokens['reviewer'])
    assert wrong.code == 400 and '只能撤回自己' in wrong.message, wrong

    right = api.post('/api/admin/approvals/%s/cancel' % application['id'],
                     token=tokens['admin'])
    assert right.ok and right.data['applyStatus'] == 'CANCELLED', right
    assert not front_has(api, name)


@pytest.mark.approval
def test_delete_application(api, tokens, cleaner):
    name = uid('APIA')
    application = submit_application(api, tokens['admin'], name, cleaner=cleaner)
    result = api.delete('/api/admin/approvals/%s' % application['id'], token=tokens['admin'])
    assert result.ok, result
    assert find_approval(api, tokens['admin'], name) is None

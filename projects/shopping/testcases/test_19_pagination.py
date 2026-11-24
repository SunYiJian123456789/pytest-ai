# -*- coding: utf-8 -*-
"""分页边界：page / pageSize 的归一化、越界回退与翻页一致性。

数据源用「唯一前缀的申请单」而不是全局商品列表——申请单是我们自己造的，
总数固定为 3，不受 ``-n 4`` 下其他用例增删商品影响，断言才能稳定。
"""
import pytest

from projects.shopping.helpers import submit_application, uid

BATCH = 3


@pytest.fixture
def batch(api, tokens, cleaner):
    """3 条同前缀申请单，返回 (keyword, names)，用例结束统一删除。"""
    prefix = uid('PAGE')
    names = ['%s%d' % (prefix, i) for i in range(BATCH)]
    for name in names:
        submit_application(api, tokens['admin'], name, cleaner=cleaner)
    return prefix, names


def approvals_page(api, tokens, keyword, **params):
    params.setdefault('keyword', keyword)
    params.setdefault('pageSize', 10)
    result = api.get('/api/admin/approvals', params=params, token=tokens['admin'])
    assert result.ok, result.describe()
    return result.data


def test_page_below_one_falls_back_to_first_page(api, tokens, batch):
    """page=0 / page=-1 属于非法页码，应归一化为第 1 页而不是报错或返回空。"""
    keyword, names = batch
    baseline = approvals_page(api, tokens, keyword, page=1, pageSize=2)

    for bad_page in (0, -1):
        data = approvals_page(api, tokens, keyword, page=bad_page, pageSize=2)
        assert data['page'] == 1, 'page=%s 应归一化为 1，实际 %s' % (bad_page, data['page'])
        assert [row['name'] for row in data['list']] == \
               [row['name'] for row in baseline['list']], 'page=%s 的内容应与第 1 页一致' % bad_page


def test_page_beyond_last_returns_last_page(api, tokens, batch):
    """page 超过总页数时应回退到末页，而不是返回空列表或 5xx。"""
    keyword, _ = batch
    data = approvals_page(api, tokens, keyword, page=999999, pageSize=1)

    assert data['total'] == BATCH, data
    assert data['totalPages'] == BATCH, data
    assert data['page'] == BATCH, '越界页码应回退到末页 %d，实际 %s' % (BATCH, data['page'])
    assert len(data['list']) == 1, '末页应仍有数据，实际 %d 条' % len(data['list'])


def test_page_size_is_clamped_to_one_and_hundred(api, tokens, batch):
    """pageSize <= 0 归一化为 1，> 100 截断为 100，且响应里的 pageSize 就是生效值。"""
    keyword, _ = batch

    for bad_size, expected in ((0, 1), (-1, 1), (1000, 100), (10000, 100)):
        data = approvals_page(api, tokens, keyword, page=1, pageSize=bad_size)
        assert data['pageSize'] == expected, \
            'pageSize=%s 应生效为 %d，实际 %s' % (bad_size, expected, data['pageSize'])
        assert len(data['list']) <= expected, '返回条数不得超过生效的 pageSize'


@pytest.mark.parametrize('param', ['page', 'pageSize'])
def test_non_numeric_paging_param_is_client_error(api, tokens, param):
    """非数字的分页参数属于客户端错误，应给 400 业务码而不是 5xx 或静默忽略。"""
    result = api.get('/api/admin/approvals', params={param: 'abc'}, token=tokens['admin'])
    assert result.status < 500, '非法分页参数不应打成 5xx：%s' % result.describe()
    assert result.code == 400, '%s=abc 应返回 code 400，实际 %s' % (param, result.code)


def test_walking_all_pages_covers_every_row_exactly_once(api, tokens, batch):
    """按 pageSize=1 逐页翻完：共 3 页、id 不重复、合计条数等于 total。"""
    keyword, names = batch
    first = approvals_page(api, tokens, keyword, page=1, pageSize=1)
    total_pages = first['totalPages']
    assert total_pages == BATCH, '3 条数据按每页 1 条应有 3 页，实际 %s' % total_pages

    seen = []
    for page in range(1, total_pages + 1):
        data = approvals_page(api, tokens, keyword, page=page, pageSize=1)
        assert data['page'] == page, '回显页码应与请求一致'
        seen.extend(row['id'] for row in data['list'])

    assert len(seen) == len(set(seen)) == BATCH, '翻页不应重复返回同一行，实际 %r' % (seen,)
    assert len(seen) == first['total'], '翻页合计应等于 total'
    assert sorted(row['name'] for row in approvals_page(
        api, tokens, keyword, page=1, pageSize=10)['list']) == sorted(names)


def test_out_of_range_page_on_empty_result_is_safe(api, tokens):
    """结果集为空时越界页码也要安全：page 归 1、列表为空、不报错。"""
    result = api.get('/api/admin/products', params={
        'keyword': uid('NOMATCH'), 'page': 999999, 'pageSize': 10,
    }, token=tokens['admin'])
    assert result.ok, result.describe()
    data = result.data
    assert data['total'] == 0, data
    assert data['page'] == 1, '空结果集时越界页码应归 1，实际 %s' % data['page']
    assert data['list'] == [], data['list']

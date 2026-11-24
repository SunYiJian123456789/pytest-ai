# -*- coding: utf-8 -*-
"""管理端概览统计与分页元信息。"""
import pytest


@pytest.mark.admin
def test_stats_shape_and_totals(api, admin_token):
    result = api.get('/api/admin/stats', token=admin_token)
    assert result.ok, result
    data = result.data
    for key in ('total', 'onSale', 'offSale', 'lowStock', 'outOfStock',
                'totalStock', 'totalSales', 'categoryCount', 'pendingApprovals'):
        assert key in data, key
    assert data['total'] > 0, data
    assert data['onSale'] + data['offSale'] == data['total'], data


@pytest.mark.admin
def test_stats_category_alignment(api, admin_token):
    stats = api.get('/api/admin/stats', token=admin_token).data
    categories = api.get('/api/categories').data
    assert stats['categoryCount'] == len(categories), (stats['categoryCount'], len(categories))
    assert len(stats['distribution']) == len(categories), stats['distribution']


@pytest.mark.admin
def test_stats_money_fields_are_numbers(api, admin_token):
    data = api.get('/api/admin/stats', token=admin_token).data
    assert isinstance(data['avgPrice'], (int, float)) and data['avgPrice'] > 0, data['avgPrice']
    assert isinstance(data['inventoryValue'], (int, float)), data['inventoryValue']


@pytest.mark.admin
def test_stats_pending_count_matches_approval_api(api, admin_token):
    stats = api.get('/api/admin/stats', token=admin_token).data
    pending = api.get('/api/admin/approvals/pending-count', token=admin_token).data
    assert stats['pendingApprovals'] == pending['pending'], (stats['pendingApprovals'], pending)


@pytest.mark.admin
def test_stats_recent_logs_have_operator(api, admin_token):
    data = api.get('/api/admin/stats', token=admin_token).data
    assert isinstance(data['recentLogs'], list), data['recentLogs']
    assert 'lowStockProducts' in data and 'recentProducts' in data


@pytest.mark.admin
def test_product_pagination_metadata(api, admin_token):
    result = api.get('/api/admin/products', params={
        'page': 1, 'pageSize': 5,
    }, token=admin_token)
    assert result.ok, result
    data = result.data
    assert data['page'] == 1 and data['pageSize'] == 5, data
    assert data['total'] >= len(data['list']), data
    assert data['totalPages'] >= 1, data
    assert len(data['list']) <= 5, data

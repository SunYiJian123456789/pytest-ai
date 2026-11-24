# -*- coding: utf-8 -*-
"""搜索联想与关键词处理边界。"""
import pytest


@pytest.mark.product
def test_suggest_empty_keyword_returns_empty(api):
    result = api.get('/api/search/suggest', params={'keyword': ''})
    assert result.ok and result.data == [], result


@pytest.mark.product
def test_suggest_honours_limit(api):
    result = api.get('/api/search/suggest', params={'keyword': '耳', 'limit': 3})
    assert result.ok, result
    assert len(result.data) <= 3, result.data
    assert all(row['status'] == 1 for row in result.data), result.data


@pytest.mark.product
def test_suggest_limit_is_clamped_to_ten(api):
    result = api.get('/api/search/suggest', params={'keyword': '耳', 'limit': 99})
    assert result.ok, result
    assert len(result.data) <= 10, len(result.data)


@pytest.mark.product
def test_suggest_sorted_by_sales_desc(api):
    result = api.get('/api/search/suggest', params={'keyword': '耳', 'limit': 10})
    sales = [row.get('sales') or 0 for row in result.data]
    assert sales == sorted(sales, reverse=True), sales


@pytest.mark.product
def test_keyword_whitespace_is_trimmed(api):
    raw = api.get('/api/products', params={'keyword': '耳'})
    padded = api.get('/api/products', params={'keyword': '  耳  '})
    assert raw.ok and padded.ok, (raw, padded)
    assert [r['id'] for r in raw.data] == [r['id'] for r in padded.data]


@pytest.mark.product
def test_suggest_only_returns_on_sale_products(api):
    result = api.get('/api/search/suggest', params={'keyword': '耳机'})
    assert result.ok, result
    assert all(row.get('status') == 1 for row in result.data), result.data

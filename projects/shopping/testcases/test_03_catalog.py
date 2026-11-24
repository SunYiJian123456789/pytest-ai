# -*- coding: utf-8 -*-
"""首页聚合、分类、轮播、促销与商品列表。"""
import pytest

from framework.assertions import assert_elapsed


@pytest.mark.smoke
@pytest.mark.product
def test_home_aggregates_all_sections(api, soft):
    result = api.get('/api/home')
    assert result.ok, result.describe()  # 前提：首页都取不到就不必逐段核

    sections = ('banners', 'categories', 'hotProducts', 'flashProducts', 'promotions')
    for key in sections:
        present = soft.fields_present(result.data, key, label='首页聚合')
        if present:
            soft.check(isinstance(result.data[key], list),
                       '首页聚合 %s 应为列表，实际 %s' % (key, type(result.data[key]).__name__))
    if soft.fields_present(result.data, 'banners'):
        soft.check(bool(result.data['banners']), '轮播图不应为空')
    if soft.fields_present(result.data, 'categories'):
        soft.check(bool(result.data['categories']), '分类不应为空')
    soft.assert_all()


@pytest.mark.product
def test_banners_and_promotions_are_lists(api):
    banners = api.get('/api/banners')
    promotions = api.get('/api/promotions')
    assert banners.ok and isinstance(banners.data, list), banners
    assert promotions.ok and isinstance(promotions.data, list), promotions


@pytest.mark.product
def test_categories_have_id_and_name(api):
    result = api.get('/api/categories')
    assert result.ok and result.data, result
    for row in result.data:
        assert isinstance(row.get('id'), int), row
        assert row.get('name'), row


@pytest.mark.smoke
@pytest.mark.product
def test_products_list_only_contains_on_sale(api):
    result = api.get('/api/products')
    assert result.ok and result.data, result
    assert all(row.get('status') == 1 for row in result.data), result.data[:3]
    assert_elapsed(result, 800, '商品列表')


@pytest.mark.product
def test_products_filter_by_category(api):
    categories = api.get('/api/categories').data
    category_id = categories[0]['id']
    result = api.get('/api/products', params={'categoryId': category_id})
    assert result.ok, result
    assert all(row.get('categoryId') == category_id for row in result.data), result.data[:3]


@pytest.mark.product
def test_products_sort_price_ascending(api):
    result = api.get('/api/products', params={'sort': 'price_asc'})
    prices = [row['price'] for row in result.data]
    assert prices == sorted(prices), prices


@pytest.mark.product
def test_products_sort_price_descending(api):
    result = api.get('/api/products', params={'sort': 'price_desc'})
    prices = [row['price'] for row in result.data]
    assert prices == sorted(prices, reverse=True), prices


@pytest.mark.product
def test_product_detail_success_and_missing(api):
    first = api.get('/api/products').data[0]
    detail = api.get('/api/products/%s' % first['id'])
    assert detail.ok and detail.data['id'] == first['id'], detail
    missing = api.get('/api/products/999999999')
    assert missing.code == 404 and '商品不存在' in missing.message, missing


@pytest.mark.product
def test_like_wildcards_are_escaped(api):
    result = api.get('/api/products', params={'keyword': '%'})
    assert result.ok, result
    assert not result.data, 'LIKE 通配符必须被转义，%% 不应命中全表' % ()


@pytest.mark.product
def test_search_matches_any_supported_field(api):
    first = api.get('/api/products').data[0]
    keyword = first['name'][:2]
    result = api.get('/api/products', params={'keyword': keyword})
    assert result.ok, result
    assert any(row['id'] == first['id'] for row in result.data), (keyword, result.data[:3])

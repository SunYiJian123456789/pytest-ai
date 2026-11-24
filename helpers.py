# -*- coding: utf-8 -*-
"""兼容层：业务助手已迁移到 projects/shopping/helpers.py。"""
from projects.shopping.helpers import (
    assert_order_persisted, create_product, find_approval, first_category_id,
    front_has, front_products, product_payload, register_isolated_user,
    submit_application, uid,
)

__all__ = [
    'assert_order_persisted', 'create_product', 'find_approval',
    'first_category_id', 'front_has', 'front_products', 'product_payload',
    'register_isolated_user', 'submit_application', 'uid',
]

# -*- coding: utf-8 -*-
"""兼容层：业务 SQL 已迁移到 projects/shopping/dbclean.py。"""
from projects.shopping.dbclean import (
    available, count_order_items, delete_payment_orders, delete_users,
    execute, query_order, query_user,
)

__all__ = [
    'available', 'count_order_items', 'delete_payment_orders',
    'delete_users', 'execute', 'query_order', 'query_user',
]

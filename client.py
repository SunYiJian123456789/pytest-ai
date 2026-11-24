# -*- coding: utf-8 -*-
"""兼容层：REST 客户端已迁移到 framework/client.py。

旧代码 ``from client import ApiClient`` 继续可用；新代码请 ``from framework import ApiClient``。
"""
from framework.client import (
    SLOW_MS, ApiClient, ApiResult, Envelope, mask_token, shorten,
)

__all__ = ['SLOW_MS', 'ApiClient', 'ApiResult', 'Envelope', 'mask_token', 'shorten']

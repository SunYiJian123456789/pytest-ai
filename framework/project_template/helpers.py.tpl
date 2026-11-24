# -*- coding: utf-8 -*-
"""{{PROJECT}} 的数据构造助手（按需扩展）。"""
import uuid


def uid(prefix: str = '') -> str:
    return prefix + uuid.uuid4().hex[:8].upper()

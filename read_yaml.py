# -*- coding: utf-8 -*-
"""兼容层：YAML 数据加载器已迁移到 framework/data.py。

shopping 用例请使用 ``from projects.shopping.data import cases``（自动绑定数据文件路径）。
"""
from framework.data import DATA_FILE, ROOT, cases, load

__all__ = ['DATA_FILE', 'ROOT', 'cases', 'load']

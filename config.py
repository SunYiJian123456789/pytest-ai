# -*- coding: utf-8 -*-
"""兼容层：配置已迁移到 projects/shopping/config.py。

旧代码 ``from config import BASE_URL`` 继续可用；新代码请直接引用业务项目或 framework。
"""
from framework.config import ROOT  # noqa: F401 - 兼容层 re-export
from projects.shopping.config import (  # noqa: F401 - 兼容层 re-export
    ADMIN_ACCOUNTS, BASE_URL, CFG, DATA_PREFIX, DATA_SOURCE, DEFAULT_CATEGORY_ID,
    DEFAULT_IMAGE, MODULE_LABELS, MYSQL_DATABASE, MYSQL_HOST,
    MYSQL_PASSWORD, MYSQL_PORT, MYSQL_USER, PROJECT_LABEL, REPORT_NOTES,
    REPORT_PATH, STORE_PASSWORD, STORE_USERNAME, TIMEOUT, UPLOAD_DIR,
)

__all__ = [name for name in dir() if not name.startswith('_')]

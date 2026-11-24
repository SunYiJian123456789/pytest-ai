# -*- coding: utf-8 -*-
"""根 conftest：只挂载 framework 的通用钩子。

业务 fixtures（api / tokens / cleaner 等）由 ``projects/<API_PROJECT>/conftest.py``
提供；pytest 按测试路径自动加载对应项目的 conftest，无需在此写业务代码。
"""
from framework.hooks import (  # noqa: F401 - 这些函数由 pytest 作为 hook 调用
    REPORT_ENHANCE_ERROR, REPORT_OPTIONS, configure_report,
    pytest_configure, pytest_html_report_title, pytest_terminal_summary,
    pytest_unconfigure,
)

# -*- coding: utf-8 -*-
"""根 conftest：只挂载 framework 的通用钩子。

业务 fixtures（api / tokens / cleaner 等）由 ``projects/<API_PROJECT>/conftest.py``
提供；pytest 按测试路径自动加载对应项目的 conftest，无需在此写业务代码。
"""
import pytest

from framework.assertions import SoftAssert
from framework.hooks import (  # noqa: F401 - 这些函数由 pytest 作为 hook 调用
    REPORT_ENHANCE_ERROR, REPORT_OPTIONS, configure_report,
    pytest_configure, pytest_html_report_title, pytest_terminal_summary,
    pytest_unconfigure,
)


@pytest.fixture
def soft():
    """软断言收集器（通用，所有项目可用）：末尾调用 ``soft.assert_all()`` 统一抛出。"""
    return SoftAssert()

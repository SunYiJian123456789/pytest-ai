# -*- coding: utf-8 -*-
"""{{PROJECT}} 的 fixtures：登录态、客户端、注册式清理器。"""
from pathlib import Path

import pytest

from framework import coverage, hooks
from framework.cleanup import CleanupRegistry
from framework.client import ApiClient, Envelope
from framework.extract import CaseContext
from projects.{{PROJECT}}.config import (
    AUTH, AUTH_PASSWORD, AUTH_USERNAME, BASE_URL, DATA_SOURCE,
    MODULE_LABELS, PROJECT_LABEL, REPORT_NOTES, SUCCESS_CODE, TIMEOUT,
)
from projects.{{PROJECT}}.helpers import uid


def pytest_configure(config):
    hooks.configure_report(
        title='{{PROJECT_UPPER}} 接口自动化测试报告',
        project_label=PROJECT_LABEL,
        module_labels=MODULE_LABELS,
        base_url=BASE_URL,
        data_source=DATA_SOURCE,
        notes=REPORT_NOTES,
        success_code=SUCCESS_CODE,
    )
    # 接口覆盖率基准：data/api_inventory.yaml 登记被测接口（method + path）
    coverage.configure(Path(__file__).parent / 'data' / 'api_inventory.yaml')


def _client() -> ApiClient:
    return ApiClient(BASE_URL, TIMEOUT, auth=AUTH,
                     envelope=Envelope(success_code=SUCCESS_CODE))


@pytest.fixture(scope='session')
def auth_state():
    """登录一次：header 模式拿 token，cookie 模式由 Session 自动保存 Cookie。"""
    client = _client()
    token = client.login(AUTH_USERNAME, AUTH_PASSWORD)
    return {'token': token, 'cookies': dict(client.session.cookies)}


@pytest.fixture(scope='session')
def token(auth_state):
    return auth_state['token']


@pytest.fixture(scope='session')
def tokens(token):
    """兼容习惯写法：tokens['user'] / tokens['admin']。"""
    return {'user': token, 'admin': token}


@pytest.fixture
def api(extras, auth_state):
    client = _client()
    if auth_state['cookies']:
        client.session.cookies.update(auth_state['cookies'])
    client.default_token = auth_state['token']
    client.extras = extras  # pytest-html 4.x 的 extras fixture
    return client


@pytest.fixture
def cleaner(api):
    """业务清理动作按需注册，框架统一执行并写入报告汇总。"""
    instance = CleanupRegistry()
    yield instance
    instance.run()


@pytest.fixture
def ctx(extras):
    """用例内依赖链：remember 记录上游响应值，render 渲染下游请求参数。"""
    return CaseContext(extras=extras)


@pytest.fixture
def scenario_variables(token):
    """场景编排用例的初始变量：${token} 登录态、${uid} 场景级唯一串。

    function 作用域保证每条场景独立（${uid} 不重复、xdist 并行不串值）；
    需要更多变量（角色 token、种子数据 ID 等）在这里按需补充。
    """
    return {'token': token, 'uid': uid('SCEN')}


@pytest.fixture(scope='session')
def role_tokens(tokens):
    """权限矩阵的角色→token 映射；按被测系统的角色增减键即可。"""
    return {
        'anonymous': None,
        'user': tokens.get('user'),
        'admin': tokens.get('admin'),
    }

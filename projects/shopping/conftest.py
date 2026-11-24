# -*- coding: utf-8 -*-
"""shopping 项目的 pytest fixtures（业务层）。

通用钩子在 framework.hooks；这里只负责：登录态、API 客户端、业务清理动作，
以及把项目信息注入报告。换系统时新增一个 projects/<name>/conftest.py 即可。
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from framework import hooks
from framework.cleanup import CleanupRegistry, remove_uploaded_files
from framework.client import ApiClient
from framework.extract import CaseContext, extract
from projects.shopping import dbclean
from projects.shopping.config import (
    ADMIN_ACCOUNTS, ADMIN_AUTH, BASE_URL, DATA_SOURCE, MODULE_LABELS, MYSQL_DATABASE,
    PROJECT_LABEL, REPORT_NOTES, STORE_PASSWORD, STORE_USERNAME, TIMEOUT, UPLOAD_DIR,
    USER_AUTH,
)


def pytest_configure(config):
    """把 shopping 项目信息注入通用报告钩子。"""
    hooks.configure_report(
        title='Shopping 接口自动化测试报告（pytest + requests）',
        project_label=PROJECT_LABEL,
        module_labels=MODULE_LABELS,
        base_url=BASE_URL,
        database=MYSQL_DATABASE,
        data_source=DATA_SOURCE,
        notes=[REPORT_NOTES],
        success_code=200,
    )


class Cleaner(CleanupRegistry):
    """登记用例产生的数据，teardown 时按安全顺序删除；结果统一进报告汇总。"""

    def __init__(self, api: ApiClient, tokens: dict):
        super().__init__()
        self.api = api
        self.tokens = tokens
        self._products = []
        self._approvals = []
        self._categories = []
        self._snapshots = []
        self._clear_cart = False
        self._cart_token = None
        self._orders = []
        self._users = []
        self._uploads = []

    def product(self, product_id):
        if product_id is not None:
            self._products.append(product_id)
        return self

    def approval(self, approval_id):
        if approval_id is not None:
            self._approvals.append(approval_id)
        return self

    def category(self, category_id):
        if category_id is not None:
            self._categories.append(category_id)
        return self

    def restore_product(self, product_id, payload):
        self._snapshots.append((product_id, payload))
        return self

    def cart(self, token=None):
        self._clear_cart = True
        self._cart_token = token
        return self

    def order(self, order_no):
        if order_no:
            self._orders.append(order_no)
        return self

    def user(self, username):
        if username:
            self._users.append(username)
        return self

    def upload(self, image_path):
        if image_path:
            self._uploads.append(image_path)
        return self

    @staticmethod
    def _ignore_missing(result):
        """目标已被用例删除时，清理视为成功（幂等），避免汇总里出现假失败。"""
        if result.code == 404 or '不存在' in (result.message or ''):
            return SimpleNamespace(ok=True, skipped=False, error='', message='')
        return result

    def run(self):
        admin = self.tokens['admin']
        for pid, payload in self._snapshots:
            self.register('restore product %s' % pid,
                          lambda pid=pid, payload=payload: self.api.put(
                              '/api/admin/products/%s' % pid,
                              json_body=payload, token=admin))
        for aid in reversed(self._approvals):
            self.register('delete approval %s' % aid,
                          lambda aid=aid: self._ignore_missing(self.api.delete(
                              '/api/admin/approvals/%s' % aid, token=admin)))
        for pid in reversed(self._products):
            self.register('delete product %s' % pid,
                          lambda pid=pid: self._ignore_missing(self.api.delete(
                              '/api/admin/products/%s' % pid, token=admin)))
        for cid in reversed(self._categories):
            self.register('delete category %s' % cid,
                          lambda cid=cid: self._ignore_missing(self.api.delete(
                              '/api/admin/categories/%s' % cid, token=admin)))
        if self._clear_cart:
            token = self._cart_token or self.tokens['user']
            self.register('clear cart',
                          lambda: self.api.delete('/api/cart', token=token))
        if self._orders:
            self.register('delete payment orders',
                          lambda: dbclean.delete_payment_orders(self._orders))
        if self._users:
            self.register('delete users',
                          lambda: dbclean.delete_users(self._users))
        for image_path in self._uploads:
            name = Path(image_path).name
            self.register('delete upload %s' % name,
                          lambda image_path=image_path: remove_uploaded_files(
                              UPLOAD_DIR, [image_path]))
        return super().run()


@pytest.fixture(scope='session')
def tokens():
    """三种角色各登录一次，跨用例复用；登录走 AuthSpec，换系统只改配置。

    用户端与管理端用各自的 AuthSpec（登录路径/字段/token 位置可配），
    UserInfo 从 last_login 响应按路径提取，避免散落的 resp.data['token']。
    """
    result = {}

    user_client = ApiClient(BASE_URL, TIMEOUT, auth=USER_AUTH)
    user_client.login(STORE_USERNAME, STORE_PASSWORD)
    result['user'] = user_client.default_token
    result['user_info'] = extract(user_client.last_login, 'data.user')

    for role, (username, password) in ADMIN_ACCOUNTS.items():
        client = ApiClient(BASE_URL, TIMEOUT, auth=ADMIN_AUTH)
        client.login(username, password)
        result[role] = client.default_token
        result[role + '_info'] = extract(client.last_login, 'data.admin')
    return result


@pytest.fixture
def api(extras):
    client = ApiClient(BASE_URL, TIMEOUT, auth=USER_AUTH)
    # pytest-html 4.x 通过 extras fixture 收集报告明细
    client.extras = extras
    return client


@pytest.fixture
def cleaner(api, tokens):
    instance = Cleaner(api, tokens)
    yield instance
    instance.run()


@pytest.fixture
def ctx(extras):
    """用例内依赖链上下文：提取上游响应值，渲染下游请求参数。

    function 作用域保证每个用例独立，不会因 xdist 并行而串值；
    每次 remember 都会写入报告 extras，链路可追溯。
    """
    return CaseContext(extras=extras)


@pytest.fixture(scope='session')
def role_tokens(tokens):
    """权限矩阵的角色→token 映射：内核不认识业务角色，由这里配置。"""
    return {
        'anonymous': None,
        'user': tokens['user'],
        'admin': tokens['admin'],
        'reviewer': tokens['reviewer'],
        'operator': tokens['operator'],
    }


@pytest.fixture
def user_token(tokens):
    return tokens['user']


@pytest.fixture
def admin_token(tokens):
    return tokens['admin']


@pytest.fixture
def reviewer_token(tokens):
    return tokens['reviewer']

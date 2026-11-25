# -*- coding: utf-8 -*-
"""shopping 项目的 pytest fixtures（业务层）。

通用钩子在 framework.hooks；这里只负责：登录态、API 客户端、业务清理动作，
以及把项目信息注入报告。换系统时新增一个 projects/<name>/conftest.py 即可。
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from framework import coverage, defects, hooks
from framework.cleanup import (
    CleanupRegistry, register_sweep, remove_uploaded_files,
)
from framework.client import ApiClient
from framework.config import missing_required
from framework.extract import CaseContext, extract
from framework.preflight import Check, Preflight, Skipped
from framework.state import state
from projects.shopping import dbclean
from projects.shopping.config import (
    ADMIN_ACCOUNTS, ADMIN_AUTH, BASE_URL, DATA_SOURCE, DB_STRICT, MODULE_LABELS,
    MYSQL_DATABASE, MYSQL_HOST, MYSQL_PORT, MYSQL_USER, PREFLIGHT_TIMEOUT,
    PROJECT_LABEL, REPORT_NOTES, STORE_PASSWORD, STORE_USERNAME, TIMEOUT, UPLOAD_DIR,
    USER_AUTH,
)


def pytest_configure(config):
    """把 shopping 项目信息注入通用报告钩子，并登记接口清单（覆盖率基准）。"""
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
    coverage.configure(Path(__file__).parent / 'data' / 'api_inventory.yaml')
    defects.configure(Path(__file__).parent / 'data' / 'known_defects.yaml',
                      project='shopping')
    _register_sweeps()


def _register_sweeps():
    """兜底清理：收尾时按 API 前缀扫描残留，补上用例漏登记/中途异常的数据。

    只在主进程执行（见 framework.hooks），且内核对标识再做一次前缀校验；
    demo/admin 等真实账号不以 API 开头，不会被扫到。DB 不可用时扫描抛错，
    由内核记一条 FAIL，不影响测试结论但会暴露在报告里。
    """
    targets = (
        ('users', 'API 测试用户'),
        ('products', 'API 测试商品'),
        ('categories', 'API 测试分类'),
        ('approvals', 'API 审批单'),
    )
    for target, label in targets:
        register_sweep(
            label,
            discover=lambda target=target: dbclean.scan_test_keys(target),
            clean=lambda key, target=target: dbclean.delete_test_keys(target, [key]),
            fallback='按前缀扫描的残留删除失败',
            prefixes=('API',),
        )


# ---------- 启动体检 ----------

# 体检时登录一次，tokens fixture 直接复用，避免「体检登录 → 用例再登录」重复一轮。
# 会话态真实存放于 SessionState 的私有槽位；别名指向同一 dict，业务代码不感知。
_TOKENS: dict = state.namespace('shopping.tokens')


def _fill_tokens(state: dict) -> None:
    """用户端 + 管理端各角色登录一次，写入 state（键与 tokens fixture 一致）。

    全部成功才写入：避免「用户登录成功、admin 失败」时留下半套 token，
    后续用例以 KeyError 的形式报错，掩盖真正原因。
    失败集中成一条消息——密码改一个就跑一次，成本太高。
    """
    fresh: dict = {}
    failures = []

    user_client = ApiClient(BASE_URL, TIMEOUT, auth=USER_AUTH)
    try:
        user_client.login(STORE_USERNAME, STORE_PASSWORD)
    except AssertionError as exc:
        failures.append('商城用户 %s — %s' % (STORE_USERNAME, exc))
    else:
        fresh['user'] = user_client.default_token
        fresh['user_info'] = extract(user_client.last_login, 'data.user')

    for role, (username, password) in ADMIN_ACCOUNTS.items():
        client = ApiClient(BASE_URL, TIMEOUT, auth=ADMIN_AUTH)
        try:
            client.login(username, password)
        except AssertionError as exc:
            failures.append('管理端 %s（%s）— %s' % (role, username, exc))
            continue
        fresh[role] = client.default_token
        fresh[role + '_info'] = extract(client.last_login, 'data.admin')

    if failures:
        raise AssertionError('；'.join(failures))
    state.update(fresh)


def _reason(result) -> str:
    """把 requests 的长异常压成一句话：体检消息要能一眼看完。"""
    text = str(result.message or '')
    if '10061' in text or 'Connection refused' in text or '积极拒绝' in text:
        return '连接被拒绝（服务未启动或端口不对）'
    if '10060' in text or 'timed out' in text or 'timeout' in text.lower():
        return '连接超时'
    if 'getaddrinfo' in text or 'Name or service not known' in text:
        return '域名解析失败'
    return text[:120] or '无响应'


def _preflight_checks() -> list:
    """启动体检项：服务可达 → 服务自检 → 数据库可用 → 登录可用。

    全部只读、快速失败；某项挂掉不影响后面的检查继续跑完（一轮把问题说全）。
    前置条件不满足时抛 Skipped：把「没测」与「测了不通过」分开，别把未执行显示成失败。
    """
    probe: dict = {}
    # 体检探活不重试、不注入 trace：这是诊断请求，重试只会把「服务没起」的等待翻倍
    probe_client = ApiClient(BASE_URL, PREFLIGHT_TIMEOUT,
                             retry_enabled=False, trace_enabled=False)

    def health():
        """一次 /api/health 探活结果，多项检查共用（后端没起时不重复等超时）。"""
        if 'result' not in probe:
            probe['result'] = probe_client.get('/api/health')
        return probe['result']

    def service_up():
        result = health()
        return result.status == 200 and result.ok

    def service_reachable():
        result = health()
        if result.status == 0:
            raise AssertionError('无法连接 %s：%s' % (BASE_URL, _reason(result)))
        if result.status != 200 or not result.ok:
            raise AssertionError('GET /api/health → HTTP %s / code %s：%s'
                                 % (result.status, result.code, _reason(result)))
        return 'HTTP 200 · code 200 · %d ms' % result.elapsed_ms

    def service_healthy():
        if not service_up():
            raise Skipped('后端不可达（见上一项），未执行健康自检')
        data = health().data
        status = data.get('status') if isinstance(data, dict) else None
        if status != 'UP':
            raise AssertionError('健康自检 status=%r，期望 UP' % (status,))
        return 'status=UP · %s' % (data.get('database') or '-')

    def database_ready():
        if not dbclean.available():
            raise AssertionError('PyMySQL 未安装或未配置数据库名')
        result = dbclean.execute('SELECT 1 AS ok')
        if result.skipped:
            raise AssertionError('数据库驱动不可用')
        if not result.ok:
            raise AssertionError(result.error)
        return '%s@%s:%s/%s' % (MYSQL_USER, MYSQL_HOST, MYSQL_PORT, MYSQL_DATABASE)

    def login_ready():
        if not service_up():
            raise Skipped('后端不可达（见上一项），未执行登录校验')
        _fill_tokens(_TOKENS)
        return '用户 1 个 + 管理端 %d 个角色登录成功' % len(ADMIN_ACCOUNTS)

    def config_complete():
        """必填配置齐备：CFG.require 只登记不抛错，缺项在这里一次性说清。"""
        missing = missing_required()
        if missing:
            raise AssertionError('缺少必填配置：%s（请在 .env 或进程环境变量中补充）'
                                 % '、'.join('%s[%s]' % (key, env_name)
                                            for key, env_name in sorted(missing.items())))
        return '必填键齐备'

    return [
        Check('必填配置', config_complete,
              hint='照 .env.example 补齐缺项；CI 从 .env.example 生成 .env 即为此项服务'),
        Check('后端可达', service_reachable,
              hint='先启动被测服务（D:/shopping/start-backend.bat）；'
                   '并确认 .env 的 SHOPPING_API_BASE_URL=%s' % BASE_URL),
        Check('服务自检', service_healthy, required=False,
              hint='/api/health 的 status 不是 UP：检查数据库连接与图片存储目录'),
        Check('数据库可用', database_ready, required=DB_STRICT,
              hint='检查 .env 的 SHOPPING_MYSQL_*；本地无库可忽略（落库断言自动跳过），'
                   'CI 需 DB_STRICT=1 且库可用'),
        Check('登录可用', login_ready,
              hint='核对 .env 的 SHOPPING_STORE_USER/PASSWORD '
                   '与 SHOPPING_ADMIN_* / REVIEWER_* / OPERATOR_*'),
    ]


def pytest_sessionstart(session):
    """收集用例前做一次体检：环境没备好就一条消息中止。

    不做体检时，后端没启动会让 140 条用例各报一次 ConnectionRefused，
    看报告的人要翻完所有红叉才发现「服务没起」。现在直接一条 ERROR 说清。

    - 失败：抛 pytest.UsageError → 终端一行 ERROR + 退出码 4，用例零执行；
    - ``--collect-only`` 不联网（收集阶段不需要服务）；
    - ``API_PREFLIGHT_ENABLED=0`` 关闭；``API_PREFLIGHT_STRICT=0`` 只告警不中止。
    """
    if session.config.getoption('collectonly', False):
        return
    Preflight(_preflight_checks()).run_or_exit()


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

    正常由启动体检（pytest_sessionstart）填好缓存，这里直接复用；
    体检被关闭（API_PREFLIGHT_ENABLED=0）时兜底登录，行为与改造前一致。
    """
    if not _TOKENS.get('user') or not _TOKENS.get('admin'):
        _fill_tokens(_TOKENS)
    return _TOKENS


@pytest.fixture
def api(extras):
    client = ApiClient(BASE_URL, TIMEOUT, auth=USER_AUTH)
    # pytest-html 4.x 通过 extras fixture 收集报告明细
    client.extras = extras
    return client


@pytest.fixture
def new_client():
    """按需创建独立 ApiClient（各自独立 cookie jar），用于多身份场景。

    共享的 api fixture 只有一个 requests.Session，登录 / 注册返回的 Set-Cookie
    会累积；本后端 Cookie 优先于 Authorization 头，同一客户端先后注册两个用户
    会静默串号（请求头写着 A，服务端按 cookie 认成 B）。越权、会话隔离这类
    「同时存在多个身份」的用例必须各用独立客户端。
    """
    created = []

    def factory(token=None):
        client = ApiClient(BASE_URL, TIMEOUT, auth=USER_AUTH, default_token=token)
        created.append(client)
        return client

    yield factory
    for client in created:
        client.session.close()


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

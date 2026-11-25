# -*- coding: utf-8 -*-
"""{{PROJECT}} 的 pytest fixtures（业务层）。

换系统时只改本文件与 config.py / helpers.py：内核 framework.* 无需改动。
本模板已接好五套机制（与 shopping 项目能力基线对齐）：

1. 启动体检：后端不可达时一条 ERROR 中止，不让每条用例各报一次 ConnectionRefused；
2. 必填配置：CFG.require() 只登记，缺失项由体检一次性汇总（--collect-only 不受影响）；
3. 缺陷台账：known_defects.yaml + 收集清单双向校验，CI 可加 --check 门禁；
4. 清理：注册式 cleaner + 兜底 sweep（内核二次校验前缀，仅主进程执行）；
5. 多身份隔离：new_client 给每个身份独立 cookie jar，避免 Cookie 优先的后端串号。

标有「按需」的部分按被测系统实际情况补充即可，不补也能 collect / 跑示例用例。
"""
from pathlib import Path

import pytest

from framework import coverage, defects, hooks
from framework.cleanup import CleanupRegistry, register_sweep
from framework.client import ApiClient, Envelope
from framework.extract import CaseContext
from framework.preflight import Check, Preflight, Skipped
from framework.state import state
from projects.{{PROJECT}}.config import (
    AUTH, AUTH_PASSWORD, AUTH_USERNAME, BASE_URL, DATA_SOURCE,
    MODULE_LABELS, PREFLIGHT_TIMEOUT, PROJECT_LABEL, REPORT_NOTES,
    SUCCESS_CODE, TIMEOUT,
)
from projects.{{PROJECT}}.helpers import uid


def pytest_configure(config):
    """把项目信息注入报告钩子，并登记覆盖率 / 缺陷台账基准文件。"""
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
    # xfail 缺陷台账：data/known_defects.yaml，project 名隔离收集清单
    defects.configure(Path(__file__).parent / 'data' / 'known_defects.yaml',
                      project='{{PROJECT}}')
    _register_sweeps()


def _register_sweeps():
    """按需：兜底清理，收尾时按本轮测试标识扫描残留。

    与注册式 cleaner 的区别：cleaner 只收用例主动登记的数据；sweep 负责补
    「用例中途异常 / 新人忘了 register」留下的脏数据。内核会在 clean 前二次
    校验 prefixes，discover 扫宽了也删不到真实数据。

    需要时按被测系统的存储方式提供 discover / clean（例如业务 db 模块）：
        register_sweep('测试用户', discover=db.scan_test_keys,
                       clean=db.delete_test_keys,
                       fallback='按前缀扫描的残留删除失败', prefixes=('API',))
    新项目若没有可扫的存储，留空即可——不影响注册式清理。
    """


# ---------- 启动体检 ----------

# 会话态私有槽位：体检登录与 fixture 共用，避免重复登录；名字带项目名防串扰。
_TOKENS: dict = state.namespace('{{PROJECT}}.tokens')


def _client() -> ApiClient:
    """统一构造客户端；响应包装由 Envelope(success_code=...) 适配。"""
    return ApiClient(BASE_URL, TIMEOUT, auth=AUTH,
                     envelope=Envelope(success_code=SUCCESS_CODE))


def _fill_tokens() -> None:
    """登录一次并写入会话态槽位，供体检结果与 tokens fixture 共用。

    本模板只有一个账号；多角色项目请照 shopping 的范式改为逐角色登录，
    全部成功再写入，避免留下半套 token 掩盖真正原因。
    """
    client = _client()
    client.login(AUTH_USERNAME, AUTH_PASSWORD)
    fresh = {
        'token': client.default_token,
        'cookies': dict(client.session.cookies),
    }
    _TOKENS.update(fresh)


def _preflight_checks() -> list:
    """体检项：配置齐备 → 服务可达 → 健康自检 → 登录可用。

    全部只读、快速失败；某项挂掉不影响其余项跑完（一轮把问题说全）。
    前置不满足时抛 Skipped，把「没测」与「测了不通过」分开。
    有数据库的项目可再加一项：用业务 db 模块执行 SELECT 1，
    required 由 config 的 DB_STRICT 决定（本地无库可跳过，CI 必须可用）。
    """
    probe: dict = {}

    def health():
        if 'result' not in probe:
            # 诊断请求不重试、不注入 trace：服务没起时重试只会翻倍等待
            probe_client = ApiClient(BASE_URL, PREFLIGHT_TIMEOUT,
                                     retry_enabled=False, trace_enabled=False)
            probe['result'] = probe_client.get('/api/health')
        return probe['result']

    def service_up():
        result = health()
        return result.status == 200 and result.ok

    def config_complete():
        """CFG.require 只登记不抛错，缺项在这里一次性说清。"""
        missing = missing_required()
        if missing:
            raise AssertionError('缺少必填配置：%s（请在 .env 或进程环境变量中补充）'
                                 % '、'.join('%s[%s]' % (key, env)
                                            for key, env in sorted(missing.items())))
        return '必填键齐备'

    def service_reachable():
        result = health()
        if result.status == 0:
            raise AssertionError('无法连接 %s：%s' % (BASE_URL, result.message or '无响应'))
        if result.status != 200 or not result.ok:
            raise AssertionError('GET /api/health → HTTP %s / code %s'
                                 % (result.status, result.code))
        return 'HTTP 200 · code %s · %d ms' % (result.code, result.elapsed_ms)

    def service_healthy():
        if not service_up():
            raise Skipped('后端不可达（见上一项），未执行健康自检')
        data = health().data
        status = data.get('status') if isinstance(data, dict) else None
        if status != 'UP':
            raise AssertionError('健康自检 status=%r，期望 UP' % (status,))
        return 'status=UP'

    def login_ready():
        if not service_up():
            raise Skipped('后端不可达（见上一项），未执行登录校验')
        _fill_tokens()
        return '%s 登录成功' % AUTH_USERNAME

    return [
        Check('必填配置', config_complete,
              hint='照 .env.example 补齐缺项；CI 从 .env.example 生成 .env 即为此项服务'),
        Check('后端可达', service_reachable,
              hint='先启动被测服务，并确认 .env 的 {{PREFIX}}API_BASE_URL=%s' % BASE_URL),
        Check('服务自检', service_healthy, required=False,
              hint='/api/health 的 status 不是 UP：检查被测服务依赖'),
        Check('登录可用', login_ready,
              hint='核对 .env 的 {{PREFIX}}USERNAME / {{PREFIX}}PASSWORD'),
    ]


def pytest_sessionstart(session):
    """收集用例前体检：环境没备好就一条 ERROR 中止，用例零执行。

    --collect-only 不联网；API_PREFLIGHT_ENABLED=0 关闭；
    API_PREFLIGHT_STRICT=0 只告警不中止。
    """
    if session.config.getoption('collectonly', False):
        return
    Preflight(_preflight_checks()).run_or_exit()


# ---------- fixtures ----------

@pytest.fixture(scope='session')
def auth_state():
    """登录态（session 级）：体检时已登录则复用，未体检则在此登录。"""
    if 'token' not in _TOKENS:
        _fill_tokens()
    return dict(_TOKENS)


@pytest.fixture(scope='session')
def token(auth_state):
    return auth_state['token']


@pytest.fixture(scope='session')
def tokens(token):
    """角色 → token 映射。

    ⚠️ 本模板只有单账号，'user' 与 'admin' 指向同一个 token，仅用于演示。
    真实项目若有多个角色，**必须分别登录并各用独立客户端**（见下方 new_client），
    否则在 Cookie 优先的后端上会静默串号：请求头写着 A，服务端按 Cookie 认成 B。
    """
    return {'anonymous': None, 'user': token, 'admin': token}


@pytest.fixture
def api(extras, auth_state):
    client = _client()
    if auth_state.get('cookies'):
        client.session.cookies.update(auth_state['cookies'])
    client.default_token = auth_state['token']
    client.extras = extras  # pytest-html 4.x 的 extras fixture
    return client


@pytest.fixture
def new_client():
    """工厂：每次创建独立 cookie jar，给「同时存在多个身份」的用例用。

    越权 / 会话隔离用例不要复用共享的 api fixture——它的 Session 会累积 Set-Cookie。
    用法：a = new_client(token_a); b = new_client(token_b)，各自请求互不串号。
    """
    created = []

    def factory(token=None):
        client = ApiClient(BASE_URL, TIMEOUT, auth=AUTH, default_token=token)
        created.append(client)
        return client

    yield factory
    for client in created:
        client.session.close()


@pytest.fixture
def cleaner(api):
    """注册式清理：业务动作按需登记，teardown 统一执行并写入报告汇总。"""
    instance = CleanupRegistry()
    yield instance
    instance.run()


@pytest.fixture
def ctx(extras):
    """用例内依赖链：remember 记录上游响应值，render 渲染下游请求参数。"""
    return CaseContext(extras=extras)


@pytest.fixture
def scenario_variables(token):
    """场景编排初始变量：${token} 登录态、${uid} 场景唯一串。

    function 作用域保证每条场景独立（xdist 并行不串值）；
    需要多角色时在这里补对应 token 变量。
    """
    return {'token': token, 'uid': uid('SCEN')}


@pytest.fixture(scope='session')
def role_tokens(tokens):
    """权限矩阵的角色 → token 映射；按被测系统角色增减键即可。

    真实多角色项目：把 tokens 拆成独立登录后，这里返回各自的 token。
    """
    return {
        'anonymous': None,
        'user': tokens.get('user'),
        'admin': tokens.get('admin'),
    }

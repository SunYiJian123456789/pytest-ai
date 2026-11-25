# -*- coding: utf-8 -*-
"""YAML 场景编排（framework 内核）：一个 YAML 块描述一条多步业务链路。

定位：让「线性正向业务链路」用例也数据驱动——测试人员只写 YAML，不写 Python。
用例入口是项目里的一个通用 test 函数（脚手架模板 ``test_04_scenarios.py``）：
按场景名参数化，逐条调用 :func:`run_scenario`。

**适用边界（能力储备，不是主流程默认写法）**：本引擎只描述「请求 → 断言 →
提取 → 下一步」的线性正向链路，刻意不引入条件分支、循环与 pytest 参数化。
下列场景请继续写 Python 用例，不要硬塞进 YAML：

- 负向 / 异常面（非法值参数化、鉴权异常、越权矩阵）——pytest 的 parametrize
  与 marker 表达力更强；
- 落库断言、软断言、多身份 client 切换——引擎刻意不支持，避免退化成另一个 pytest；
- 需要条件分支、循环或按响应动态决定下一步的链路——YAML 没有控制流。

一句话：能写成「一条直线走到底且只看 HTTP/业务信封」的链路才适合 YAML；
需要更强的断言与编排能力时，老老实实写 Python。

积木复用（本模块只做编排，不重复造轮子）：
- 请求走 ApiClient：Envelope / AuthSpec / 重试 / trace / 报告明细 / 敏感字段脱敏全部生效；
- 变量与渲染走 CaseContext：``${}`` 占位符，独占占位符保留原始类型（id 不转字符串）；
- 提取走 extract：默认业务 data 层，支持 ``data.list[0].id`` 数组下标；
- 断言走 assertions + schema：失败信息带场景名与步骤名；
- 清理走 CleanupRegistry：场景开始时注册，用例结束统一执行（步骤失败也执行），
  结果进报告的「清理汇总」。

YAML 结构::

    scenarios:
      - name: 下单支付
        vars: {order_name: 'SC-${uid}'}            # 场景级常量，可引用全局变量
        steps:
          - step: 创建订单
            request:
              method: POST
              path: /api/orders
              token: '${token}'                    # 缺省用 api 客户端默认登录态
              params: {channel: app}               # 可选 query
              body: {name: '${order_name}'}        # 可选 JSON 体
            extract: {order_id: data.id}           # 步骤断言通过后提取变量
            assert: {ok: true, code: 200}          # 缺省 = {ok: true}
          - step: 支付
            request: {method: POST, path: '/api/orders/${order_id}/pay'}
        cleanup:                                   # 用例结束执行（步骤失败也执行）
          - method: DELETE
            path: '/api/orders/${order_id}'
            ignore_missing: true                   # 目标不存在视为成功

变量来源（优先级从低到高）：conftest 的 ``scenario_variables`` fixture →
场景 ``vars`` → 步骤 ``extract``。未知字段名一律报错并列出合法键，
防止配置笔误静默失效。
"""
import html
import re
from pathlib import Path
from types import SimpleNamespace

import yaml
from pytest_html import extras as html_extras

from framework.assertions import (
    assert_code, assert_message_contains, assert_ok, assert_status,
)
from framework.extract import MISSING, CaseContext
from framework.schema import assert_data_schema, assert_schema

_VAR_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


def _check_keys(raw, allowed: frozenset, where: str) -> None:
    """未知字段即报错：宁可启动失败，不让笔误静默变成另一个含义。"""
    if not isinstance(raw, dict):
        raise TypeError('%s 必须是映射，收到 %s' % (where, type(raw).__name__))
    unknown = sorted(set(raw) - set(allowed))
    if unknown:
        raise ValueError('%s 含未知字段 %s；合法键：%s' % (where, unknown, sorted(allowed)))


def _check_var_name(name, where: str) -> str:
    name = str(name)
    if not _VAR_NAME.fullmatch(name):
        raise ValueError('%s 的变量名 %r 不合法（需为标识符，才能用 ${%s} 引用）' % (where, name, name))
    return name


class StepSpec:
    """一步：request 必填；extract / assert 可选。"""

    KEYS = frozenset({'step', 'request', 'extract', 'assert'})
    REQUEST_KEYS = frozenset({'method', 'path', 'params', 'body', 'token', 'headers'})
    ASSERT_KEYS = frozenset({'ok', 'http', 'code', 'message_has', 'schema', 'data_schema'})

    def __init__(self, raw, scenario: str, index: int):
        self.scenario = scenario
        self.index = index
        where = '场景 %r 第 %d 步' % (scenario, index)
        _check_keys(raw, self.KEYS, where)
        self.label = str(raw.get('step') or '第 %d 步' % index)

        request = raw.get('request')
        _check_keys(request, self.REQUEST_KEYS, where + ' 的 request')
        if not request.get('method') or not request.get('path'):
            raise ValueError('%s 的 request 缺少 method 或 path' % where)
        self.method = str(request['method']).upper()
        self.path = str(request['path'])
        self.params = request.get('params')
        self.body = request.get('body')
        self.token = request.get('token', MISSING)  # MISSING = 用客户端默认登录态
        self.headers = request.get('headers')

        self.extract = raw.get('extract') or {}
        if not isinstance(self.extract, dict):
            raise TypeError('%s 的 extract 必须是映射' % where)
        for name, path in self.extract.items():
            _check_var_name(name, where + ' 的 extract')
            if not isinstance(path, str) or not path.strip():
                raise ValueError('%s 的提取路径 %r 必须是非空字符串' % (where, path))

        self.expect = self._normalize_assert(raw.get('assert'), where)

    @staticmethod
    def _normalize_assert(raw, where: str) -> dict:
        raw = {} if raw is None else raw
        _check_keys(raw, StepSpec.ASSERT_KEYS, where + ' 的 assert')
        if 'ok' in raw and not isinstance(raw['ok'], bool):
            raise ValueError('%s 的 assert.ok 必须是布尔值' % where)
        return {
            'ok': raw.get('ok', True),  # 缺省期望业务成功
            'http': raw.get('http', MISSING),
            'code': raw.get('code', MISSING),
            'message_has': raw.get('message_has', ''),
            'schema': raw.get('schema', MISSING),
            'data_schema': raw.get('data_schema', MISSING),
        }

    def describe(self) -> str:
        return '[%s · 第 %d 步 %s]' % (self.scenario, self.index, self.label)


class CleanupItem:
    """场景清理项：用例结束执行，变量缺失（步骤未执行到）记 SKIP。"""

    KEYS = frozenset({'method', 'path', 'token', 'ignore_missing'})

    def __init__(self, raw, scenario: str, index: int):
        where = '场景 %r 清理项 %d' % (scenario, index)
        _check_keys(raw, self.KEYS, where)
        if not raw.get('method') or not raw.get('path'):
            raise ValueError('%s 缺少 method 或 path' % where)
        self.method = str(raw['method']).upper()
        self.path = str(raw['path'])
        self.token = raw.get('token', MISSING)
        self.ignore_missing = bool(raw.get('ignore_missing', False))
        self.label = '场景清理 %s %s' % (self.method, self.path)


class ScenarioSpec:
    """一条场景：name + steps 必填；vars / cleanup 可选。"""

    KEYS = frozenset({'name', 'vars', 'steps', 'cleanup'})

    def __init__(self, raw):
        _check_keys(raw, self.KEYS, '场景定义')
        self.name = raw.get('name')
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError('场景缺少非空字符串 name：%r' % (self.name,))
        self.vars = raw.get('vars') or {}
        if not isinstance(self.vars, dict):
            raise TypeError('场景 %r 的 vars 必须是映射' % self.name)
        for name in self.vars:
            _check_var_name(name, '场景 %r 的 vars' % self.name)

        steps = raw.get('steps')
        if not isinstance(steps, list) or not steps:
            raise ValueError('场景 %r 的 steps 必须是非空列表' % self.name)
        self.steps = [StepSpec(step, self.name, i) for i, step in enumerate(steps, 1)]

        cleanup = raw.get('cleanup') or []
        if not isinstance(cleanup, list):
            raise TypeError('场景 %r 的 cleanup 必须是列表' % self.name)
        self.cleanup = [CleanupItem(item, self.name, i)
                        for i, item in enumerate(cleanup, 1)]


def load_scenarios(file_path) -> dict:
    """读取 scenarios.yaml，返回 ``{场景名: ScenarioSpec}``；重名/结构错误在加载期报错。"""
    path = Path(file_path)
    # utf-8-sig：兼容 Windows 记事本/PowerShell 写出的带 BOM 文件
    data = yaml.safe_load(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or 'scenarios' not in data:
        raise ValueError('%s 顶层必须包含 scenarios 列表' % path)
    rows = data['scenarios']
    if not isinstance(rows, list) or not rows:
        raise ValueError('%s 的 scenarios 必须是非空列表' % path)
    scenarios: dict = {}
    for row in rows:
        spec = ScenarioSpec(row)
        if spec.name in scenarios:
            raise ValueError('%s 场景重名：%r' % (path, spec.name))
        scenarios[spec.name] = spec
    return scenarios


def _step_extras(ctx: CaseContext, text: str) -> None:
    """步骤标签写入报告 extras（复用 enh-ctx 样式），链路在报告里逐步可见。"""
    extras = getattr(ctx, 'extras', None)
    if extras is not None:
        extras.append(html_extras.html(
            '<div class="enh-ctx enh-step">▶ %s</div>' % html.escape(text)))


def _assert_step(step: StepSpec, result) -> None:
    hint = step.describe()
    expect = step.expect
    if expect['ok']:
        assert_ok(result, hint + ' 期望业务成功')
    else:
        assert not result.ok, '%s 期望业务失败，实际 %r' % (hint, result)
    if expect['http'] is not MISSING:
        assert_status(result, expect['http'], hint)
    if expect['code'] is not MISSING:
        assert_code(result, expect['code'], hint)
    if expect['message_has']:
        assert_message_contains(result, expect['message_has'], hint)
    if expect['schema'] is not MISSING:
        assert_schema(result, expect['schema'], label=hint)
    if expect['data_schema'] is not MISSING:
        assert_data_schema(result, expect['data_schema'], label=hint)


def _register_cleanups(api, cleaner, ctx: CaseContext, items) -> None:
    """场景开始时即注册清理：步骤中途失败，teardown 仍会回收已产生的数据。"""
    for item in items:
        def _run(item=item):
            try:
                path = ctx.render(item.path)
                token = None if item.token is MISSING else ctx.render(item.token)
            except KeyError as exc:
                # 变量未产生 = 所属步骤没执行到，无需清理；记 SKIP 而不是 FAIL
                return SimpleNamespace(ok=False, skipped=True,
                                       error='变量未产生 %s（所属步骤未执行到）' % exc)
            result = api.request(item.method, path, token=token)
            if item.ignore_missing and (result.code == 404 or '不存在' in (result.message or '')):
                return SimpleNamespace(ok=True, skipped=False, error='', message='')
            return result
        cleaner.register(item.label, _run)


def run_scenario(api, cleaner, ctx: CaseContext, spec, *, variables=None) -> list:
    """执行一条场景：按顺序跑步骤，任一步骤断言失败即中止（清理已在开始时注册）。

    :param api: ApiClient
    :param cleaner: CleanupRegistry（通常是项目 conftest 的 cleaner fixture）
    :param ctx: CaseContext（function 作用域 fixture），变量经它传递与渲染
    :param spec: ScenarioSpec 实例或原始 dict
    :param variables: 初始变量（如登录 token、唯一串），由项目的通用 test 函数提供
    :return: 每个步骤的 ApiResult 列表，供调用方追加断言
    """
    spec = spec if isinstance(spec, ScenarioSpec) else ScenarioSpec(spec)
    for name, value in (variables or {}).items():
        ctx.remember(_check_var_name(name, '场景 %r 的初始变量' % spec.name), value=value)
    for name, value in spec.vars.items():
        ctx.remember(name, value=ctx.render(value))  # vars 可引用初始变量组合出场景常量
    _register_cleanups(api, cleaner, ctx, spec.cleanup)

    results = []
    for step in spec.steps:
        _step_extras(ctx, '%s · 第 %d 步 %s' % (spec.name, step.index, step.label))
        kw = {}
        if step.params is not None:
            kw['params'] = ctx.render(step.params)
        if step.body is not None:
            kw['json_body'] = ctx.render(step.body)
        if step.token is not MISSING:
            kw['token'] = ctx.render(step.token)
        if step.headers is not None:
            kw['headers'] = ctx.render(step.headers)
        result = api.request(step.method, ctx.render(step.path), **kw)
        _assert_step(step, result)
        for var, expr in step.extract.items():
            ctx.remember(var, result, expr)  # 提取失败会带响应体报错，链路可定位
        results.append(result)
    return results

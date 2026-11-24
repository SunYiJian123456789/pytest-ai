# -*- coding: utf-8 -*-
"""内核单测：YAML 场景编排（加载校验 / 变量链 / 断言 / 清理注册），不依赖真实服务。"""
import pytest
import yaml

from framework.cleanup import CleanupRegistry
from framework.extract import CaseContext
from framework.client import ApiClient
from framework.scenario import (
    CleanupItem, ScenarioSpec, load_scenarios, run_scenario,
)

OK = {'code': 200, 'message': 'success', 'data': {}}


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else dict(OK)
        self.url = 'http://fake/test'
        self.headers = {'Content-Type': 'application/json'}

    def json(self):
        return self._payload


def make_client(script):
    """script：响应序列，元素为 payload 或 (status, payload)；记录每次调用的参数。"""
    # 关闭重试：脚本式响应序列要严格对应调用次数（500 触发的默认重试会错位）
    client = ApiClient('http://fake', retry_enabled=False, archive_failures=False)
    calls = []

    def fake(method, url, **kw):
        calls.append({'method': method, 'url': url, **kw})
        item = script[len(calls) - 1]
        status, payload = item if isinstance(item, tuple) else (200, item)
        return FakeResponse(status, payload)

    client.session.request = fake
    return client, calls


def spec(**overrides):
    base = {
        'name': '测试场景',
        'steps': [{'request': {'method': 'GET', 'path': '/ping'}}],
    }
    base.update(overrides)
    return base


def run(client, registry, raw, variables=None):
    ctx = CaseContext()
    results = run_scenario(client, registry, ctx, raw, variables=variables)
    return results, ctx


# ---------- 加载与校验 ----------

class TestLoadAndValidate:
    def test_load_maps_by_name(self, tmp_path):
        file = tmp_path / 'scenarios.yaml'
        file.write_text(yaml.safe_dump({'scenarios': [
            spec(),
            spec(name='第二条', steps=[{'step': 'ping',
                                       'request': {'method': 'GET', 'path': '/ping'}}]),
        ]}, allow_unicode=True), encoding='utf-8')
        loaded = load_scenarios(file)
        assert set(loaded) == {'测试场景', '第二条'}
        assert isinstance(loaded['测试场景'], ScenarioSpec)
        assert loaded['第二条'].steps[0].label == 'ping'

    def test_duplicate_name_rejected(self, tmp_path):
        file = tmp_path / 'scenarios.yaml'
        file.write_text(yaml.safe_dump({'scenarios': [spec(), spec()]}), encoding='utf-8')
        with pytest.raises(ValueError) as exc:
            load_scenarios(file)
        assert '重名' in str(exc.value)

    def test_unknown_step_key_rejected(self):
        with pytest.raises(ValueError) as exc:
            ScenarioSpec(spec(steps=[{'request': {'method': 'GET', 'path': '/x'},
                                      'stpes': 1}]))
        assert '未知字段' in str(exc.value) and 'stpes' in str(exc.value)

    def test_unknown_assert_key_rejected(self):
        with pytest.raises(ValueError) as exc:
            ScenarioSpec(spec(steps=[{'request': {'method': 'GET', 'path': '/x'},
                                      'assert': {'okk': False}}]))
        assert 'assert' in str(exc.value) and 'okk' in str(exc.value)

    def test_bad_extract_var_name_rejected(self):
        with pytest.raises(ValueError) as exc:
            ScenarioSpec(spec(steps=[{'request': {'method': 'GET', 'path': '/x'},
                                      'extract': {'1bad': 'data.id'}}]))
        assert '变量名' in str(exc.value)

    def test_cleanup_item_validation(self):
        with pytest.raises(ValueError):
            CleanupItem({'path': '/x'}, 's', 1)  # 缺 method
        with pytest.raises(ValueError):
            CleanupItem({'method': 'DELETE', 'path': '/x', 'oops': 1}, 's', 1)


# ---------- 执行链路 ----------

class TestRunScenario:
    def test_extract_then_render_next_step(self):
        client, calls = make_client([
            {'code': 200, 'message': 'ok', 'data': {'id': 7}},
            {'code': 200, 'message': 'ok', 'data': {'no': 'NO-7'}},
        ])
        raw = spec(steps=[
            {'step': '创建', 'request': {'method': 'POST', 'path': '/orders',
                                         'body': {'name': 'A'}, 'token': '${token}'},
             'extract': {'oid': 'data.id'}},
            {'step': '查询', 'request': {'method': 'GET', 'path': '/orders/${oid}'}},
        ])
        results, ctx = run(client, CleanupRegistry(), raw, variables={'token': 'TK'})
        assert ctx.value('oid') == 7
        assert calls[0]['json'] == {'name': 'A'}
        assert calls[0]['headers']['Authorization'] == 'Bearer TK'
        assert '/orders/7' in calls[1]['url']
        assert len(results) == 2

    def test_default_assert_requires_business_ok(self):
        client, _ = make_client([{'code': 400, 'message': 'bad', 'data': None}])
        with pytest.raises(AssertionError) as exc:
            run(client, CleanupRegistry(), spec())
        assert '测试场景' in str(exc.value) and '期望业务成功' in str(exc.value)

    def test_negative_assert_ok_false_with_code(self):
        client, _ = make_client([{'code': 400, 'message': 'bad', 'data': None}])
        raw = spec(steps=[{'request': {'method': 'GET', 'path': '/x'},
                           'assert': {'ok': False, 'code': 400, 'message_has': 'bad'}}])
        results, _ = run(client, CleanupRegistry(), raw)
        assert results[0].code == 400

    def test_http_and_data_schema_assertions(self):
        client, _ = make_client([(500, {'code': 500, 'message': 'boom', 'data': {'name': 'x'}})])
        raw = spec(steps=[{'request': {'method': 'GET', 'path': '/x'},
                           'assert': {'ok': False, 'http': 500,
                                      'data_schema': {'type': 'object', 'required': ['id']}}}])
        with pytest.raises(AssertionError) as exc:
            run(client, CleanupRegistry(), raw)
        assert 'required' in str(exc.value) and "'id'" in str(exc.value)

    def test_vars_reference_variables_and_render_body(self):
        client, calls = make_client([dict(OK)])
        raw = spec(vars={'name': 'SC-${uid}'},
                   steps=[{'request': {'method': 'POST', 'path': '/x',
                                       'body': {'name': '${name}'}}}])
        run(client, CleanupRegistry(), raw, variables={'uid': 'AB12'})
        assert calls[0]['json'] == {'name': 'SC-AB12'}

    def test_params_and_step_label_reported(self):
        client, calls = make_client([dict(OK)])
        captured = []
        client.extras = captured
        ctx = CaseContext(extras=captured)
        raw = spec(steps=[{'step': '带查询的步骤',
                           'request': {'method': 'GET', 'path': '/x', 'params': {'page': 1}}}])
        run_scenario(client, CleanupRegistry(), ctx, raw)
        assert calls[0]['params'] == {'page': 1}
        contents = ''.join(item['content'] for item in captured)
        assert '带查询的步骤' in contents and '▶' in contents

    def test_failure_stops_later_steps(self):
        client, calls = make_client([
            {'code': 400, 'message': 'bad', 'data': None},
            dict(OK),
        ])
        raw = spec(steps=[
            {'request': {'method': 'GET', 'path': '/a'}},
            {'request': {'method': 'GET', 'path': '/b'}},
        ])
        with pytest.raises(AssertionError):
            run(client, CleanupRegistry(), raw)
        assert len(calls) == 1  # 第一步失败即止


# ---------- 清理注册 ----------

class TestCleanup:
    def test_cleanup_registered_upfront_and_executed_with_vars(self):
        client, calls = make_client([
            {'code': 200, 'message': 'ok', 'data': {'id': 7}},
            dict(OK),
        ])
        registry = CleanupRegistry()
        raw = spec(steps=[{'request': {'method': 'POST', 'path': '/orders'},
                           'extract': {'oid': 'data.id'}}],
                   cleanup=[{'method': 'DELETE', 'path': '/orders/${oid}'}])
        run(client, registry, raw)
        assert len(registry.actions) == 1  # 场景开始即注册
        registry.run()
        assert calls[1]['method'] == 'DELETE'
        assert '/orders/7' in calls[1]['url']

    def test_cleanup_ignore_missing_treats_404_as_ok(self):
        client, calls = make_client([
            dict(OK),
            (200, {'code': 404, 'message': '订单不存在', 'data': None}),
        ])
        registry = CleanupRegistry()
        raw = spec(steps=[{'request': {'method': 'GET', 'path': '/x'}}],
                   cleanup=[{'method': 'DELETE', 'path': '/orders/1',
                             'ignore_missing': True}])
        run(client, registry, raw)
        entries = registry.run()
        assert entries[-1]['state'] == 'OK'
        assert calls[1]['method'] == 'DELETE'

    def test_cleanup_missing_variable_records_skip(self):
        client, calls = make_client([dict(OK)])
        registry = CleanupRegistry()
        raw = spec(steps=[{'request': {'method': 'POST', 'path': '/x'}}],
                   cleanup=[{'method': 'DELETE', 'path': '/orders/${never_made}'}])
        run(client, registry, raw)  # 步骤成功但没有 extract，变量 never_made 不存在
        entries = registry.run()
        assert entries[-1]['state'] == 'SKIP'
        assert all(call['method'] != 'DELETE' for call in calls)  # 未发无谓请求

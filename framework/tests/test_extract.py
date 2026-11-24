# -*- coding: utf-8 -*-
"""framework 内核单元测试：响应提取与用例上下文。

不属于任何业务项目，默认 testpaths 不收集；单独运行：
    python -m pytest framework/tests -o addopts= -q
"""
import pytest

from framework.client import ApiResult, Envelope
from framework.extract import CaseContext, extract, extract_many


def make_result(data, payload=None):
    payload = payload if payload is not None else {'code': 200, 'data': data}
    return ApiResult(
        status=200, code=200, message='ok', data=data,
        elapsed_ms=1, raw='response-body', url='http://x/api',
        payload=payload, envelope=Envelope(),
    )


class TestExtract:
    def test_default_root_is_business_data(self):
        assert extract(make_result({'id': 42}), 'id') == 42

    def test_explicit_data_and_payload_roots(self):
        result = make_result({'id': 42}, payload={'code': 200, 'data': {'id': 7}})
        assert extract(result, 'data.id') == 42
        assert extract(result, 'payload.data.id') == 7

    def test_whole_data_layer(self):
        assert extract(make_result({'id': 42}), 'data') == {'id': 42}

    def test_list_index_and_nested_path(self):
        data = {'list': [{'id': 7}, {'id': 8}], 'meta': {'token': 'T'}}
        assert extract(make_result(data), 'data.list[0].id') == 7
        assert extract(make_result(data), 'list[1].id') == 8
        assert extract(make_result(data), 'meta.token') == 'T'

    def test_jsonpath_prefix_is_ignored(self):
        assert extract(make_result({'id': 42}), '$.data.id') == 42

    def test_plain_dict_and_list_source(self):
        assert extract({'a': {'b': 3}}, 'a.b') == 3
        assert extract([{'id': 9}], '[0].id') == 9

    def test_default_value_on_missing_path(self):
        assert extract(make_result({'id': 42}), 'missing', default='X') == 'X'

    def test_missing_path_raises_with_response_detail(self):
        with pytest.raises(AssertionError) as exc:
            extract(make_result({'id': 42}), 'data.noSuchField')
        message = str(exc.value)
        assert 'data.noSuchField' in message
        assert 'noSuchField' in message
        assert 'response-body' in message  # 失败时能定位到响应体

    def test_extract_many(self):
        got = extract_many(make_result({'id': 5, 'name': 'n'}),
                           pid='data.id', title='data.name')
        assert got == {'pid': 5, 'title': 'n'}


class TestCaseContext:
    def test_remember_from_result_and_plain_value(self):
        ctx = CaseContext()
        ctx.remember('pid', make_result({'id': 5}), 'data.id')
        ctx.remember('name', value='APIA')
        assert ctx.value('pid') == 5
        assert ctx.get('name') == 'APIA'
        assert 'pid' in ctx
        assert ctx.as_dict() == {'pid': 5, 'name': 'APIA'}

    def test_render_path_preserves_types(self):
        ctx = CaseContext().remember('pid', value=5).remember('name', value='APIA')
        assert ctx.render('/api/products/${pid}') == '/api/products/5'
        assert ctx.render({'id': '${pid}', 'label': 'item-${name}'}) == {
            'id': 5, 'label': 'item-APIA',
        }
        assert ctx.render(['${pid}', {'n': '${name}'}]) == [5, {'n': 'APIA'}]

    def test_missing_variable_raises_with_known_names(self):
        ctx = CaseContext().remember('pid', value=5)
        with pytest.raises(KeyError) as exc:
            ctx.render('/x/${unknown}')
        assert 'unknown' in str(exc.value)
        assert 'pid' in str(exc.value)

    def test_isolated_between_instances(self):
        first = CaseContext().remember('pid', value=1)
        second = CaseContext()
        assert 'pid' not in second
        assert first.value('pid') == 1


class TestPermissionMatrix:
    """权限矩阵内核单测：用 fake client 验证断言与角色解析，不依赖真实服务。"""

    class FakeClient:
        def __init__(self, status=200, code=200, message='success'):
            self.status, self.code, self.message = status, code, message
            self.calls = []

        def request(self, method, path, **kw):
            self.calls.append((method, path, kw.get('token')))
            from framework.client import ApiResult, Envelope
            return ApiResult(
                status=self.status, code=self.code, message=self.message,
                data={}, elapsed_ms=1, raw='', url=path,
                envelope=Envelope(),
            )

    def test_anonymous_gets_no_token(self):
        from framework.permissions import check_permission
        api = self.FakeClient(code=401, message='请先登录')
        row = {'role': 'anonymous', 'method': 'GET', 'path': '/api/cart',
               'expect_code': 401, 'message_has': '请先登录'}
        check_permission(api, row, {'anonymous': None, 'user': 'U'})
        assert api.calls[0][2] is None

    def test_role_token_and_expect_http(self):
        from framework.permissions import check_permission
        api = self.FakeClient(status=200, code=200)
        row = {'role': 'admin', 'method': 'GET', 'path': '/api/admin/stats',
               'expect_http': 200, 'expect_code': 200}
        check_permission(api, row, {'anonymous': None, 'admin': 'ADM'})
        assert api.calls[0][2] == 'ADM'

    def test_token_from_overrides_role(self):
        from framework.permissions import check_permission
        api = self.FakeClient()
        row = {'role': 'user', 'token_from': 'user_b', 'method': 'GET', 'path': '/api/cart'}
        check_permission(api, row, {'user': 'A', 'user_b': 'B'})
        assert api.calls[0][2] == 'B'

    def test_mismatch_raises_with_row_description(self):
        from framework.permissions import check_permission
        api = self.FakeClient(code=200)
        row = {'label': '未登录应被拒', 'role': 'anonymous', 'path': '/api/cart',
               'expect_code': 401}
        with pytest.raises(AssertionError) as exc:
            check_permission(api, row, {'anonymous': None})
        assert '未登录应被拒' in str(exc.value)
        assert '401' in str(exc.value)

    def test_unknown_role_lists_available(self):
        from framework.permissions import check_permission
        api = self.FakeClient()
        with pytest.raises(KeyError) as exc:
            check_permission(api, {'role': 'ghost', 'path': '/x'}, {'anonymous': None})
        assert 'ghost' in str(exc.value)
        assert 'anonymous' in str(exc.value)

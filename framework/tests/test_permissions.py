# -*- coding: utf-8 -*-
"""内核单测：权限矩阵的行解析、凭证解析、路径变量渲染，不依赖真实服务。"""
import pytest

from framework.client import ApiResult, Envelope
from framework.permissions import PermissionRow, check_permission, run_matrix


class FakeApi:
    """记录收到的请求，返回预设响应；用于断言"发了什么请求"。"""

    def __init__(self, status=200, code=200, message='success', data=None):
        self.status = status
        self.code = code
        self.message = message
        self.data = data
        self.calls = []

    def request(self, method, path, **kw):
        self.calls.append({'method': method, 'path': path, **kw})
        return ApiResult(
            status=self.status, code=self.code, message=self.message, data=self.data,
            elapsed_ms=1, raw='{}', url='http://fake' + path, envelope=Envelope(),
            payload={'code': self.code, 'message': self.message, 'data': self.data},
        )

    @property
    def last(self):
        return self.calls[-1]


class TestRowParsing:
    def test_defaults(self):
        row = PermissionRow({'method': 'get', 'path': '/api/x'})
        assert row.method == 'GET' and row.role == 'anonymous'
        assert row.label == 'GET /api/x'
        assert row.token_from == '' and row.params is None

    def test_missing_path_raises(self):
        with pytest.raises(ValueError):
            check_permission(FakeApi(), {'label': '无路径'}, {})

    def test_non_dict_raises(self):
        with pytest.raises(TypeError):
            PermissionRow(['not', 'a', 'dict'])

    def test_describe_lists_expectations(self):
        row = PermissionRow({'label': '匿名访问', 'method': 'GET', 'path': '/api/cart',
                             'expect_http': 401, 'expect_code': 401, 'message_has': '请先登录'})
        text = row.describe()
        assert '匿名访问' in text and 'HTTP 401' in text and 'code 401' in text
        assert '请先登录' in text


class TestCredentialResolution:
    def test_anonymous_sends_no_token(self):
        api = FakeApi()
        check_permission(api, {'method': 'GET', 'path': '/api/cart'}, {})
        assert api.last['token'] is None

    def test_role_maps_to_token(self):
        api = FakeApi()
        check_permission(api, {'role': 'user', 'method': 'GET', 'path': '/api/cart'},
                         {'user': 'T-USER'})
        assert api.last['token'] == 'T-USER'

    def test_token_from_overrides_role(self):
        """越权场景：role 写资源归属者，token_from 指定实际请求凭证。"""
        api = FakeApi()
        check_permission(api, {'role': 'victim', 'token_from': 'attacker',
                               'method': 'DELETE', 'path': '/api/cart/1'},
                         {'victim': 'T-VICTIM', 'attacker': 'T-ATTACKER'})
        assert api.last['token'] == 'T-ATTACKER'

    def test_unknown_role_lists_available(self):
        with pytest.raises(KeyError) as exc:
            check_permission(FakeApi(), {'role': 'nobody', 'path': '/api/x'}, {'user': 'T'})
        assert 'nobody' in str(exc.value) and 'user' in str(exc.value)

    def test_unknown_token_from_lists_available(self):
        with pytest.raises(KeyError) as exc:
            check_permission(FakeApi(), {'token_from': 'ghost', 'path': '/api/x'},
                             {'attacker': 'T'})
        assert 'ghost' in str(exc.value) and 'attacker' in str(exc.value)

    def test_token_resolver_takes_precedence(self):
        api = FakeApi()
        seen = []

        def resolver(name):
            seen.append(name)
            return 'DYN-' + name

        check_permission(api, {'role': 'victim', 'token_from': 'attacker',
                               'method': 'PUT', 'path': '/api/cart/1'},
                         {}, token_resolver=resolver)
        assert seen == ['attacker'] and api.last['token'] == 'DYN-attacker'


class TestVariableRendering:
    def test_path_variable_rendered(self):
        api = FakeApi()
        check_permission(api, {'method': 'DELETE', 'path': '/api/cart/${cart_item_id}'},
                         {}, variables={'cart_item_id': 42})
        assert api.last['path'] == '/api/cart/42'

    def test_params_and_json_body_rendered_recursively(self):
        api = FakeApi()
        check_permission(
            api,
            {'method': 'POST', 'path': '/api/cart/${item}',
             'params': {'page': '${page}', 'fixed': 1},
             'json_body': {'id': '${item}', 'nested': [{'q': '${page}'}]}},
            {}, variables={'item': 7, 'page': 2},
        )
        assert api.last['params'] == {'page': 2, 'fixed': 1}
        assert api.last['json_body'] == {'id': 7, 'nested': [{'q': 2}]}

    def test_whole_placeholder_keeps_type(self):
        api = FakeApi()
        check_permission(api, {'method': 'PUT', 'path': '/api/x',
                               'json_body': {'quantity': '${qty}'}},
                         {}, variables={'qty': 0})
        assert api.last['json_body'] == {'quantity': 0}

    def test_unresolved_placeholder_raises(self):
        with pytest.raises(KeyError) as exc:
            check_permission(FakeApi(), {'path': '/api/cart/${missing}'},
                             {}, variables={'other': 1})
        assert 'missing' in str(exc.value)

    def test_no_variables_leaves_literal_path(self):
        api = FakeApi()
        check_permission(api, {'path': '/api/products/1'}, {})
        assert api.last['path'] == '/api/products/1'


class TestExpectations:
    def test_http_mismatch_reports_row_label(self):
        api = FakeApi(status=200, code=200)
        with pytest.raises(AssertionError) as exc:
            check_permission(api, {'label': '应被拒绝', 'path': '/api/x', 'expect_http': 401}, {})
        assert '应被拒绝' in str(exc.value) and '401' in str(exc.value)

    def test_business_code_mismatch(self):
        api = FakeApi(status=200, code=0, message='boom')
        with pytest.raises(AssertionError) as exc:
            check_permission(api, {'path': '/api/x', 'expect_code': 401}, {})
        assert 'code 期望 401' in str(exc.value)

    def test_message_contains(self):
        api = FakeApi(code=403, message='无权访问该资源')
        with pytest.raises(AssertionError) as exc:
            check_permission(api, {'path': '/api/x', 'message_has': '未登录'}, {})
        assert '无权访问该资源' in str(exc.value)

    def test_no_expectation_only_requires_reachable(self):
        api = FakeApi(status=500, code=500, message='err')
        result = check_permission(api, {'path': '/api/x'}, {})
        assert result.status == 500  # 只断言可达：状态由调用方决定是否进一步判断


class TestRunMatrix:
    def test_returns_one_result_per_row_and_keeps_order(self):
        api = FakeApi()
        rows = [{'label': 'a', 'path': '/a'}, {'label': 'b', 'path': '/b'}]
        results = run_matrix(api, rows, {}, variables={'x': 1})
        assert [c['path'] for c in api.calls] == ['/a', '/b']
        assert len(results) == 2

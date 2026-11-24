# -*- coding: utf-8 -*-
"""响应契约校验示范：结构写在 YAML，用例只负责选场景。"""
import pytest

from framework.schema import assert_schema
from projects.shopping.data import load

SCHEMAS = load().get('response_schemas', {})


@pytest.mark.contract
@pytest.mark.parametrize('name,path,token_key', [
    ('health', '/api/health', None),
    ('categories', '/api/categories', None),
    ('user_me', '/api/auth/me', 'user'),
    ('admin_stats', '/api/admin/stats', 'admin'),
])
def test_response_schema(api, tokens, name, path, token_key):
    """校验 HTTP 2xx 响应的字段存在性、类型与取值范围。"""
    assert name in SCHEMAS, 'YAML 未定义响应契约: %s' % name
    result = api.get(path, token=tokens.get(token_key) if token_key else None)
    assert result.ok, result
    assert_schema(result, SCHEMAS[name], label=name)


@pytest.mark.contract
def test_schema_mismatch_has_clear_location(api):
    """负向自检：故意用错误 schema 校验，确认失败信息能定位到字段路径。"""
    result = api.get('/api/health')
    assert result.ok, result
    wrong = {
        'type': 'object',
        'required': ['data'],
        'properties': {'data': {'type': 'object', 'required': ['not_exists']}},
    }
    with pytest.raises(AssertionError) as exc:
        assert_schema(result, wrong, label='故意错误的契约')
    message = str(exc.value)
    assert '故意错误的契约' in message
    assert 'data.not_exists' in message
    assert '响应体' in message

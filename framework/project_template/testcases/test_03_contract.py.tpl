# -*- coding: utf-8 -*-
"""响应契约校验：schema 写在 data/api_cases.yaml 的 response_schemas。"""
import pytest

from framework.schema import assert_schema
from projects.{{PROJECT}}.data import load, records

SCHEMAS = load().get('response_schemas', {})


@pytest.mark.contract
@pytest.mark.parametrize('row', records('response_schemas_cases'))
def test_response_schema(api, row):
    """按 YAML 中声明的路径与 schema 校验响应结构。"""
    name, path = row['name'], row['path']
    assert name in SCHEMAS, 'YAML 未定义响应契约: %s' % name
    result = api.get(path)
    assert result.ok, result
    assert_schema(result, SCHEMAS[name], label=name)

# -*- coding: utf-8 -*-
"""响应契约校验消费方：结构来自 data/contracts.yaml，用例只选契约名。

契约是服务方与消费方共用的资产：这里只负责按契约校验真实响应；
契约变更是否破坏消费方，由 CI 的 framework.contract check 门禁拦截。
"""
from pathlib import Path

import pytest
import yaml

from framework.contract import assert_contract, get_contract, load_contracts

CONTRACT_FILE = Path(__file__).parents[1] / 'data' / 'contracts.yaml'
CONTRACTS = load_contracts(CONTRACT_FILE)
INVENTORY_FILE = Path(__file__).parents[1] / 'data' / 'api_inventory.yaml'


@pytest.mark.contract
@pytest.mark.parametrize('name', ['health', 'categories', 'user_me', 'admin_stats'])
def test_response_schema(api, tokens, name):
    """按契约校验 2xx 响应的字段存在性、类型与取值范围。"""
    item = get_contract(CONTRACTS, name)
    role = item.get('token')
    result = api.get(item['path'], token=tokens.get(role) if role else None)
    assert result.ok, result
    assert_contract(result, item, label=name)


@pytest.mark.contract
def test_contract_endpoints_registered_in_inventory():
    """契约里的 method/path 必须在接口清单登记，避免契约与被测接口脱节。"""
    with INVENTORY_FILE.open(encoding='utf-8') as handle:
        inventory = yaml.safe_load(handle)
    registered = {(row['method'], row['path'])
                  for row in inventory.get('endpoints', [])}
    missing = ['%s %s（%s）' % (item['method'], item['path'], name)
               for name, item in CONTRACTS.items()
               if (item['method'], item['path']) not in registered]
    assert not missing, '契约接口未在清单登记：%s' % '、'.join(sorted(missing))


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
        assert_contract(result, {'response': wrong}, label='故意错误的契约')
    message = str(exc.value)
    assert '故意错误的契约' in message
    assert 'data.not_exists' in message
    assert '响应体' in message

# -*- coding: utf-8 -*-
"""响应契约校验消费方：结构来自 data/contracts.yaml，用例只选契约名。

契约是服务方与消费方共用的资产：这里只校验真实响应；
契约变更是否破坏消费方，由 CI 的 framework.contract check 门禁拦截。
"""
from pathlib import Path

import pytest

from framework.contract import assert_contract, get_contract, load_contracts

CONTRACT_FILE = Path(__file__).parents[1] / 'data' / 'contracts.yaml'
CONTRACTS = load_contracts(CONTRACT_FILE)


@pytest.mark.contract
@pytest.mark.parametrize('name', sorted(CONTRACTS))
def test_response_schema(api, tokens, name):
    """按契约校验 2xx 响应的字段存在性、类型与取值范围。"""
    item = get_contract(CONTRACTS, name)
    role = item.get('token')
    result = api.get(item['path'], token=tokens.get(role) if role else None)
    assert result.ok, result
    assert_contract(result, item, label=name)

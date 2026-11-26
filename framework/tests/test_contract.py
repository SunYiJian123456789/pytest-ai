# -*- coding: utf-8 -*-
"""契约外置内核单测：加载自检、消费方校验、提供方兼容性门禁。"""
import json

import pytest
import yaml

from framework import contract


class FakeResult:
    """最小 ApiResult 替身：只提供 schema 校验需要的三个属性。"""

    def __init__(self, payload):
        self.payload = payload
        self.data = payload.get('data') if isinstance(payload, dict) else None
        self.raw = json.dumps(payload, ensure_ascii=False)


def _write(tmp_path, contracts, version=1):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / 'contracts.yaml'
    path.write_text(yaml.safe_dump({
        'version': version,
        'project': 'demo',
        'contracts': contracts,
    }, allow_unicode=True, sort_keys=False), encoding='utf-8')
    return path


def _contract(response, method='GET', path='/api/demo'):
    return {'method': method, 'path': path, 'response': response}


BASE_SCHEMA = {
    'type': 'object',
    'required': ['code', 'data'],
    'properties': {
        'code': {'type': 'integer'},
        'data': {
            'type': 'object',
            'required': ['id', 'name'],
            'properties': {
                'id': {'type': 'integer', 'minimum': 1},
                'name': {'type': 'string', 'minLength': 1},
                'status': {'type': 'string', 'enum': ['on', 'off']},
            },
        },
    },
}


# ---------- 加载与自检 ----------

def test_load_valid(tmp_path):
    path = _write(tmp_path, {'demo': _contract(BASE_SCHEMA)})
    loaded = contract.load_contracts(path)
    assert list(loaded) == ['demo']
    assert loaded['demo']['path'] == '/api/demo'


@pytest.mark.parametrize('version', [None, 2, '1'])
def test_load_rejects_bad_version(tmp_path, version):
    path = _write(tmp_path, {'demo': _contract(BASE_SCHEMA)}, version=version)
    with pytest.raises(ValueError, match='version'):
        contract.load_contracts(path)


def test_load_rejects_empty_contracts(tmp_path):
    path = _write(tmp_path, {})
    with pytest.raises(ValueError, match='非空 contracts'):
        contract.load_contracts(path)


@pytest.mark.parametrize('field', ['method', 'path', 'response'])
def test_load_rejects_missing_field(tmp_path, field):
    item = _contract(BASE_SCHEMA)
    del item[field]
    path = _write(tmp_path, {'demo': item})
    with pytest.raises(ValueError, match=field):
        contract.load_contracts(path)


def test_load_rejects_bad_path(tmp_path):
    path = _write(tmp_path, {'demo': _contract(BASE_SCHEMA, path='api/demo')})
    with pytest.raises(ValueError, match='以 / 开头'):
        contract.load_contracts(path)


def test_load_rejects_invalid_schema(tmp_path):
    bad = {'type': 'object', 'required': 'not-a-list'}
    path = _write(tmp_path, {'demo': _contract(bad)})
    with pytest.raises(ValueError, match='合法 JSON Schema'):
        contract.load_contracts(path)


def test_get_contract_missing_lists_names(tmp_path):
    path = _write(tmp_path, {'demo': _contract(BASE_SCHEMA)})
    loaded = contract.load_contracts(path)
    with pytest.raises(KeyError, match='demo'):
        contract.get_contract(loaded, 'nope')


# ---------- 消费方：响应校验 ----------

def test_assert_contract_pass(tmp_path):
    path = _write(tmp_path, {'demo': _contract(BASE_SCHEMA)})
    item = contract.get_contract(contract.load_contracts(path), 'demo')
    contract.assert_contract(
        FakeResult({'code': 200, 'data': {'id': 1, 'name': 'x', 'status': 'on'}}),
        item, label='demo')


def test_assert_contract_reports_field_path(tmp_path):
    path = _write(tmp_path, {'demo': _contract(BASE_SCHEMA)})
    item = contract.get_contract(contract.load_contracts(path), 'demo')
    with pytest.raises(AssertionError) as exc:
        contract.assert_contract(
            FakeResult({'code': 200, 'data': {'id': 0, 'name': ''}}), item, label='demo')
    message = str(exc.value)
    assert 'demo' in message
    assert 'data.id' in message
    assert '响应体' in message


def test_assert_contract_rejects_bad_contract():
    with pytest.raises(TypeError, match='response schema'):
        contract.assert_contract(FakeResult({}), {'path': '/api/demo'})


# ---------- 提供方：破坏性变更判定 ----------

def _check(baseline, current):
    return contract.check_compatibility(
        {'demo': _contract(baseline)}, {'demo': _contract(current)})


@pytest.mark.parametrize('mutate,keyword', [
    (lambda s: s['properties'].pop('code'), '删除字段'),
    (lambda s: s.update({'type': 'array'}), '类型'),
    (lambda s: s['required'].append('new'), '新增必填'),
    (lambda s: s['properties']['data']['properties']['id'].update({'minimum': 5}), '收紧'),
    (lambda s: s['properties']['code'].update({'const': 500}), 'const'),
    (lambda s: s['properties']['data']['properties']['status'].update({'enum': ['on']}), 'enum'),
    (lambda s: s['properties']['data']['properties']['name'].update({'pattern': '^a'}), 'pattern'),
    (lambda s: s.update({'additionalProperties': False}), 'additionalProperties'),
    (lambda s: s['properties']['data']['properties'].pop('status'), '删除字段'),
])
def test_breaking_changes_detected(mutate, keyword):
    current = json.loads(json.dumps(BASE_SCHEMA))
    mutate(current)
    result = _check(BASE_SCHEMA, current)
    assert not result['ok']
    assert any(keyword in issue for issue in result['issues']), result['issues']


@pytest.mark.parametrize('mutate', [
    lambda s: s['properties']['data']['properties'].update({'extra': {'type': 'string'}}),
    lambda s: s['required'].pop(),
    lambda s: s['properties']['data']['properties']['id'].update({'minimum': 0}),
    lambda s: s['properties']['data']['properties']['status'].update(
        {'enum': ['on', 'off', 'other']}),
])
def test_allowed_changes_pass(mutate):
    current = json.loads(json.dumps(BASE_SCHEMA))
    mutate(current)
    assert _check(BASE_SCHEMA, current)['ok']


def test_added_contract_is_allowed():
    result = contract.check_compatibility(
        {'demo': _contract(BASE_SCHEMA)},
        {'demo': _contract(BASE_SCHEMA), 'new': _contract(BASE_SCHEMA, path='/api/new')})
    assert result['ok']
    assert result['added'] == ['new']


def test_removed_contract_is_breaking():
    result = contract.check_compatibility(
        {'demo': _contract(BASE_SCHEMA), 'old': _contract(BASE_SCHEMA)},
        {'demo': _contract(BASE_SCHEMA)})
    assert not result['ok']
    assert 'old' in result['removed']


def test_render_terminal_lists_issues():
    current = json.loads(json.dumps(BASE_SCHEMA))
    current['properties'].pop('code')
    text = contract.render_terminal(_check(BASE_SCHEMA, current))
    assert '破坏性变更' in text
    assert '删除字段 code' in text


# ---------- CLI 门禁 ----------

def test_cli_validate(tmp_path, capsys):
    path = _write(tmp_path, {'demo': _contract(BASE_SCHEMA)})
    assert contract.main(['validate', '--file', str(path)]) == 0
    assert '1 条契约' in capsys.readouterr().out


def test_cli_check_ok(tmp_path, capsys):
    path = _write(tmp_path, {'demo': _contract(BASE_SCHEMA)})
    assert contract.main(['check', '--current', str(path), '--baseline', str(path)]) == 0
    assert '兼容性检查通过' in capsys.readouterr().out


def test_cli_check_breaking_returns_one(tmp_path, capsys):
    base = _write(tmp_path / 'base', {'demo': _contract(BASE_SCHEMA)})
    current = json.loads(json.dumps(BASE_SCHEMA))
    current['properties'].pop('code')
    new = _write(tmp_path / 'new', {'demo': _contract(current)})
    assert contract.main(['check', '--current', str(new), '--baseline', str(base)]) == 1
    assert '删除字段' in capsys.readouterr().out


def test_cli_missing_baseline_returns_two(tmp_path, capsys):
    path = _write(tmp_path, {'demo': _contract(BASE_SCHEMA)})
    assert contract.main(['check', '--current', str(path),
                          '--baseline', str(tmp_path / 'missing.yaml')]) == 2
    assert '基线读取失败' in capsys.readouterr().out

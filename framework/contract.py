# -*- coding: utf-8 -*-
"""契约外置与双向校验（framework 内核）。

契约从测试用例/数据集中独立出来，成为服务方与消费方共用的 YAML 资产：

1. **消费方校验**：运行时按契约校验真实响应（``assert_contract``）；
2. **提供方门禁**：提交前对比基线契约，拦截破坏性变更
   （``check_compatibility`` / ``python -m framework.contract check``）。

契约文件格式::

    version: 1
    project: shopping
    contracts:
      health:                       # 契约名（用例按名字引用）
        method: GET                 # 接口标识，便于服务方定位
        path: /api/health
        token: null                 # 可选：鉴权角色，仅作说明
        response:                   # JSON Schema Draft 7，校验整个响应体
          type: object
          required: [code, data]
          properties:
            code: {type: integer}
            data: {type: object}

**破坏性变更**（提供方门禁拦截）：
- 删除字段 / 删除数组元素约束
- 字段类型改变
- 新增必填字段（required 增加）
- 约束收紧（minimum / minLength / minItems 变大，maximum / maxLength / maxItems 变小）
- const 改变、enum 缩小、新增或改变 pattern

**放行**：新增可选字段、移除必填约束、约束放宽。
这样服务方加字段不会被误判为破坏，但删字段/改类型会立刻暴露。

只描述"结构"，不替代业务断言；不依赖 pytest，CLI 可在任意环境跑。
"""
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft7Validator
from jsonschema.exceptions import SchemaError

from framework.schema import assert_schema

DEFAULT_FILE = 'contracts/contracts.yaml'

# 收紧方向：键 -> 'up' 表示数值变大即收紧，'down' 表示变小即收紧
_TIGHTEN_UP = ('minimum', 'exclusiveMinimum', 'minLength', 'minItems',
               'minProperties', 'uniqueItems')
_TIGHTEN_DOWN = ('maximum', 'exclusiveMaximum', 'maxLength', 'maxItems',
                 'maxProperties')


def load_contracts(path: str | Path | None = None) -> dict[str, Any]:
    """加载契约文件并做结构自检；返回 ``contracts`` 映射。

    ``path`` 缺省为工作区下的 ``contracts/contracts.yaml``。
    校验失败抛 ``ValueError``，信息含具体契约名与字段，避免 CI 只看到笼统报错。
    """
    target = Path(path) if path else Path(DEFAULT_FILE)
    with target.open(encoding='utf-8') as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError('契约文件顶层必须是映射：%s' % target)
    if data.get('version') != 1:
        raise ValueError('契约文件 version 必须为 1（当前 %r）' % data.get('version'))

    contracts = data.get('contracts')
    if not isinstance(contracts, dict) or not contracts:
        raise ValueError('契约文件必须包含非空 contracts 映射：%s' % target)

    for name, contract in contracts.items():
        label = '契约 %r' % name
        if not isinstance(contract, dict):
            raise ValueError('%s 必须是映射' % label)
        for field in ('method', 'path', 'response'):
            if field not in contract:
                raise ValueError('%s 缺少字段 %s' % (label, field))
        if not isinstance(contract['method'], str) or not contract['method'].strip():
            raise ValueError('%s 的 method 必须是非空字符串' % label)
        path_value = contract['path']
        if not isinstance(path_value, str) or not path_value.startswith('/'):
            raise ValueError('%s 的 path 必须以 / 开头（当前 %r）' % (label, path_value))
        schema = contract['response']
        if not isinstance(schema, dict):
            raise ValueError('%s 的 response 必须是 JSON Schema 映射' % label)
        try:
            Draft7Validator.check_schema(schema)
        except SchemaError as exc:
            raise ValueError('%s 的 response 不是合法 JSON Schema：%s'
                             % (label, exc.message)) from exc
    return contracts


def get_contract(contracts: dict[str, Any], name: str) -> dict[str, Any]:
    """按名称取契约，缺失时列出可用名称。"""
    try:
        value = contracts[name]
    except (KeyError, TypeError):
        raise KeyError('契约 %r 未定义；可选：%s'
                       % (name, sorted(contracts) if isinstance(contracts, dict) else []))
    if not isinstance(value, dict):
        raise TypeError('契约 %r 必须是映射' % name)
    return value


def assert_contract(result, contract: dict[str, Any], *, label: str = '') -> None:
    """用契约的 response schema 校验响应体；失败抛 AssertionError。

    复用 ``framework.schema.assert_schema`` 的错误定位（字段路径 + 响应体），
    因此契约外置不改变既有失败信息质量。
    """
    schema = contract.get('response') if isinstance(contract, dict) else None
    if not isinstance(schema, dict):
        raise TypeError('契约必须含 response schema（映射），收到 %s'
                        % type(contract).__name__)
    assert_schema(result, schema, label=label or contract.get('name', 'contract'))


def _compare(old: Any, new: Any, path: str, issues: list[str]) -> None:
    """递归对比两份 JSON Schema，把破坏性变更写进 ``issues``。"""
    if not isinstance(old, dict) or not isinstance(new, dict):
        if old != new:
            issues.append('%s: 约束由 %r 变为 %r' % (path, old, new))
        return

    old_type = old.get('type')
    new_type = new.get('type')
    if old_type != new_type:
        issues.append('%s: 类型由 %r 改为 %r' % (path, old_type, new_type))

    old_required = set(old.get('required') or [])
    new_required = set(new.get('required') or [])
    added = sorted(new_required - old_required)
    if added:
        issues.append('%s: 新增必填字段 %s' % (path, ', '.join(added)))

    old_props = old.get('properties') or {}
    new_props = new.get('properties') or {}
    if isinstance(old_props, dict) and isinstance(new_props, dict):
        removed = sorted(set(old_props) - set(new_props))
        if removed:
            issues.append('%s: 删除字段 %s' % (path, ', '.join(removed)))
        for key in sorted(set(old_props) & set(new_props)):
            _compare(old_props[key], new_props[key], '%s.%s' % (path, key), issues)
    elif old_props != new_props:
        issues.append('%s: 字段定义结构变化' % path)

    old_items, new_items = old.get('items'), new.get('items')
    if old_items is not None:
        if new_items is None:
            issues.append('%s: 删除数组元素约束' % path)
        else:
            _compare(old_items, new_items, '%s[]' % path, issues)

    for key in _TIGHTEN_UP:
        if key in old and isinstance(old[key], (int, float)):
            if not isinstance(new.get(key), (int, float)) or new[key] > old[key]:
                issues.append('%s: %s 收紧（%s → %s）'
                              % (path, key, old[key], new.get(key)))
    for key in _TIGHTEN_DOWN:
        if key in old and isinstance(old[key], (int, float)):
            if not isinstance(new.get(key), (int, float)) or new[key] < old[key]:
                issues.append('%s: %s 收紧（%s → %s）'
                              % (path, key, old[key], new.get(key)))

    if 'const' in new and old.get('const') != new['const']:
        issues.append('%s: const 由 %r 改为 %r' % (path, old.get('const'), new['const']))

    if isinstance(old.get('enum'), list):
        old_enum = {repr(item) for item in old['enum']}
        new_enum = ({repr(item) for item in new['enum']}
                    if isinstance(new.get('enum'), list) else set())
        if not old_enum.issubset(new_enum):
            issues.append('%s: enum 缩小（%s → %s）'
                          % (path, old['enum'], new.get('enum')))
    elif isinstance(new.get('enum'), list):
        issues.append('%s: 新增 enum 约束 %s' % (path, new['enum']))

    if new.get('pattern') and old.get('pattern') != new['pattern']:
        issues.append('%s: pattern 由 %r 改为 %r'
                      % (path, old.get('pattern'), new['pattern']))

    if old.get('additionalProperties') is not False and new.get('additionalProperties') is False:
        issues.append('%s: 新增 additionalProperties=false（拒绝未知字段）' % path)


def check_compatibility(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """对比基线与当前契约，返回破坏性变更报告。

    新增契约不算破坏（服务方新增接口）；删除契约算破坏（消费方还在用）。
    """
    issues: list[str] = []
    base_names = set(baseline)
    current_names = set(current)

    for name in sorted(base_names - current_names):
        issues.append('契约 %s: 已删除' % name)
    for name in sorted(base_names & current_names):
        old_response = (baseline[name].get('response') if isinstance(baseline[name], dict)
                        else None)
        new_response = (current[name].get('response') if isinstance(current[name], dict)
                        else None)
        _compare(old_response, new_response, '契约 %s.response' % name, issues)

    return {
        'ok': not issues,
        'baseline_count': len(baseline),
        'current_count': len(current),
        'added': sorted(current_names - base_names),
        'removed': sorted(base_names - current_names),
        'issues': issues,
    }


def render_terminal(report: dict[str, Any]) -> str:
    """终端/CI 日志用的紧凑输出。"""
    lines = [
        '[contract] 基线 %d 条 / 当前 %d 条'
        % (report['baseline_count'], report['current_count'])
    ]
    if report['added']:
        lines.append('[contract] 新增契约 %d 条：%s'
                     % (len(report['added']), ', '.join(report['added'])))
    if report['ok']:
        lines.append('[contract] 兼容性检查通过：无破坏性变更')
    else:
        lines.append('[contract] 发现 %d 处破坏性变更：' % len(report['issues']))
        lines.extend('  - %s' % issue for issue in report['issues'])
    return '\n'.join(lines)


def main(argv=None) -> int:
    """命令行入口：``validate`` 自检契约，``check`` 做提供方兼容性门禁。"""
    import argparse

    parser = argparse.ArgumentParser(prog='python -m framework.contract')
    sub = parser.add_subparsers(dest='command', required=True)

    validate = sub.add_parser('validate', help='校验契约文件格式与 schema 合法性')
    validate.add_argument('--file', default=DEFAULT_FILE, help='契约文件路径')

    check = sub.add_parser('check', help='对比基线与当前契约，拦截破坏性变更')
    check.add_argument('--current', default=DEFAULT_FILE, help='当前契约文件')
    check.add_argument('--baseline', required=True,
                       help='基线契约文件（CI 用 git show HEAD:<path> 生成）')

    args = parser.parse_args(argv)

    try:
        current = load_contracts(args.current if args.command == 'check' else args.file)
    except (OSError, ValueError) as exc:
        print('[contract] 契约读取失败：%s' % exc)
        return 2

    if args.command == 'validate':
        print('[contract] %s 校验通过：%d 条契约'
              % (args.file, len(current)))
        return 0

    try:
        baseline = load_contracts(args.baseline)
    except (OSError, ValueError) as exc:
        print('[contract] 基线读取失败：%s' % exc)
        return 2

    report = check_compatibility(baseline, current)
    print(render_terminal(report))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

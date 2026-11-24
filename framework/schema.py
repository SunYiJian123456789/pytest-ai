# -*- coding: utf-8 -*-
"""响应契约校验（framework 内核）。

用 JSON Schema（Draft 7）描述接口响应结构，检查字段存在性、类型、取值范围。
只验"结构"，不替代业务断言；失败时给出具体路径与完整响应，便于定位。

用法::

    from framework.schema import assert_schema, assert_data_schema

    assert_schema(result, SCHEMAS['health'])           # 校验整个 {code,message,data}
    assert_data_schema(result, SCHEMAS['user_info'])   # 只校验 data 层

schema 可以直接写在 YAML 数据集中，换系统时只改 YAML，不改内核。
"""
from jsonschema import Draft7Validator

from framework.client import ApiResult, shorten


def _path_of(error) -> str:
    parts = [str(p) for p in error.absolute_path]
    # "required" 错误默认指向父对象，补上缺失字段名，定位更精确
    if error.validator == 'required' and isinstance(error.validator_value, (list, tuple)):
        missing = [str(p) for p in error.validator_value
                   if not isinstance(error.instance, dict) or p not in error.instance]
        if missing:
            parts.append(missing[0])
    return '.'.join(parts) or '<root>'


def assert_schema(result: ApiResult, schema: dict, *, label: str = '',
                  root: str = 'payload') -> None:
    """按 schema 校验响应；失败抛 AssertionError，信息含字段路径与完整响应。

    :param result: ApiResult
    :param schema: JSON Schema（Draft 7）字典
    :param label: 用例标签，写入失败信息便于定位
    :param root: ``payload``（整个响应体）或 ``data``（业务数据层）
    """
    if not isinstance(schema, dict):
        raise TypeError('schema 必须是 dict，收到 %s' % type(schema).__name__)
    if root == 'data':
        node = result.data
    else:
        node = result.payload
    if node is None:
        node = {}

    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(node), key=lambda e: list(map(str, e.absolute_path)))
    if not errors:
        return

    lines = []
    for error in errors[:5]:
        lines.append('  - %s: %s' % (_path_of(error), error.message))
    if len(errors) > 5:
        lines.append('  - ...另有 %d 处不符' % (len(errors) - 5))

    raise AssertionError(
        '响应契约不匹配%s (root=%s):\n%s\n响应体: %s'
        % (' [%s]' % label if label else '', root,
           '\n'.join(lines), shorten(result.raw or '', 2000))
    )


def assert_data_schema(result: ApiResult, schema: dict, *, label: str = '') -> None:
    """只校验业务数据层（Envelope.data），适用于各系统通用的 data 契约。"""
    assert_schema(result, schema, label=label, root='data')


def schema_from_yaml(dataset: dict, name: str) -> dict:
    """从 ``load()['response_schemas']`` 中按名称取 schema，找不到给出清晰提示。"""
    try:
        value = dataset[name]
    except (KeyError, TypeError):
        raise KeyError('YAML 中未定义响应契约 %r；可选：%s'
                       % (name, sorted(dataset) if isinstance(dataset, dict) else []))
    if not isinstance(value, dict):
        raise TypeError('响应契约 %r 必须是映射，收到 %s' % (name, type(value).__name__))
    return value


__all__ = ['assert_schema', 'assert_data_schema', 'schema_from_yaml']

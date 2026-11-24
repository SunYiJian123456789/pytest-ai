# -*- coding: utf-8 -*-
"""响应值提取与用例内依赖链上下文（framework 内核）。

解决的问题：上一个接口的返回值要作为下一个请求的参数时，不再散落
``resp.data['id']`` 这类硬编码取值，而是统一按路径提取、失败可定位、
链路可追溯。

设计约束（与 UI 自动化的“流程串联”本质区别）：
- 依赖链只在**单个用例内部**闭环，通过本地变量 / CaseContext 传递；
- 绝不用模块级全局变量或 pytest 用例间依赖，否则无法并行、不能单跑；
- 允许 session 级共享的只有只读前置数据（token、分类 id 等）。

用法::

    created = api.post('/api/orders', json_body=payload, token=token)
    order_id = extract(created, 'data.id')               # 深层字段
    first_id = extract(listed, 'data.list[0].id')        # 数组下标

    ctx.remember('order_id', created, 'data.id')
    api.get(ctx.render('/api/orders/${order_id}'))
"""
import html
import re
from typing import Any

from pytest_html import extras as html_extras

MISSING = object()

# 路径 token：普通字段名或 [数字] 下标；支持可选的 $. 前缀
_TOKEN = re.compile(r'\$\.?|[^.\[\]]+|\[\d+\]')
_PLACEHOLDER = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


def _tokens(path: str) -> list:
    if not isinstance(path, str) or not path.strip():
        raise ValueError('提取路径不能为空')
    parts = []
    for raw in _TOKEN.findall(path.strip()):
        if raw in ('$', '$.'):
            continue  # JSONPath 风格前缀，忽略
        if raw.startswith('[') and raw.endswith(']'):
            parts.append(int(raw[1:-1]))
        else:
            parts.append(raw)
    if not parts:
        raise ValueError('无法解析提取路径：%r' % path)
    return parts


def _is_result(source: Any) -> bool:
    return hasattr(source, 'data') and hasattr(source, 'payload')


def _root(source: Any, parts: list):
    """ApiResult 默认从 data 层解析；data/payload 可显式指定根；普通对象直取。"""
    if _is_result(source):
        if isinstance(parts[0], str) and parts[0] in ('data', 'payload'):
            return getattr(source, parts[0]), parts[1:]
        return source.data, parts  # extract(resp, 'id') 等价于取 data.id
    return source, parts


def _detail(source: Any) -> str:
    raw = getattr(source, 'raw', '')
    if raw:
        return '%r | 响应体: %s' % (source, raw[:600])
    return repr(source)[:800]


def extract(source: Any, path: str, default: Any = MISSING):
    """按点分路径从 ApiResult / dict / list 中提取值。

    - ``data.id``：默认从 ``ApiResult.data``（业务数据层）取；
    - ``payload.data.token``：从原始响应包装层取（如 token 在顶层 data 时）；
    - ``data.list[0].id``：支持数组下标；
    - 传入普通 dict/list 时，路径直接从该对象开始解析。

    提取失败：未给 default 时抛 AssertionError 并带上完整响应；给了则返回 default。
    """
    parts = _tokens(path)
    node, parts = _root(source, parts)
    if not parts:  # extract(resp, 'data') 直接返回整个业务数据层
        return node
    for part in parts:
        if isinstance(part, int):
            if not isinstance(node, (list, tuple)) or part >= len(node):
                return default if default is not MISSING else _fail(path, source, node, part)
            node = node[part]
        else:
            if not isinstance(node, dict) or part not in node:
                return default if default is not MISSING else _fail(path, source, node, part)
            node = node[part]
    return node


def _fail(path, source, node, part):
    keys = sorted(node.keys())[:20] if isinstance(node, dict) else (
        'list[%d]' % len(node) if isinstance(node, (list, tuple)) else type(node).__name__
    )
    raise AssertionError(
        '提取路径 %r 失败：在 %r 处无字段 %r；可用键=%s；来源=%s'
        % (path, node, part, keys, _detail(source))
    )


def extract_many(source: Any, **paths) -> dict:
    """一次提取多个值：``extract_many(r, approval_id='data.id', name='data.name')``。"""
    return {name: extract(source, path) for name, path in paths.items()}


class CaseContext:
    """单个用例内的依赖链上下文（function 作用域，不跨用例共享）。

    ``remember`` 把提取结果记为命名变量，同时写入 pytest-html 报告 extras，
    报告里可直接看到“哪个响应提取了什么值”；``render`` 把 ``${name}``
    占位符替换为已记录的值，可递归处理 dict/list，便于构造下一请求的
    URL、query 或 json_body。
    """

    def __init__(self, extras=None):
        self._values: dict[str, Any] = {}
        self.extras = extras

    def remember(self, name: str, result: Any = MISSING, path: str = '',
                 *, value: Any = MISSING) -> 'CaseContext':
        """记录一个值：``remember('id', resp, 'data.id')`` 或 ``remember('id', value=5)``。"""
        if not isinstance(name, str) or not name:
            raise ValueError('变量名必须是非空字符串')
        if value is not MISSING:
            stored = value
            detail = repr(stored)[:200]
        else:
            if result is MISSING:
                raise ValueError('remember 需要 result+path 或 value 参数')
            stored = extract(result, path)
            detail = repr(stored)[:200]
        self._values[name] = stored
        if self.extras is not None:
            row = ('<div class="enh-ctx"><span class="enh-ctx-key">${%s}</span>'
                   '<span class="enh-ctx-arrow">←</span><code>%s</code></div>'
                   % (html.escape(name), html.escape(detail)))
            self.extras.append(html_extras.html(row))
        return self

    def value(self, name: str, default: Any = MISSING):
        if name in self._values:
            return self._values[name]
        if default is not MISSING:
            return default
        raise KeyError('上下文中没有 %r；已有变量：%s' % (name, sorted(self._values)))

    # 常用短别名，读起来更自然
    get = value

    def render(self, template: Any) -> Any:
        """替换 ``${name}`` 占位符；str 直接替换，dict/list 递归处理。

        占位符独占整个字符串时保留原始类型（如 id 仍是 int，JSON body 不会
        被转成字符串）；嵌入在更长文本中才转为字符串。
        """
        if isinstance(template, str):
            whole = _PLACEHOLDER.fullmatch(template)
            if whole:
                return self.value(whole.group(1))
            return _PLACEHOLDER.sub(
                lambda m: str(self.value(m.group(1))), template
            )
        if isinstance(template, dict):
            return {key: self.render(val) for key, val in template.items()}
        if isinstance(template, (list, tuple)):
            return [self.render(item) for item in template]
        return template

    def as_dict(self) -> dict:
        return dict(self._values)

    def __contains__(self, name: str) -> bool:
        return name in self._values

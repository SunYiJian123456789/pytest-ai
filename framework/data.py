# -*- coding: utf-8 -*-
"""静态用例数据的 YAML 加载器。

与 UI 自动化的 read_excel.py 定位一致：把「可预先写死的参数」外置到
`test_data/api_cases.yaml`，用例通过 `cases(name, *fields)` 拿到
`list[tuple]`，直接交给 `@pytest.mark.parametrize`。

边界：
- 只负责静态数据的读取与校验；token、随机 ID、审批链等运行时状态仍由
  helpers.py / conftest.py 构造，不放进 YAML。
- 字段名必须完整覆盖 parametrize 的参数名，缺字段立即报错，避免用例
  在收集阶段静默使用错误默认值。
"""
from pathlib import Path
from typing import Any

import yaml

from framework.config import workspace_root

# 默认数据集路径；业务项目应通过 file_path 参数指向自己的 data/api_cases.yaml。
# 用函数动态取工作区根，避免 pip 安装后把路径固定在 site-packages。
def _default_data_file() -> Path:
    return workspace_root() / 'test_data' / 'api_cases.yaml'


def load(file_path: str | Path | None = None) -> dict[str, Any]:
    """读取整个 YAML 文件，校验顶层为映射。"""
    path = Path(file_path) if file_path else _default_data_file()
    with path.open(encoding='utf-8') as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError('YAML 顶层必须是映射：%s' % path)
    return data


def records(name: str, file_path: str | Path | None = None) -> list[dict]:
    """取出一个数据集的原始 dict 行列表，适合字段多/可选字段多的场景。

    与 ``cases`` 的区别：``cases`` 按指定字段拆成 tuple 供少量参数解包；
    ``records`` 保留整行 dict，可直接 ``parametrize('row', records(...))``，
    由框架按行解析（如权限矩阵的行含 method/path/期望码等可选字段）。
    """
    data = load(file_path)
    if name not in data:
        raise KeyError('YAML 中缺少数据集 %r；现有：%s' % (name, sorted(data)))
    rows = data[name]
    if not isinstance(rows, list) or not rows:
        raise ValueError('数据集 %r 必须是非空列表' % name)
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError('%s[%d] 必须是映射' % (name, index))
    return rows


def cases(name: str, *fields: str, file_path: str | Path | None = None):
    """取出一个数据集，转成 parametrize 可直接消费的值列表。

    - 单个字段：返回标量列表 `[v1, v2, ...]`，因为 pytest 对单 argname
      不会解包单元素 tuple；若返回 `[(v1,), ...]` 会把 tuple 整体当参数值。
    - 多个字段：返回 tuple 列表 `[(v1, v2), ...]`。

    示例：
        cases('payment_invalid_amounts', 'amount')  -> [0, -1, 'abc']
        cases('cart_requires_login', 'method', 'path', 'extra')
    """
    data = load(file_path)
    if name not in data:
        raise KeyError('YAML 中缺少数据集 %r；现有：%s' % (name, sorted(data)))
    rows = data[name]
    if not isinstance(rows, list) or not rows:
        raise ValueError('数据集 %r 必须是非空列表' % name)
    if not fields:
        raise ValueError('至少指定一个字段名')

    result = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError('%s[%d] 必须是映射' % (name, index))
        missing = [field for field in fields if field not in row]
        if missing:
            raise ValueError('%s[%d] 缺少字段 %s' % (name, index, missing))
        result.append(row[fields[0]] if len(fields) == 1
                      else tuple(row[field] for field in fields))
    return result

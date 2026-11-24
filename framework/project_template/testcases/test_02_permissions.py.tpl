# -*- coding: utf-8 -*-
"""{{PROJECT}} 权限矩阵：角色 × 接口 × 期望结果，由 YAML 数据驱动。

改 YAML 的 permission_matrix 数据集即可增减场景；角色→token 映射在
项目 conftest 的 role_tokens fixture 里配置。断言逻辑在通用内核。
"""
import pytest

from framework.permissions import PermissionRow, check_permission
from projects.{{PROJECT}}.data import records


@pytest.mark.auth
@pytest.mark.parametrize(
    'row',
    records('permission_matrix'),
    ids=lambda row: row.get('label') or '%s_%s' % (row.get('role'), row.get('path')),
)
def test_permission_matrix(api, role_tokens, row):
    case = PermissionRow(row)
    result = check_permission(api, case, role_tokens)
    assert result is not None, case.describe()

# -*- coding: utf-8 -*-
"""登录后权限矩阵：角色 × 接口 × 期望结果，全部由 YAML 数据驱动。

矩阵数据集见 data/api_cases.yaml 的 permission_matrix；
角色→token 映射见 conftest 的 role_tokens fixture；
断言逻辑在 framework.permissions.check_permission（通用内核，无业务耦合）。

覆盖三类场景：
1. 未登录访问：公开接口放行、受保护接口被拒；
2. 角色隔离：用户 token 不能访问管理端、管理 token 不能访问用户端；
3. 管理端内部：不同管理员角色的只读接口放行（写操作权限在各业务用例中验证）。

新增场景只需在 YAML 加一行，不用写 Python 代码。
"""
import pytest

from framework.permissions import PermissionRow, check_permission
from projects.shopping.data import records


@pytest.mark.auth
@pytest.mark.parametrize(
    'row',
    records('permission_matrix'),
    ids=lambda row: row.get('label') or '%s_%s' % (row.get('role'), row.get('path')),
)
def test_permission_matrix(api, role_tokens, row):
    """一行一个权限场景；期望失败时 message_has 可进一步核对拒绝原因。"""
    case = PermissionRow(row)
    result = check_permission(api, case, role_tokens)
    assert result is not None, case.describe()


@pytest.mark.auth
def test_permission_matrix_rejects_unknown_role(api, role_tokens):
    """矩阵引用未定义角色时应明确报错，避免把配置错误误判为接口行为。"""
    row = {'label': '未知角色', 'method': 'GET', 'path': '/api/cart', 'role': 'not_exist'}
    with pytest.raises(KeyError) as exc:
        check_permission(api, row, role_tokens)
    assert 'not_exist' in str(exc.value)

# -*- coding: utf-8 -*-
"""YAML 场景编排的示范入口（能力储备，非 shopping 主流程写法）。

场景定义见 data/scenarios.yaml；断言、提取、清理由 framework.scenario 解释执行，
失败信息带场景名与步骤名。两条场景与专项 Python 用例刻意重叠，用于证明
「新线性链路只加 YAML」的接入方式；主流程仍以下列专项用例为准：

- 商品审批入库 → test_11_admin_approvals.py（自审/驳回/撤回等异常面）
- 购物车加购清空 → test_05_cart.py（越权、独立用户隔离）

需要落库断言、软断言、多身份 client 或负向参数化时请写 Python 用例，
不要把 YAML 引擎当成主流程的替代品。
"""
import pytest

from framework.scenario import run_scenario
from projects.shopping.config import DEFAULT_CATEGORY_ID
from projects.shopping.data import scenarios
from projects.shopping.helpers import register_isolated_user, uid


SCENARIOS = scenarios()


@pytest.fixture
def scenario_user_token(api, cleaner):
    """购物车按 user_id 隔离：每条场景注册独立用户，teardown 由 cleaner 精确删除。"""
    return register_isolated_user(api, cleaner, prefix='APISC')


@pytest.mark.scenario
@pytest.mark.parametrize('name', sorted(SCENARIOS), ids=sorted(SCENARIOS))
def test_scenario(api, cleaner, ctx, role_tokens, scenario_user_token, name):
    """一个场景 = 一个用例；变量经 ctx 传递，场景清理在 teardown 统一执行。"""
    run_scenario(api, cleaner, ctx, SCENARIOS[name], variables={
        'uid': uid(),                      # 场景级唯一串（商品名防并行冲突）
        'user_token': scenario_user_token,
        'admin_token': role_tokens['admin'],
        'reviewer_token': role_tokens['reviewer'],
        'category_id': DEFAULT_CATEGORY_ID,
    })

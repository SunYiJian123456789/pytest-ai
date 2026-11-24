# -*- coding: utf-8 -*-
"""YAML 场景编排：一个 YAML 块描述一条多步业务链路，本文件只是通用入口。

场景定义见 data/scenarios.yaml；断言、提取、清理由 framework.scenario 解释执行，
失败信息带场景名与步骤名。新增场景只加 YAML，不写 Python。
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

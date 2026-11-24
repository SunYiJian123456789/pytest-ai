# -*- coding: utf-8 -*-
"""YAML 场景编排用例：场景定义在 data/scenarios.yaml，本文件只是通用入口。

新增场景只加 YAML（含正向链路、提取、断言、清理），不写 Python；
变量（登录态、场景级唯一串等）由 conftest 的 scenario_variables fixture 提供。
"""
import pytest

from framework.scenario import run_scenario
from projects.{{PROJECT}}.data import scenarios


SCENARIOS = scenarios()


@pytest.mark.scenario
@pytest.mark.parametrize('name', sorted(SCENARIOS), ids=sorted(SCENARIOS))
def test_scenario(api, cleaner, ctx, scenario_variables, name):
    """一个场景 = 一个用例；失败信息带场景名与步骤名，清理在 teardown 统一执行。"""
    run_scenario(api, cleaner, ctx, SCENARIOS[name], variables=scenario_variables)

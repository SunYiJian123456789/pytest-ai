# -*- coding: utf-8 -*-
"""YAML 场景编排用例（能力储备，非主流程默认写法）：本文件只是通用入口。

场景定义在 data/scenarios.yaml，新增「线性正向链路」只加 YAML，不写 Python；
变量（登录态、场景级唯一串等）由 conftest 的 scenario_variables fixture 提供。

引擎刻意只支持请求 → 断言 → 提取 → 下一步的直线链路。负向 / 异常面、
落库断言、软断言、多身份 client、条件分支 / 循环请写 Python 用例，
不要为了「全 YAML」把断言能力降级。
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

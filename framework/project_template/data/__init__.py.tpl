# -*- coding: utf-8 -*-
"""{{PROJECT}} 的 YAML 数据入口；通用加载逻辑在 framework.data / framework.scenario。"""
from pathlib import Path

from framework.data import cases as _cases
from framework.data import load as _load
from framework.data import records as _records
from framework.scenario import load_scenarios as _load_scenarios

DATA_FILE = Path(__file__).resolve().parent / 'api_cases.yaml'
SCENARIO_FILE = Path(__file__).resolve().parent / 'scenarios.yaml'


def cases(name: str, *fields: str, file_path=None):
    return _cases(name, *fields, file_path=file_path or DATA_FILE)


def records(name: str, file_path=None):
    return _records(name, file_path=file_path or DATA_FILE)


def load(file_path=None):
    return _load(file_path or DATA_FILE)


def scenarios():
    """场景编排定义（data/scenarios.yaml），返回 {场景名: ScenarioSpec}。"""
    return _load_scenarios(SCENARIO_FILE)

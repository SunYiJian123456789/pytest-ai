# -*- coding: utf-8 -*-
"""framework：可复用的接口自动化内核。

只依赖 pytest / requests / PyYAML / jsonschema，不含任何业务系统信息。
新系统接入方式见项目根目录 README.md 与 framework/scaffold.py。
"""

from framework.auth import AuthSpec
from framework.client import ApiClient, ApiResult, Envelope
from framework.config import ROOT, Settings, env
from framework.data import cases, load, records
from framework.extract import CaseContext, extract, extract_many
from framework.permissions import PermissionRow, check_permission, run_matrix
from framework.scenario import load_scenarios, run_scenario
from framework.schema import assert_data_schema, assert_schema, schema_from_yaml

__all__ = [
    'ApiClient', 'ApiResult', 'Envelope', 'AuthSpec',
    'ROOT', 'Settings', 'env',
    'cases', 'load', 'records',
    'CaseContext', 'extract', 'extract_many',
    'PermissionRow', 'check_permission', 'run_matrix',
    'load_scenarios', 'run_scenario',
    'assert_schema', 'assert_data_schema', 'schema_from_yaml',
]

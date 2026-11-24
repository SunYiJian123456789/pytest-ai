# -*- coding: utf-8 -*-
"""{{PROJECT}} 项目配置：换系统时主要改这里。"""
from framework.auth import AuthSpec
from framework.config import ROOT, Settings

CFG = Settings('{{PREFIX}}')

BASE_URL = CFG.get('API_BASE_URL', '{{BASE_URL}}').rstrip('/')
TIMEOUT = CFG.floating('API_TIMEOUT', 10.0)

# 鉴权通配：模式/登录路径/字段/token 嵌套路径等全部由 <前缀>AUTH_* 环境变量决定
# 常用模式：bearer | header | cookie | auto | none
AUTH = AuthSpec.from_settings(CFG)
AUTH_USERNAME = CFG.get('USERNAME', 'demo')
AUTH_PASSWORD = CFG.get('PASSWORD', '123456')
SUCCESS_CODE = CFG.integer('SUCCESS_CODE', 200)

# 启动校验：机器相关、没有合理默认值的键，缺失即报错并列出全部缺项，例如：
# CFG.require('API_BASE_URL')

# 报告展示（可选，不配置也能生成报告）
PROJECT_LABEL = '{{PROJECT_UPPER}} · API REGRESSION'
DATA_SOURCE = CFG.get('DATA_SOURCE', '真实数据源')
MODULE_LABELS = {'test_01_smoke.py': '冒烟检查'}
REPORT_NOTES = []

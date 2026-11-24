# -*- coding: utf-8 -*-
"""shopping 项目的业务配置（换系统时只改这一层）。

所有键都通过 framework.Settings('SHOPPING_') 读取，环境变量优先级高于 .env。
机器相关、无合理默认值的键（如 UPLOAD_DIR）用 CFG.require() 启动校验，
缺失即报错并列出全部缺项，绝不静默落到错误默认值。
"""
import os

from framework import AuthSpec
from framework.config import ENV, Settings

CFG = Settings('SHOPPING_')

# 被测服务：Spring Boot 后端（8080），不是 Vite 开发服务器
BASE_URL = CFG.get('API_BASE_URL', 'http://127.0.0.1:8080').rstrip('/')
TIMEOUT = CFG.floating('API_TIMEOUT', 10.0)
# 启动体检的请求超时：体检要快速失败，不跟 10s 业务超时走（后端没起时不让开场卡住）
PREFLIGHT_TIMEOUT = CFG.floating('PREFLIGHT_TIMEOUT', 3.0)

# 鉴权约定：用户端与管理端登录路径不同，各用一份 AuthSpec（闭环示范）
USER_AUTH = AuthSpec.from_settings(CFG)  # SHOPPING_AUTH_* → /api/auth/login
ADMIN_AUTH = AuthSpec.from_settings(CFG, prefix='ADMIN_AUTH_')  # → /api/admin/auth/login
ADMIN_AUTH.login_path = CFG.get('ADMIN_AUTH_LOGIN_PATH', '/api/admin/auth/login')

# 演示账号（与 sql/data.sql 保持一致）
STORE_USERNAME = CFG.get('STORE_USER', 'demo')
STORE_PASSWORD = CFG.get('STORE_PASSWORD', '123456')
ADMIN_ACCOUNTS = {
    'admin': (CFG.get('ADMIN_USER', 'admin'), CFG.get('ADMIN_PASSWORD', 'admin123')),
    'reviewer': (CFG.get('REVIEWER_USER', 'reviewer'), CFG.get('REVIEWER_PASSWORD', 'review123')),
    'operator': (CFG.get('OPERATOR_USER', 'operator'), CFG.get('OPERATOR_PASSWORD', 'op123456')),
}

DATA_PREFIX = CFG.get('API_DATA_PREFIX', 'APIAUTO')

# 支付订单 / 注册用户由接口写入数据库，但没有删除接口，通过数据库直连精确清理。
# 走 PyMySQL 驱动（framework.db），不再依赖 mysql.exe；密码只进连接参数，不进命令行。
MYSQL_HOST = CFG.get('MYSQL_HOST', 'localhost')
MYSQL_PORT = CFG.integer('MYSQL_PORT', 3306)
MYSQL_DATABASE = CFG.get('MYSQL_DATABASE', 'shopping_db')
MYSQL_USER = CFG.get('MYSQL_USER', 'root')
MYSQL_PASSWORD = CFG.get('MYSQL_PASSWORD', '123456')

# 数据库不可用时的策略：CI 环境默认硬失败（不跑出假全绿），本地开发默认跳过落库断言
DB_STRICT = CFG.boolean('DB_STRICT', False) or os.getenv('CI', '').lower() == 'true'

# 上传文件落盘目录（用例结束后删除本轮上传的图片）：机器相关路径，必填
CFG.require('UPLOAD_DIR')
UPLOAD_DIR = CFG.get('UPLOAD_DIR')

# 用于提交商品申请的分类 ID 与默认图片
DEFAULT_CATEGORY_ID = CFG.integer('CATEGORY_ID', 1)
DEFAULT_IMAGE = '/images/product-01.jpg'

REPORT_PATH = 'reports/report.html'

# 报告展示信息：由 conftest 注入 framework.hooks.REPORT_OPTIONS；
# 运行环境（API_ENV）追加在项目标签上，多环境结果一眼可分。
PROJECT_LABEL = 'SHOPPING · API REGRESSION' + (' · %s' % ENV if ENV else '')
DATA_SOURCE = '本地 MySQL（真实数据）'
MODULE_LABELS = {
    'test_01_health.py': '健康与响应结构',
    'test_02_user_auth.py': '用户认证',
    'test_03_catalog.py': '商品浏览',
    'test_04_search.py': '搜索联想',
    'test_05_cart.py': '购物车',
    'test_06_payment.py': '虚拟支付',
    'test_07_admin_auth.py': '管理端登录',
    'test_08_admin_stats.py': '概览统计',
    'test_09_admin_products.py': '商品管理',
    'test_10_admin_categories.py': '分类管理',
    'test_11_admin_approvals.py': '审批流',
    'test_12_upload.py': '图片上传',
    'test_13_permissions.py': '权限矩阵',
    'test_14_contract.py': '响应契约',
    'test_15_scenarios.py': '场景编排',
    'test_16_idor.py': '越权访问（IDOR）',
    'test_17_idempotency.py': '幂等与并发',
    'test_18_auth_negative.py': '鉴权异常输入',
    'test_19_pagination.py': '分页边界',
    'test_20_input_bounds.py': '输入边界与特殊字符',
}
REPORT_NOTES = (
    '后端把多数失败封装为 HTTP 200 + code 400/401/404，因此 HTTP 2xx 数量大于业务成功数量；'
    '4xx / 5xx 由鉴权、路径不存在、缺 multipart 等框架层直接返回，均为负向用例主动触发。'
)

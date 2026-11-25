# 已知缺陷台账（{{PROJECT}} 项目）—— 空台账，等待第一条缺陷
#
# 每条缺陷绑定一个 strict=True 的 xfail 用例。后端修复后请同时做两件事：
#   1) 删除用例上的 @pytest.mark.xfail；
#   2) 把 status 从 open 改为 fixed，并补固定日期/版本。
# CI 门禁：`python -m framework.defects --project {{PROJECT}} --check`
# 双向校验：台账 open 但用例无 xfail / 台账 fixed 但标记还在 / reason 缺缺陷号，
# 任一处遗漏都会失败。本文件由 conftest 的 defects.configure() 自动加载。
#
# 登记示例（取消注释并按实际情况填写）：
#   - id: DEF-001
#     test: projects/{{PROJECT}}/testcases/test_09_products.py::test_bad_input_returns_500
#     status: open
#     title: 非法输入触发未处理异常
#     symptom: >-
#       具体输入与实测响应（HTTP 状态 / code / 关键字段）。
#     expected: 客户端错误应返回 400 业务码与统一错误信封。
#     endpoint: POST /api/xxx
#     severity: medium
#     discovered: 2026-01-01
#     owner: backend
#
# 字段说明：
#   id          缺陷编号（DEF-001 格式），必须出现在 xfail 的 reason 里，如
#               @pytest.mark.xfail(reason='[DEF-001] ...', strict=True)
#   test        完整 pytest nodeid（文件::用例）
#   status      open=缺陷存在且用例带 xfail；fixed=已修复且用例无 xfail
#   title       一句话标题
#   symptom     实测现象（含关键边界值）
#   expected    正确行为（用例的断言目标）
#   endpoint    对应后端接口
#   severity    high / medium / low
#   discovered  发现日期
#   owner       责任侧（backend / frontend / ops）
#   fixed_date  修复日期（status=fixed 时填写）
version: 1
project: {{PROJECT}}
defects: []

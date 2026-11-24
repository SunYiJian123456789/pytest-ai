# {{PROJECT}} 接口清单 —— 覆盖率基准
#
# 覆盖率由运行期真实请求统计（framework.coverage），不是按下面的 covered_by 推断。
# 新增接口时在这里登记一行，跑完看 reports/api_coverage.md 是否有「未覆盖」。
#
# 字段：method / path（动态段用 {id}，静态文件名用 {file}）/ group / name / covered_by
version: 1

endpoints:
  - method: GET
    path: /api/health
    group: 公开
    name: 健康检查
    covered_by: [test_01_smoke.py]

  - method: POST
    path: /api/auth/login
    group: 公开
    name: 登录
    covered_by: [test_01_smoke.py]

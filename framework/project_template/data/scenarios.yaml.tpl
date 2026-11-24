# {{PROJECT}} 场景编排：一个 YAML 块描述一条多步业务链路，无需写 Python。
# 用例入口在 testcases/test_04_scenarios.py（按场景名参数化，内核解释执行）。
#
# 规则速查：
#   steps[].request: {method, path, params, body, token, headers}；值可含 ${变量}
#   steps[].extract: {变量: 提取路径}（默认从业务 data 层提取，支持 data.list[0].id）
#   steps[].assert:  {ok, http, code, message_has, schema, data_schema}；缺省 = 期望业务成功
#   cleanup:         用例结束统一执行（步骤失败也执行）；ignore_missing: 目标不存在视为成功
#   变量来源:        conftest 的 scenario_variables fixture → 本文件 vars → 步骤 extract
scenarios:
  - name: 健康检查与登录态
    steps:
      - step: 服务健康
        request: {method: GET, path: /api/health}
      - step: 登录态访问个人信息
        request: {method: GET, path: /api/auth/me, token: '${token}'}
        assert: {ok: true}

  # ---- 完整能力示例（创建 → 校验 → 清理，按真实接口改造后取消注释）----
  # - name: 资源创建-校验-清理
  #   vars: {res_name: 'SCEN-${uid}'}
  #   steps:
  #     - step: 创建资源并记住 ID
  #       request:
  #         method: POST
  #         path: /api/items
  #         body: {name: '${res_name}'}
  #       extract: {item_id: data.id}
  #     - step: 详情可查且结构正确
  #       request:
  #         method: GET
  #         path: '/api/items/${item_id}'
  #       assert: {ok: true, data_schema: {type: object, required: [id, name]}}
  #   cleanup:
  #     - method: DELETE
  #       path: '/api/items/${item_id}'
  #       ignore_missing: true

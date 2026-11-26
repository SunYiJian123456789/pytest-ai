# {{PROJECT}} 响应契约：服务方与消费方共用的结构约定（可选，建议启用）。
#
# 消费方：用例用 framework.contract.assert_contract 按契约校验真实响应。
# 提供方：CI 与上一版契约对比，删字段/改类型/加必填/收紧约束直接失败；
#         新增可选字段、放宽约束放行。
#
# 每条契约必须有 method / path / response（JSON Schema Draft 7）。
# token 字段仅作说明（需哪种角色），不参与校验；用例自己决定用哪个 token。
version: 1
project: {{PROJECT}}
contracts:
  health:
    method: GET
    path: /api/health
    token: null
    response:
      type: object
      required: [code, data]
      properties:
        code: {type: integer}
        data:
          type: object
          required: [status]
          properties:
            status: {type: string}

  # 按接口继续添加，例如：
  # user_me:
  #   method: GET
  #   path: /api/auth/me
  #   token: user
  #   response:
  #     type: object
  #     required: [code, data]
  #     properties:
  #       code: {type: integer}
  #       data: {type: object, required: [id], properties: {id: {type: integer}}}

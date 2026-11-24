# {{PROJECT}} 静态用例数据；新增一行即新增一条参数化用例
smoke_paths:
  - path: /api/health
  - path: /api/products
  - path: /api/categories

invalid_ids:
  - id: 0
  - id: -1
  - id: abc

# 权限矩阵：每个角色对接口的访问期望，新增一行即新增一条权限用例。
# role 取自项目 conftest 的 role_tokens fixture；anonymous 表示不带 token。
permission_matrix:
  - label: 匿名访问公开接口放行
    role: anonymous
    method: GET
    path: /api/health
    expect_http: 200
    expect_code: 200

# 响应契约：JSON Schema Draft 7，新增一个 key 即新增一条契约用例。
# 结构不符时报告会指出具体字段路径与完整响应体。
response_schemas:
  health:
    type: object
    required: [code, data]
    properties:
      code: {type: integer}
      data: {type: object}

# 契约用例场景：name 对应上面的 response_schemas key
response_schemas_cases:
  - name: health
    path: /api/health

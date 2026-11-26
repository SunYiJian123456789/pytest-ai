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

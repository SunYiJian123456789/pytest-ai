# 被测系统 Swagger / OpenAPI 导出说明

## 背景：被测系统没有 Swagger

`shopping-backend`（Spring Boot + MyBatis）**未集成 Swagger / springdoc / knife4j**：

- `pom.xml` 无 `springdoc-openapi` / `springfox-swagger` 依赖；
- 41 个 Java 源文件里零 Swagger 注解（`@Operation` / `@Tag` 等）；
- `application.yml` 无相关配置；
- 服务运行中也不暴露 `/v3/api-docs` / `/swagger-ui.html`。

因此**无法从运行服务导出 Swagger**。若确实需要运行时 Swagger，需在被测系统加依赖
`springdoc-openapi-starter-webmvc-ui` 并重启服务，再访问 `http://127.0.0.1:8080/v3/api-docs`。

## 采用方案：从 Spring MVC 注解反向生成

Controller 用了标准注解（`@RestController` / `@RequestMapping` / `@GetMapping` 等），
可静态解析源码生成 OpenAPI 3.0 文档。工具：`tools/gen_openapi.py`。

```bash
python tools/gen_openapi.py \
  --src D:/shopping/backend/src/main/java \
  --out projects/shopping/data/openapi.json \
  --base-url http://127.0.0.1:8080 \
  --title "Shopping API"
```

生成结果：`projects/shopping/data/openapi.json`（35 个 path / 42 个 operation）。
被测系统源码升级后重跑该命令即可刷新。

## 交叉核对：与框架接口清单一致

把生成的 OpenAPI 与 `projects/shopping/data/api_inventory.yaml` 交叉比对：

| 项 | 数量 | 结论 |
| --- | --- | --- |
| OpenAPI operations（源码注解） | 42 | — |
| api_inventory.yaml 接口 | 43 | — |
| 源码有、清单未登记 | **0** | 清单完整覆盖所有 Controller 接口 |
| 清单有、源码注解无 | 1 | `GET /images/{file}`，静态图片路由（非 Spring MVC 注解），合理差异 |

这印证了框架接口清单的完整性：43 条 = 42 条 Controller 接口 + 1 条静态资源路由。

## 能力边界（务必看清）

源码反向生成**不等于真实 Swagger**，它以静态推导代替运行时契约，局限如下：

1. **请求/响应 body 只有结构层级**：输出 `Result` 信封（code/message/data）+ Java 类型
   映射（Long→int64、List→array 等），无法推导字段级 schema、枚举值、约束、示例值。
2. **字段级契约以 `contracts.yaml` 为准**：框架 `projects/shopping/data/contracts.yaml`
   才是权威的响应契约（JSON Schema Draft 7），消费方校验与提供方 CI 门禁都基于它。
3. **无鉴权/错误码描述**：注解里没有这些信息，需在接入时从接口文档或抓包补充。
4. **摘要依赖 Javadoc**：仅紧邻方法的注释会被提取（本轮 5 条），无注释的方法摘要为空。

## 接入新系统时的用法

拿一个新系统做接口自动化时，Swagger/OpenAPI 的价值是**快速列出接口清单**：

- 若被测系统有 Swagger：直接访问 `/v3/api-docs` 导出 JSON，按 method+path 整理进
  `data/api_inventory.yaml`，作为覆盖率门禁基准；
- 若像 shopping 一样没有：用 `tools/gen_openapi.py` 从源码反向生成，再做一次与清单的
  交叉核对（源码有而清单无 = 漏登记，清单有而源码无 = 需确认是否静态路由/已下线）。

接口清单只是骨架；账号、鉴权方式、响应包装、数据集、权限矩阵、契约仍需按
`docs/新系统接入指南.md` 补齐。

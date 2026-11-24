# 接口自动化测试框架（pytest + requests）

本工程已改造为 **通用内核 + 业务项目** 两层结构：

- `framework/`：与被测系统无关的测试内核（请求、断言、数据驱动、清理、报告、脚手架）。
- `projects/shopping/`：现成的 shopping 电商系统用例，118 条全绿，作为接入范例。
- 换一个系统时只新增 `projects/<项目名>/`，改配置和用例，**framework 代码不动**。

## 1. 目录结构

```text
D:/shopping-api-automation/
├── framework/                       通用内核（不依赖任何业务系统）
│   ├── config.py                    env/.env 加载器 + Settings(prefix)
│   ├── client.py                    ApiClient / ApiResult / Envelope 响应包装适配
│   ├── assertions.py                通用断言库（assert_ok / assert_code / ...）
│   ├── data.py                      YAML 数据加载与 parametrize 转换
│   ├── db.py                        SQL 执行器（结构化结果、密码不进命令行）
│   ├── cleanup.py                   注册式清理器 + 清理汇总横幅
│   ├── hooks.py                     通用 pytest 钩子 + 报告选项注入
│   ├── reporting/                   仪表盘报告增强（enhancer.py / assets.py）
│   ├── scaffold.py                  新项目脚手架：python -m framework.scaffold
│   └── project_template/            脚手架模板
├── projects/
│   ├── shopping/                    shopping 业务层（138 条用例）
│   │   ├── config.py                账号、库表、路径、报告标签
│   │   ├── conftest.py              api / tokens / cleaner fixtures
│   │   ├── helpers.py               商品构造、独立用户、落库断言
│   │   ├── dbclean.py               shopping 业务 SQL
│   │   ├── data.py + data/          YAML 入口与 11 组数据集（含权限矩阵、响应契约）
│   │   ├── testcases/               14 个测试模块
│   │   └── docs/接口清单.md          接口与用例对照
│   └── <新项目>/                    由脚手架生成，按配置接入
├── conftest.py                      根 conftest：仅挂载 framework 通用钩子
├── pytest.ini                       默认 testpaths = projects/shopping/testcases
├── .env.example / .env / requirements.txt / requirements-dev.txt / run.bat
├── pyproject.toml                   ruff 静态检查配置（工程门禁）
├── config.py, client.py, read_yaml.py, dbclean.py,
│   helpers.py, report_enhancer.py, report_assets.py   根目录薄兼容层（re-export）
└── reports/                         report.html + junit.xml + run_summary.json
    └── archive/                     按时间戳归档的历史报告（默认保留 30 份）
```

## 2. 运行环境与快速开始

| 项 | 要求 |
| --- | --- |
| Python | 3.10+（本机验证 3.12.7） |
| pytest / pytest-html / requests / PyYAML / pytest-xdist / jsonschema / PyMySQL | 见 `requirements.txt`（版本已锁定）；ruff 见 `requirements-dev.txt` |
| shopping 被测服务 | Spring Boot `127.0.0.1:8080` + MySQL 8 `shopping_db`（PyMySQL 驱动直连，不再依赖 mysql.exe） |

```bash
pip install -r requirements.txt
python -m pytest                       # 默认跑 shopping 项目
python -m pytest -n 4                  # 并行，已验证隔离
python -m pytest -m smoke              # 按 marker 过滤
run.bat                                # Windows 一键执行
```

切项目：`set API_PROJECT=order_system && run.bat`，或
`python -m pytest -o testpaths=projects/order_system/testcases`。

## 3. 新系统接入（只需改配置）

> 完整操作手册（信息收集清单、逐项落地、用例规范、验收清单、已知边界）见 **[docs/新系统接入指南.md](docs/新系统接入指南.md)**。

```bash
python -m framework.scaffold order_system --base-url http://127.0.0.1:9000 --prefix ORDER_
```

生成后按需修改 4 处：

1. `projects/order_system/config.py`：登录路径 `AUTH_LOGIN_PATH`、账号、`SUCCESS_CODE`、模块标签。
2. `.env`：按 `ORDER_` 前缀填 `ORDER_API_BASE_URL`、`ORDER_USERNAME` 等。
3. `projects/order_system/data/api_cases.yaml`：按真实场景增删数据集（含 `permission_matrix`）。
4. `projects/order_system/conftest.py` 的 `role_tokens`：按真实角色增减键；
   `test_02_permissions.py` 的示例矩阵按真实权限调整。

运行：`python -m pytest -o testpaths=projects/order_system/testcases`。
脚手架已生成 `data/` 包（内置 `cases`/`records`/`load`/`scenarios`）与
`ctx`/`role_tokens`/`scenario_variables` fixtures，生成 9 条示例用例可收集运行。

### 需要适配的四种差异

| 差异 | 改哪里 |
| --- | --- |
| 响应不是 `{code,message,data}` | 在项目的 `conftest.py` 里配置 `Envelope(code_key=..., code_path=..., success_code=...)`，换包装不改内核 |
| 鉴权方式不同（Header / Cookie / 嵌套 token） | 只改 `.env` 的 `前缀AUTH_*` 变量，`AuthSpec` 自动适配，无需改代码 |
| 清理动作不同 | `cleaner.register('动作名', lambda: api.delete(...))`，框架统一执行并写入报告 |
| 报告要显示项目信息 | `hooks.configure_report(project_label=..., module_labels=..., data_source=...)` |

### 登录后权限矩阵（permissions）

`framework/permissions.py` 把"角色 × 接口 × 期望结果"收敛成一份 YAML 矩阵：
业务层只需提供 `role_tokens` fixture（角色→token 映射）和 YAML 数据，
断言逻辑、失败信息、角色解析全部由内核负责，不认识任何业务角色名。

```yaml
permission_matrix:
  - label: 匿名访问管理端商品被拒
    role: anonymous          # 不带 token
    method: GET
    path: /api/admin/products
    expect_http: 401         # 可选：HTTP 状态断言
    expect_code: 401         # 可选：业务 code 断言
    message_has: 管理端未登录  # 可选：消息包含
  - label: 用户访问管理端被拒
    role: user               # role_tokens['user'] 的 token
    method: GET
    path: /api/admin/products
    expect_http: 401
```

新增场景只加一行 YAML，不写 Python。`token_from: user_b` 可指向另一角色的 token，
用于"用 A 的凭证访问 B 的资源"这类跨用户场景。shopping 有 14 条矩阵用例
（`test_13_permissions.py`），内核单测见 `framework/tests/`。

### 鉴权通配（AuthSpec）

`framework/auth.py` 用一份配置描述所有登录与鉴权差异，脚手架模板的 `conftest.py` 已接好，
换系统时只改 `.env`，不用改 Python：

| 环境变量（`<前缀>` 如 `SHOPPING_` / `ORDER_`） | 默认值 | 说明 |
| --- | --- | --- |
| `<前缀>AUTH_MODE` | `bearer` | `bearer` / `header` / `cookie` / `auto` / `none` |
| `<前缀>AUTH_LOGIN_PATH` | `/api/auth/login` | 登录接口路径 |
| `<前缀>AUTH_USERNAME_FIELD` / `AUTH_PASSWORD_FIELD` | `username` / `password` | 登录请求体字段名 |
| `<前缀>AUTH_TOKEN_FIELD` / `AUTH_TOKEN_PATH` | `token` / 空 | token 位置，支持 `data.access_token` 嵌套路径 |
| `<前缀>AUTH_HEADER` / `AUTH_SCHEME` | `Authorization` / `Bearer` | 请求头名与前缀；scheme 留空则原样发送 |
| `<前缀>AUTH_COOKIE_NAME` | 空 | Cookie 模式下关心的 cookie 名 |

`auto` 模式登录后自动探测：能提取到 token 就走 header，否则有 Cookie 就走 cookie。
显式传 `token=` 的调用始终优先注入请求头，因此 shopping 现有 118 条业务用例无需改动。

### 重试与链路追踪

请求层通用配置（无前缀，所有项目共享；全部可通过环境变量覆盖，无需改代码）：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `API_RETRY_ENABLED` | `1` | `0` 关闭重试 |
| `API_MAX_RETRIES` | `1` | 额外重试次数 |
| `API_RETRY_BACKOFF` | `0.2` | 退避基数秒，第 n 次等待 n×backoff |
| `API_RETRY_STATUSES` | `429,500,502,503,504` | 触发重试的 HTTP 状态 |
| `API_TRACE_ENABLED` | `1` | 每次请求生成链路 ID 并注入请求头 |
| `API_TRACE_HEADER` | `X-Trace-Id` | 链路 ID 的请求头名 |

只对**幂等方法**（GET/HEAD/OPTIONS/PUT/DELETE）且**网络异常或指定 HTTP 状态**重试；
业务失败被包成 `HTTP 200 + code≠200` 时不重试，负向用例结果保持原样。
同一逻辑请求的重试共享一个 trace_id，并写入报告明细与失败请求存档，便于跨服务定位。

### 响应契约校验

`framework/schema.py` 用 JSON Schema（Draft 7）校验响应结构，结构写在 YAML 的
`response_schemas`，新增一个 key 即新增一条契约用例；字段缺失/类型错误会指出精确路径
（如 `data.not_exists`）并附完整响应体。`assert_schema(result, schema)` 校验整个响应，
`assert_data_schema(result, schema)` 只校验业务数据层。

## 4. framework 内核能力

| 模块 | 能力 |
| --- | --- |
| `config.py` | 环境变量 > `.env` > 默认值；`Settings(prefix)` 支持多项目共存 |
| `client.py` | 统一请求/计时/响应解析、慢请求高亮、敏感字段脱敏（password/token 等键值掩码，报告与断言消息全覆盖）、失败请求存档、幂等方法重试、trace_id 链路追踪 |
| `assertions.py` | `assert_ok/assert_status/assert_code/assert_message_contains/assert_fields/assert_numeric_fields/assert_contains_row` 等，失败信息带 URL 与 code |
| `data.py` | YAML 数据集校验、单字段返回标量列表、多字段返回 tuple，直接喂给 `parametrize` |
| `extract.py` | 响应值提取与用例内依赖链：`extract` 点分路径 + 数组下标，`CaseContext` 记录变量并渲染 `${name}` 占位符 |
| `schema.py` | 响应契约校验（JSON Schema Draft 7）：校验字段存在性/类型/范围，失败定位到具体路径并附完整响应 |
| `scenario.py` | YAML 场景编排：一个 YAML 块描述多步业务链路（request/extract/assert/cleanup），`${}` 变量链与类型保持复用 extract/CaseContext，未知字段即报错，清理进报告汇总——正向链路用例不再必须写 Python |
| `db.py` | PyMySQL 驱动直连、真参数绑定（`%s` 占位符）、线程本地连接复用、结构化 `records` 行、驱动缺失自动 SKIP、`strict` 模式（CI 数据库不可用直接失败） |
| `cleanup.py` | 清理动作注册化、顺序执行、成功/跳过/失败汇总注入报告 |
| `reporting/` | pytest-html 之上的仪表盘：KPI、模块分布、TOP 接口、HTTP/业务双层状态、请求明细 |
| `hooks.py` | collect-only 不覆盖正式报告、报告标题、报告增强与降级提示 |
| `scaffold.py` | 一键生成新项目骨架，占位符自动替换 |

### 响应值提取与依赖链（跨步骤传参）

上一个接口的返回值作为下一个请求参数时，依赖链必须在**单个用例内部**闭环，
绝不用模块级全局变量或用例间依赖，否则无法单跑、无法并行。

```python
from framework import extract

submitted = api.post('/api/admin/products', json_body=payload, token=admin)
approval_id = extract(submitted, 'data.id')       # 默认从业务数据层提取
first_id = extract(listed, 'data.list[0].id')     # 支持数组下标
token = extract(resp, 'payload.data.token')       # 从原始包装层提取
```

`extract` 默认以 `ApiResult.data`（业务数据层）为根；显式写 `data.` / `payload.`
可切换根；也接受裸 dict/list。路径不存在时抛 AssertionError 并带上完整响应体，
传 `default=` 则返回值兜底。

需要把多个值串起来、或让 YAML 风格的占位符参与构造时，用 function 作用域的
`ctx` fixture（脚手架模板已自带）：

```python
def test_chain(api, tokens, cleaner, ctx):
    created = create_product(api, tokens, cleaner, name, ctx=ctx)
    ctx.remember('new_name', value=name + '-已修改')
    payload = ctx.render(dict(created['payload'], name='${new_name}'))
    result = api.put(ctx.render('/api/admin/products/${product_id}'),
                     json_body=payload, token=tokens['admin'])
```

- `ctx.remember('id', resp, 'data.id')` 或 `ctx.remember('id', value=5)` 记录变量；
  每次记录都会写入报告 extras（`${变量名} ← 值`），链路可追溯。
- `ctx.render()` 递归处理 str/dict/list，替换 `${name}` 占位符。
  **占位符独占字符串时保留原始类型**（id 仍是 int），嵌在更长文本中才转字符串。
- `ctx` 是 function 作用域，每个用例独立，xdist 并行不会串值。

shopping 的 `test_update_product_name` 是完整示范，`helpers.py:create_product`
是固定链路的封装示范（提取 ID 后立即登记 cleaner，中途失败也不留脏数据）。
内核单测：`python -m pytest framework/tests -o addopts= -q`（13 条）。

## 5. shopping 项目现状

### 覆盖范围（140 条，全部通过）

| 模块 | 用例数 | 模块 | 用例数 |
| --- | --- | --- | --- |
| 健康与响应结构 | 5 | 管理端登录 | 14 |
| 用户认证 | 11 | 概览统计 | 6 |
| 商品浏览 | 10 | 商品管理 | 22 |
| 搜索联想 | 6 | 分类管理 | 8 |
| 购物车 | 12 | 审批流 | 10 |
| 虚拟支付 | 11 | 图片上传 | 3 |
| 登录后权限矩阵 | 15 | 响应契约校验 | 5 |
| 场景编排 | 2 | | |

关键断言：`/api/health` 状态 UP、统一响应包装、上下架过滤、¥1000/¥1001 支付边界与订单落库、
用户/管理 token 双向隔离、审批通过后才入库、有商品分类禁止删除、图片上传后可回源。

### 账号与隔离

- 商城用户：`demo / 123456`（`sys_user`）
- 管理员：`admin / admin123`、`reviewer / review123`、`operator / op123456`（`sys_admin`）
- 购物车按 `user_id` 存储，写操作由 `register_isolated_user()` 注册独立用户，用例结束精确删除，可安全并行。
- 临时商品、申请单、分类、购物车、上传图片由 `cleaner` 回收；订单与用户由 `dbclean.py` 直连 MySQL 精确删除；目标已不存在按幂等成功处理。

### 数据驱动

`projects/shopping/data/api_cases.yaml` 共 11 组数据集：注册短账号、未登录接口清单、非法金额、
管理端未登录接口、商品参数校验、上下架状态值、非法状态值、批量状态值、商品表单模板，
以及权限矩阵 `permission_matrix`、响应契约 `response_schemas`。
`cases('数据集名', '字段1', '字段2')` 直接作为 `parametrize` 参数，增删 YAML 行即增减用例；
`records('数据集名')` 保留整行 dict，适合字段多的矩阵场景。

## 6. 报告

`reports/report.html` 是单文件自包含报告，每次执行自动增强：

- KPI 卡与通过率环形图、12 模块分布条形图、TOP 14 接口统计（均耗/峰值/失败数）。
- **双层状态分布**：HTTP 2xx/4xx/5xx 与业务 code 分开统计。shopping 后端把失败封装为
  `HTTP 200 + code 400/401/404`，所以两者口径不同；负向用例主动触发的 4xx/5xx 不代表测试失败。
- 请求明细：方法徽章、HTTP 状态、业务 code、耗时、左右双栏请求/响应，token 脱敏。
- 顶部「测试后清理汇总」：成功/跳过/失败分色，真实失败逐条列明；报告增强失败也会醒目提示。

## 7. 兼容层说明

根目录 `config.py`、`client.py`、`read_yaml.py`、`dbclean.py`、`helpers.py`、
`report_enhancer.py`、`report_assets.py` 现在只是 re-export，**旧 import 路径继续可用**。
新代码建议直接引用 `framework.*` 与 `projects.<项目名>.*`。

迁移前的 `testcases/`、`test_data/`、`docs/` 历史副本已清理；`pytest.ini` 的
`testpaths` 指向 `projects/shopping/testcases`，用例只在业务项目目录维护。

## 8. 分层改造记录（2026-11-22）

- 内核与业务解耦：`Envelope` 适配响应包装，`auth_header/auth_scheme` 适配鉴权，
  报告信息由 `hooks.configure_report` 注入，SQL 表名只留在业务层。
- 清理器改为 `CleanupRegistry.register()` 注册式；业务层只声明动作，框架负责记录与展示。
- 报告增强器去除 `MODULE_LABELS`、`BASE_URL`、`MYSQL_DATABASE`、`SHOPPING` 文案等硬编码，
  全部由选项注入；shopping 的业务说明作为 `notes` 传入。
- 新增脚手架与项目模板，`python -m framework.scaffold` 已验证可生成并收集 6 条示例用例。
- 幂等清理：目标已删除视为清理成功，避免汇总出现假失败。
- xdist 兼容：worker 清理记录落盘、主进程合并，并行报告同样有 73 项清理汇总。
- 并行竞态修复：审批流用例的全局总数下界断言改为「唯一商品名在前台/管理端精确查询」，
  消除与其他用例同时审批/删除商品时的偶发失败。
- 鉴权通配：新增 `framework/auth.py` 的 `AuthSpec`，支持 bearer/header/cookie/auto/none，
  token 兼容顶层与 `data` 层嵌套；脚手架模板已接好，换系统只需配 `<前缀>AUTH_*` 环境变量。
- 回归：串行 `pytest` → 118 passed in 6.19s；`pytest -n 4` 连续验证 118 passed
  （6.9~8.2s）；报告仪表盘、清理横幅、项目标识、模块标签均正常，数据库测试残留 0。

## 9. 企业级补齐记录（2026-11-23）

- **shopping 接入 AuthSpec**：用户端/管理端各用一份 `AuthSpec`（登录路径与 token 位置可配），
  `tokens` fixture 改用 `client.login()` + `last_login` 提取用户信息；账号全部前缀化到 `.env`，
  118 条业务用例零改动。
- **登录后权限矩阵**：新增 `framework/permissions.py`，把"角色 × 接口 × 期望结果"做成 YAML
  数据驱动；`framework/data.py` 增加 `records()`；shopping 新增 14 条矩阵用例 + 1 条配置校验
  （`test_13_permissions.py`），脚手架生成 `role_tokens` fixture 与示例矩阵。
- **CI 分层**：push/PR 跑 `-m smoke -n 4`（7 条快跑），定时/手动触发跑全量 `-n 4`；
  内核单测 `framework/tests` 每次都跑且无需后端。
- **内核单测**：`framework/tests/test_extract.py` 18 条，覆盖响应提取、上下文渲染、
  权限矩阵断言与角色解析，命令 `python -m pytest framework/tests -o addopts= -q`。
- 回归：串行 133 passed（原 118 + 权限 15）；`-n 4` 133 passed；
  数据库商品/用户/申请单残留 0。

## 10. 最后 3 项补齐记录（2026-11-23）
- **请求重试 + trace_id**：`client.py` 只对幂等方法（GET/HEAD/OPTIONS/PUT/DELETE）的
  网络异常与 HTTP 429/5xx 重试，业务 code 失败不重试；每次请求生成 trace_id 注入请求头，
  重试共享同一链路 ID，写入报告明细与失败存档。全部由 `API_*` 环境变量配置。
- **响应契约校验**：新增 `framework/schema.py`（JSON Schema Draft 7），`assert_schema` /
  `assert_data_schema` 校验字段存在性、类型、范围，失败定位到具体路径并附完整响应；
  shopping 新增 5 条契约用例（`test_14_contract.py`），schema 写在 YAML，脚手架同步生成模板。
- **工程细节**：新增本地 `.env`（`API_*` 与 `SHOPPING_*` 全部前缀化，已在 `.gitignore`），
  清理迁移前的 `testcases/`、`test_data/`、`docs/` 历史副本；`requirements.txt` 增加 jsonschema。
- **内核单测**：`framework/tests` 扩到 27 条（提取/上下文/权限 18 + 重试/trace/schema 9）。
- 回归：串行 **138 passed（11.69s）**，`-n 4` **138 passed（8.30s）**，`-m smoke` 7 passed；
  报告 1794 KB、仪表盘正常、提取链路 12 处、清理汇总 73 项全成功；
  数据库商品/用户/申请单残留全 0。

## 11. 企业级四项补齐（2026-11-23）

- **数据库通道**：`framework/db.py` 从「mysql.exe 子进程 + TSV 解析」改为 **PyMySQL 驱动直连**——
  真参数绑定（`execute(sql, params)`，`%s` 占位符，业务 SQL 不再手写转义）、线程本地连接复用
  （ping 重连）、`SqlResult.records` 结构化 dict 行（类型由驱动还原，`rows` 保留 TSV 兼容旧消费方）、
  密码只进连接参数。新增 `strict` 模式：CI（`CI=true` 或 `SHOPPING_DB_STRICT=1`）下数据库
  不可用直接失败，杜绝"基础设施坏了跑出假全绿"；本地默认跳过落库断言。`dbclean.py` 查询
  失败抛 RuntimeError，不再与「查无此行」混淆。
- **敏感信息脱敏**：`client.py` 按「键名」递归掩码（`API_SENSITIVE_KEYS` 可覆盖默认清单：
  password/token/secret 等 11 项）。掩码在 `ApiResult.raw` 构造时统一完成——报告请求体、
  响应体、失败存档、extract/schema 断言失败消息里的响应体全部覆盖。回归确认：报告
  `password` 键 34 次、`token` 键 26 次，全部为 `******`；已知真实口令 0 泄漏。
- **多环境**：进程启动前设置 `API_ENV`（如 test/staging）后先加载 `.env.<API_ENV>`（优先）
  再加载 `.env` 兜底，环境差异只维护差异项；`Settings.require(*names)` 启动校验必填配置，
  一次性列出全部缺项（shopping 的 `UPLOAD_DIR` 已改为必填）。`.env` 解析改用 `utf-8-sig`，
  兼容 Windows 记事本/PowerShell 写出的带 BOM 文件（BOM 曾导致首行键名静默失效）。
  `API_ENV` 同时写入报告项目标签与 `run_summary.json`，多环境结果一眼可分。
- **结果沉淀**：报告按时间戳归档到 `reports/archive/`（保留 `API_REPORT_KEEP` 份，默认 30）；
  每轮运行写 `reports/run_summary.json`（结果计数、环境、耗时、退出码），供外部系统采集趋势；
  `pytest.ini` 增加 `--junitxml=reports/junit.xml` 接入 CI 测试看板；新增 `pyproject.toml`
  （ruff 配置）与 `requirements-dev.txt`，`ruff check .` 通过并加入 CI 门禁（顺手清理了
  全部存量未使用 import）；CI 增加 `SHOPPING_DB_STRICT=1`，产物上传补 junit/summary。
- **内核单测**：`framework/tests` 扩到 **31 条**（新增敏感信息脱敏 4 条：嵌套掩码不改原数据、
  报告明细脱敏、失败消息 raw 脱敏、`API_SENSITIVE_KEYS` 覆盖清单）。
- 回归：串行/-n 4 均 **138 passed（4.35s）**；`run_summary.json` 138/0/4.39s；归档 3 份；
  数据库清理与落库断言全部经 PyMySQL 真连执行，`ruff check .` 全绿。

## 12. 场景编排层（2026-11-23）

- **新增 `framework/scenario.py`**：让正向业务链路用例也 YAML 化——一个 YAML 块描述
  多步链路（`steps[].request/extract/assert` + 场景级 `vars` + `cleanup`），由通用 test
  函数按场景名参数化执行，**新增场景只加 YAML，不写 Python**。积木全部复用：
  请求走 ApiClient（脱敏/重试/trace/报告明细生效），变量链走 extract + CaseContext
  （`${}` 渲染、独占占位符保留类型），断言走 assertions + schema（失败带场景名与步骤名），
  清理走 CleanupRegistry（场景开始即注册，步骤失败 teardown 仍回收，进报告清理汇总，
  `ignore_missing` 幂等）。
- **防笔误设计**：step/request/assert/cleanup 的未知字段一律报错并列出合法键，
  变量名必须是合法标识符；场景重名在加载期报错。
- **模板同步**：脚手架生成 `data/scenarios.yaml`（1 条活跃场景 + 1 条注释完整示例）与
  `testcases/test_04_scenarios.py` 通用入口，conftest 新增 `scenario_variables` fixture
  （`${token}` 登录态 + `${uid}` 场景级唯一串）；生成项目示例用例 6 → 9 条。
- **shopping 实证**：`data/scenarios.yaml` 两条真实链路——「商品审批入库」（提交 → 审批 →
  前台可查，唯一商品名防并行冲突，清理走 API 幂等删除）与「购物车加购与清空」（6 步，
  独立用户隔离，`data_schema` 的 minItems/maxItems 断言列表长度），`test_15_scenarios.py`
  仅 40 行通用入口。
- **内核单测**：`framework/tests` 扩到 **47 条**（新增场景编排 16 条：加载/重名校验/
  未知字段/提取渲染/缺省断言/负向断言/schema 断言/失败即止/清理注册/幂等清理/变量缺失 SKIP）。
- 回归：`-n 4` **140 passed（7.54s）**；脚手架生成项目 collect-only 验证通过（9 条收集正常）。

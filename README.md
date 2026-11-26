# 接口自动化测试框架（pytest + requests）

本工程已改造为 **通用内核 + 业务项目** 两层结构：

- `framework/`：与被测系统无关的测试内核（请求、断言、数据驱动、清理、报告、脚手架）。
- `projects/shopping/`：现成的 shopping 电商系统用例，178 条（173 通过 + 5 已知缺陷 xfail），作为接入范例。
- 换一个系统时只新增 `projects/<项目名>/`，改配置和用例，**framework 代码不动**。

## 1. 目录结构

```text
D:/shopping-api-automation/
├── framework/                       通用内核（不依赖任何业务系统）
│   ├── config.py                    env/.env 加载器 + Settings(prefix)
│   ├── state.py                     SessionState 单例：集中会话态 + xdist 分区合并
│   ├── client.py                    ApiClient / ApiResult / Envelope 响应包装适配
│   ├── assertions.py                通用断言库（assert_ok / assert_code / ...）
│   ├── data.py                      YAML 数据加载与 parametrize 转换
│   ├── db.py                        SQL 执行器（结构化结果、密码不进命令行）
│   ├── cleanup.py                   注册式清理器 + 清理汇总横幅
│   ├── coverage.py                  接口覆盖率：运行期请求比对 YAML 清单
│   ├── hooks.py                     通用 pytest 钩子 + 报告选项注入
│   ├── reporting/                   仪表盘报告增强（enhancer.py / assets.py）
│   ├── scaffold.py                  新项目脚手架：python -m framework.scaffold
│   └── project_template/            脚手架模板
├── projects/
│   ├── shopping/                    shopping 业务层（178 条用例）
│   │   ├── config.py                账号、库表、路径、报告标签
│   │   ├── conftest.py              api / tokens / cleaner fixtures
│   │   ├── helpers.py               商品构造、独立用户、落库断言
│   │   ├── dbclean.py               shopping 业务 SQL
│   │   ├── data.py + data/          YAML 入口、12 组数据集（权限矩阵/越权矩阵/响应契约）
│   │   │                            与 api_inventory.yaml（接口覆盖率基准）
│   │   ├── testcases/               20 个测试模块
│   │   └── docs/接口清单.md          接口说明与已知行为（覆盖率以 YAML 清单为准）
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
用于"用 A 的凭证访问 B 的资源"这类跨用户场景；路径里的资源 id 用
`/api/cart/${cart_item_id}` 占位，调用时传 `variables={'cart_item_id': ...}` 渲染
（整串占位保留原始类型，id 仍是 int）。shopping 有 15 条矩阵用例
（`test_13_permissions.py`），内核单测见 `framework/tests/`。

### 越权访问（IDOR）

权限矩阵管的是"角色能不能进这个接口"，管不了"同一角色下 A 能不能动 B 的数据"。
`test_16_idor.py` 补这一层，判定标准是**副作用**而不是状态码：

- 攻击者用**自己的合法 token**、拿**受害者的真实资源 id** 发起写操作；
- 断言受害者数据原样（项还在、数量未变）、攻击者列表里不出现受害者数据、
  两个 token 各自 `/api/auth/me` 返回自己；
- 后端把越权做成 `200 + 静默无效` 或 `403/404` 都算通过，打成 `500` 算失败。

shopping 用户端只有购物车项带客户端可控 id（后端 SQL 层写死了 `AND user_id = #{userId}`），
所以 4 条写攻击（改 99 / 改 0 / 改负数 / 删除）+ 列表隔离 + 清空隔离 + 支付结算归属
+ 支付记录隔离 + 身份不串，共 9 条。

**多身份注意**：`requests.Session` 会累积 `Set-Cookie`，而 shopping 后端 Cookie 优先于
`Authorization` 头（`CookieUtil.token`），同一个 `ApiClient` 先后注册两个用户会静默串号。
四层防护：① 多身份用例用 `new_client` fixture 各开一个客户端（首选）；② 复用同一客户端
切换前 `clear_cookies()`；③ 内核 `API_COOKIE_GUARD`（默认 `warn`，CI 可设 `strict` 硬失败）
自动检测「换 token 但 Cookie 未清」；④ 鉴权负向用例也用 `new_client` 起干净会话。
详见 `docs/Cookie 优先后端的身份串号防护方案.md`。

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
| `API_COOKIE_GUARD`（全局，无前缀） | `warn` | 身份串号守护：`off` / `warn` / `strict`（CI 建议 `strict`） |

`auto` 模式登录后自动探测：能提取到 token 就走 header，否则有 Cookie 就走 cookie。
显式传 `token=` 的调用始终优先注入请求头，因此 shopping 现有 178 条业务用例无需改动。

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

### 启动体检（preflight）

`framework/preflight.py` 把「服务可达 → 服务自检 → 数据库可用 → 登录可用」做成一组有序检查，
在用例收集之前（`pytest_sessionstart`）跑一次。环境没备好时只输出一条消息、退出码 4、
**用例零执行**——不再出现「后端没启动，140 条各报一次 ConnectionRefused」那种要翻完红叉
才知道根因的报告。

```text
ERROR: 启动体检未通过：4 项检查中 1 项失败、2 项跳过，本次未执行任何用例。

  [FAIL] 后端可达 — 无法连接 http://127.0.0.1:8080：连接被拒绝（服务未启动或端口不对）（2069 ms）
         提示：先启动被测服务（D:/shopping/start-backend.bat）；并确认 .env 的 SHOPPING_API_BASE_URL=...
  [SKIP] 服务自检 — 后端不可达（见上一项），未执行健康自检（0 ms）
  [ OK ] 数据库可用 — root@localhost:3306/shopping_db（142 ms）
  [SKIP] 登录可用 — 后端不可达（见上一项），未执行登录校验（0 ms）
```

| 环境变量（无前缀） | 默认值 | 说明 |
| --- | --- | --- |
| `API_PREFLIGHT_ENABLED` | `1` | `0` 关闭体检；`--collect-only` 始终跳过（收集不需要服务） |
| `API_PREFLIGHT_STRICT` | `1` | `0` 时必检项失败只告警不中止（应急放行） |

四种结果：`OK` / `WARN`（`required=False` 的检查失败，如本地无数据库）/ `SKIP`
（前置条件未满足，不把「没测」显示成「失败」）/ `FAIL`（必检项失败，中止）。

设计取舍：检查项逐个跑完、不因前一项失败而提前结束（一轮把问题说全）；探活复用同一次 HTTP
请求并关闭重试（避免把「服务没起」的等待翻倍）；体检顺带登录一次并缓存 token，`tokens`
fixture 直接复用，不重复登录；结果写入 `run_summary.json` 的 `preflight` 字段，环境问题事后可追溯。

新项目接入：在 `projects/<项目>/conftest.py` 的 `pytest_sessionstart` 里
`Preflight([...]).run_or_exit()`，四个检查项可照抄 `projects/shopping/conftest.py`。

## 4. framework 内核能力

| 模块 | 能力 |
| --- | --- |
| `config.py` | 环境变量 > `.env` > 默认值；`Settings(prefix)` 支持多项目共存 |
| `client.py` | 统一请求/计时/响应解析、慢请求高亮、敏感字段脱敏（password/token 等键值掩码，报告与断言消息全覆盖）、失败请求存档、幂等方法重试、trace_id 链路追踪 |
| `assertions.py` | `assert_ok/assert_status/assert_code/assert_message_contains/assert_fields/assert_numeric_fields/assert_contains_row` 等，失败信息带 URL 与 code；`assert_elapsed` 做响应耗时预算校验（`API_SLA_SCALE` 整体放宽，不改用例） |
| `data.py` | YAML 数据集校验、单字段返回标量列表、多字段返回 tuple，直接喂给 `parametrize` |
| `extract.py` | 响应值提取与用例内依赖链：`extract` 点分路径 + 数组下标，`CaseContext` 记录变量并渲染 `${name}` 占位符 |
| `schema.py` | 响应契约校验（JSON Schema Draft 7）：校验字段存在性/类型/范围，失败定位到具体路径并附完整响应 |
| `preflight.py` | 启动体检：检查项有序执行、结果分级（OK/WARN/SKIP/FAIL）、失败聚合成一条 `ERROR` 中止整轮 |
| `scenario.py` | YAML 场景编排（**能力储备，仅线性正向链路**）：一个 YAML 块描述多步链路（request/extract/assert/cleanup），`${}` 变量链与类型保持复用 extract/CaseContext，未知字段即报错，清理进报告汇总；负向 / 落库 / 软断言 / 多身份场景仍写 Python（见 §12 与 §24） |
| `db.py` | PyMySQL 驱动直连、真参数绑定（`%s` 占位符）、线程本地连接复用、结构化 `records` 行、驱动缺失自动 SKIP、`strict` 模式（CI 数据库不可用直接失败） |
| `cleanup.py` | 清理动作注册化、顺序执行、成功/跳过/失败汇总注入报告 |
| `coverage.py` | 接口覆盖率：`ApiClient` 上报真实请求 → 路径归一化（`{id}`/`{file}`）→ 与 YAML 清单比对 → 输出 `api_coverage.md/json`；`python -m framework.coverage --min N` 供 CI 门禁 |
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
内核单测：`python -m pytest framework/tests -o addopts= -q`（140 条）。

## 5. shopping 项目现状

### 覆盖范围（178 条：173 通过 + 5 条已知缺陷 xfail）

| 模块 | 用例数 | 模块 | 用例数 |
| --- | --- | --- | --- |
| 健康与响应结构 | 5 | 管理端登录 | 14 |
| 用户认证 | 11 | 概览统计 | 6 |
| 商品浏览 | 10 | 商品管理 | 22 |
| 搜索联想 | 6 | 分类管理 | 8 |
| 购物车 | 12 | 审批流 | 10 |
| 虚拟支付 | 11 | 图片上传 | 7 |
| 登录后权限矩阵 | 15 | 响应契约校验 | 5 |
| 场景编排 | 2 | 越权访问（IDOR） | 9 |
| 幂等与并发 | 3 | 鉴权异常输入 | 6 |
| 分页边界 | 7 | 输入边界与特殊字符 | 9 |

关键断言：`/api/health` 状态 UP、统一响应包装、上下架过滤、¥1000/¥1001 支付边界与订单落库、
用户/管理 token 双向隔离、审批通过后才入库、有商品分类禁止删除、图片上传后可回源。

### 账号与隔离

- 商城用户：`demo / 123456`（`sys_user`）
- 管理员：`admin / admin123`、`reviewer / review123`、`operator / op123456`（`sys_admin`）
- 购物车按 `user_id` 存储，写操作由 `register_isolated_user()` 注册独立用户，用例结束精确删除，可安全并行。
- 临时商品、申请单、分类、购物车、上传图片由 `cleaner` 回收；订单与用户由 `dbclean.py` 直连 MySQL 精确删除；目标已不存在按幂等成功处理。

### 数据驱动

`projects/shopping/data/api_cases.yaml` 共 12 组数据集：注册短账号、未登录接口清单、非法金额、
管理端未登录接口、商品参数校验、上下架状态值、非法状态值、批量状态值、商品表单模板，
以及权限矩阵 `permission_matrix`、越权矩阵 `idor_matrix`、响应契约 `response_schemas`。
`cases('数据集名', '字段1', '字段2')` 直接作为 `parametrize` 参数，增删 YAML 行即增减用例；
`records('数据集名')` 保留整行 dict，适合字段多的矩阵场景。

## 6. 报告

`reports/report.html` 是单文件自包含报告，每次执行自动增强：

- KPI 卡与通过率环形图、20 模块分布条形图、TOP 14 接口统计（均耗/峰值/失败数）。
- **双层状态分布**：HTTP 2xx/4xx/5xx 与业务 code 分开统计。shopping 后端把失败封装为
  `HTTP 200 + code 400/401/404`，所以两者口径不同；负向用例主动触发的 4xx/5xx 不代表测试失败。
- 请求明细：方法徽章、HTTP 状态、业务 code、耗时、左右双栏请求/响应，token 脱敏。
- 顶部「测试后清理汇总」：成功/跳过/失败分色，真实失败逐条列明；报告增强失败也会醒目提示。

## 7. 目录约定

根目录只保留入口与配置（`.env` / `pytest.ini` / `pyproject.toml` / `requirements*.txt`
/ `run.bat` 等），**不再放 Python 模块**——早期 7 个兼容层薄壳（`config.py` /
`client.py` / `read_yaml.py` / `dbclean.py` / `helpers.py` / `report_enhancer.py` /
`report_assets.py`）已确认零引用并删除。所有代码分两层引用：内核走 `framework.*`，
业务走 `projects.<项目名>.*`，不再有"到底 `from client` 还是 `from framework.client`"
的歧义。

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
  再加载 `.env` 兜底，环境差异只维护差异项；`Settings.require(*names)` 登记必填配置（缺项交给启动体检统一报，见 §19）。`.env` 解析改用 `utf-8-sig`，
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

## 12. 场景编排层（2026-11-23，定位见 §24：能力储备，非主流程默认写法）

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

## 13. 启动体检（2026-11-24）

- **新增 `framework/preflight.py`**：`Check` / `Preflight` 把环境检查做成有序清单，收集用例前
  跑一次；必检项失败抛 `pytest.UsageError`——终端一条 `ERROR: ...`、退出码 4、用例零执行。
  四种结果 `OK` / `WARN`（`required=False` 项失败）/ `SKIP`（前置未满足，如后端不可达时不再
  逐个账号登录）/ `FAIL`（必检失败）。
- **shopping 接入**：`conftest.py` 的 `pytest_sessionstart` 跑四项检查（后端可达 / 服务自检 /
  数据库可用 / 登录可用）；探活复用一次请求并关闭重试（后端没起时等待从 4.3s 降到 2.1s）；
  登录失败消息改用新增的 `ApiResult.describe()`（`HTTP 200 / code 401 / 用户名或密码不正确`），
  不再把整段 `repr` 塞进体检消息。体检登录结果被 `tokens` fixture 复用，不重复登录。
- **分级口径**：数据库检查用 `required=DB_STRICT`——本地（`DB_STRICT=0`）只告警，保持「本地
  无库也能跑、落库断言自动跳过」的既有约定；CI（`DB_STRICT=1`）直接失败，杜绝假全绿。
- **沉淀**：`run_summary.json` 新增 `preflight` 字段（每项 state/detail/耗时）。
- **验证**：后端未启动 → `EXIT=4`、一条消息、0 用例执行；口令写错 → 只报「登录可用」并指出
  401 原因；后端关闭时 `--collect-only` 仍正常收集 140 条；正常环境串行 **140 passed**、
  `-n 4` **140 passed**；`API_PREFLIGHT_ENABLED=0` 回退到改造前行为（仍 140 passed）；
  `API_PREFLIGHT_STRICT=0` 只告警不中止。
- **内核单测**：`framework/tests` 扩到 **70 条**（新增 23 条：失败聚合、WARN/SKIP 分级、
  strict/enabled 开关、消息单行化与截断、Ctrl+C 不被吞、records 副本、环境变量默认值）。

## 14. 越权访问（IDOR，2026-11-24）

- **新增 `test_16_idor.py`（9 条）**：补齐权限矩阵覆盖不到的一层——同一角色下
  「A 能不能动 B 的数据」。判定标准是副作用而非状态码：受害者数据必须原样，
  越权请求打成 `500` 也算失败（未处理异常不是「拒绝」）。
- **数据驱动**：新增 `idor_matrix` 数据集（4 条写攻击：改 99 / 改 0 / 改负数 / 删除），
  `role` 写资源归属者、`token_from` 写实际请求者——这正是 `token_from` 的设计用途。
- **内核增强**：`check_permission` 支持 `variables`，路径 / params / json_body 里的
  `${name}` 统一按 `CaseContext.render` 渲染（整串占位保留原始类型）；渲染后仍残留
  占位符直接报错，避免把模板当真实路径发出、错判成接口 404。顺手修掉 `label` 用原始
  大小写、与实际请求方法不一致的小瑕疵。
- **发现并规避一个框架陷阱**：shopping 后端 `CookieUtil.token` 是 **Cookie 优先、
  Authorization 兜底**，而 `requests.Session` 会累积 `Set-Cookie`；同一 `ApiClient`
  先后注册两个用户时，后者的 Cookie 会覆盖前者的请求头，造成静默串号（首轮 9 条全部
  因此失败）。新增 `ApiClient.clear_cookies()` + `new_client` fixture（每身份独立会话）。
- **后端实测行为**：4 种越权写操作均返回 `HTTP 200 / code 200 / success` 但零副作用
  （`CartMapper` 的 SQL 全部带 `AND user_id = #{userId}`）；列表、清空、支付结算、
  支付记录、`/api/auth/me` 均按 token 归属隔离。
- **断言有效性验证**：做了一次变异测试——用受害者自己的 token 真改数量 / 真删项，
  断言分别报出「数量被越权改动」「购物车项被越权删除」，确认不是永远绿的假用例。
- 回归：串行 **149 passed（9.08s）**、`-n 4` **149 passed（6.17s）**、`ruff check .` 通过；
  内核单测 70 → **90 条**（新增权限矩阵 20 条：行解析、凭证解析、变量渲染、断言消息）。

## 15. 断言质量：耗时预算与已知缺陷登记（2026-11-24）

- **新增 `assert_elapsed(result, max_ms, hint)`**：断言单次请求耗时不超过预算，
  预算 = `max_ms × API_SLA_SCALE`（默认 1.0）。已接入 6 条核心链路——健康检查 500ms、
  用户登录 800ms、商品列表 800ms、搜索联想 800ms、加入购物车 800ms、虚拟支付 1200ms。
  阈值按本机实测中位数（2~6ms）留了两个数量级余量，只抓「功能没坏但慢到不可用」，
  不压着真实值卡秒表；慢机器/CI 用 `API_SLA_SCALE=3` 整体放宽。
- **修掉一处假绿**：`test_upload_requires_file` 原断言 `status in (400, 500)`，
  等于把服务端未处理异常记成「防护住了」。实测后端对非 multipart 请求返回 **500**
  （Spring `MultipartException` 无人处理，回落到默认错误页且没有 code/message 包装）。
- **同时引入已知缺陷登记机制**：该用例改为 `xfail(strict=True)` 并写明原因，预期 400/415。
  缺陷修好后它会变成 XPASS 被 strict 判失败，提示删除标记——不会再被永久静默。
  `run_summary.json` 已能分别统计 `xfailed` / `xpassed`。
- **补一条漏测分支**：`test_upload_rejects_empty_file` —— file part 存在但内容为空时
  返回 `code 400 / 文件为空`（这条分支原来没有用例）。
- **断言有效性验证**：`API_SLA_SCALE=0.0001` 反向验证，6 条耗时断言全部按预期报
  「耗时 X ms 超出预算 0 ms」并带一行 `describe()` 摘要，确认不是恒真断言。
- 回归：**149 passed + 1 xfailed（7.67s）**、`ruff check .` 通过；
  内核单测 90 → **102 条**（新增断言预算 12 条：默认值、放宽倍数、非法配置兜底、
  边界值、超预算消息）。

## 16. 幂等/并发、鉴权异常、上传安全面与软断言（2026-11-24）

### 新增用例（12 条，总数 150 → 162）

- **`test_17_idempotency.py`（3 条）**：同一购物车连续支付（第二次应被拒且只有一张订单）、
  重复删除购物车项（HTTP 幂等，不报 5xx）、**同一购物车并发支付（3 线程）只应成一单**。
- **`test_18_auth_negative.py`（6 条）**：篡改 / 乱码 / 超长 2000 字符 / 注入式 token 一律 401
  且响应不带用户数据、缺 header 也 401，外加一条**有效 token 对照**（证明不是接口恒返回 401）。
- **`test_12_upload.py` 3 → 7 条**：超 10MB 上限、扩展名与 MIME 不符、`../` 文件名穿越、
  file part 内容为空。

### 发现 3 个真实缺陷（均以 `xfail(strict=True)` 登记，修好后自动翻红提示删标记）

| 缺陷 | 实测行为 | 应有行为 |
| --- | --- | --- |
| **并发重复下单**（最严重） | 3 线程同时支付同一购物车 → **3 张 SUCCESS 订单**（4 轮 × 3 线程 = 12 单，期望 4 单）。`PayController` 先 `findByUser` 再 `PayService.record`，无幂等键、无行锁 | 只成功一单，其余返回「购物车为空」 |
| 上传超 10MB | `max-file-size=10MB` 超限抛 `MaxUploadSizeExceededException`，无 `@ControllerAdvice` → **500** 默认错误页 | 413（或 400） |
| 上传缺 file part | 非 multipart 请求抛 `MultipartException` → **500** | 400 / 415 |

### 探到的好消息（已写成用例守住）

- 6 种坏 token 全部 `code 401 / 未登录或登录已过期`，且 `data` 为空——没有信息泄露；
- `../` 文件名被服务端 UUID 化（`upload-<12hex>.png`），**路径穿越无效**；
- 扩展名由 MIME 推导、客户端文件名被丢弃，`.txt` 配 `image/png` 也会落成 `.png`；
- 重复删除购物车项两次都返回 `code 200`、购物车保持为空，符合 HTTP 幂等语义。

### 断言库升级

- **失败信息切到一行摘要**：新增 `describe_result()`，`assert_code/assert_status/...` 的
  消息从整段 `repr(ApiResult)` 变成 `HTTP 200 / code 400 / 购物车为空，无法支付；url`。
- **新增软断言 `SoftAssert` + `soft` fixture**（根 conftest，所有项目可用）：
  累积多条失败、`soft.assert_all()` 一次抛出。已改造 2 条用例示范——
  `test_home_aggregates_all_sections`（5 个分区）与 `test_payment_succeeds_at_exactly_1000`
  （4 个字段 + 购物车）。失败时输出形如：

  ```text
  4 项断言失败：
    · 订单状态：期望 'SUCCESS'，实际 'FAILED'
    · 订单金额：期望 1000.0，实际 999.0
    · 购物车已清标记：期望 True，实际 False
    · 支付后购物车：期望 []，实际 ['残留一件']
  ```

- 内核单测 102 → **111 条**（新增摘要回落、软断言聚合、hint 前缀、ApiResult 助手）。

### 一个必须记住的探测教训

首轮探测「坏 token」时 6 种全部返回 `200 success`，看似鉴权完全失效。实际是**测试代码自己的坑**：
注册用户时 `Set-Cookie` 留在了同一个 `requests.Session`，而后端 `CookieUtil.token` 是
**Cookie 优先、Authorization 兜底**——放进去的坏 token 被合法 cookie 覆盖了。
改用 `new_client()` 起干净会话后，6 种全部正确返回 401。**写鉴权/多身份用例必须用独立会话**，
否则会得出完全相反的结论（这次是先差点误报一个「高危漏洞」）。

- 回归：串行 **159 passed + 3 xfailed（8.20s）**、`-n 4` 连续 3 轮同结果、`ruff check .` 通过。

## 17. 分页边界与超长输入（2026-11-24）

### 新增用例（16 条，总数 162 → 178）

- **`test_19_pagination.py`（7 条）**：`page=0/-1` 归一化为首页、`page` 越界回退末页、
  `pageSize` 夹在 1..100、非数字分页参数返回 `code 400`、逐页翻完不重不漏、
  空结果集上的越界页码也安全。
- **`test_20_input_bounds.py`（9 条）**：用户名/商品名/副标题/描述超长、`%` 与 `_` 通配符
  转义、SQL 注入载荷、超长关键词（URL 超 8KB）、特殊字符原样存储。

### 分页实测行为（全部符合预期，已写成断言守住）

| 请求 | 实际 | 说明 |
| --- | --- | --- |
| `page=0` / `page=-1` | `page=1` | 归一化为首页，内容与首页一致 |
| `page=999999` | `page=totalPages` | 回退末页且仍有数据，不返回空列表 |
| `pageSize=0` / `-1` | `pageSize=1` | 下界夹到 1 |
| `pageSize=1000` / `10000` | `pageSize=100` | 上界截到 100，且响应回显生效值 |
| `page=abc` / `pageSize=abc` | `code 400` | 非数字参数是客户端错误 |

### 又发现 2 个真实缺陷（同类根因：只靠库表兜底，没有前置校验）

| 输入 | 列定义 | 实测 |
| --- | --- | --- |
| 用户名 65 字符 | `sys_user.username varchar(64)` | **500**（64 成功、65 必崩） |
| 商品描述 25000 字（约 75000 字节） | `description text(65535 字节)` | **500** |

**已有的长度校验是好的**（说明写法不统一，而不是没能力做）：
商品名 >128 → `code 400`「商品名称不能超过 128 个字符」；副标题 >255 → `code 400`「副标题不能超过 255 个字符」。
缺校验的是**注册用户名**与**商品描述**这两条路径。

### 特殊字符全部安全（也写成用例守住）

- `%` 与 `_` 被当成字面量（`escapeLike` 生效），结果 0 条而**不是全量**——LIKE 通配符未泄漏；
- `' OR '1'='1` 返回 0 条，无注入迹象；
- 引号 / `<img onerror>` / emoji 混排的商品名原样入库，不截断、不转义、不 5xx；
- 超长关键词（1000 汉字，URL 远超 8KB）由容器直接 400，是客户端错误而非 5xx。

### 一处测试设计取舍

分页用例**不用全局商品列表**做数据源：`-n 4` 下其他用例随时增删商品，`total` 会漂。
改为每条用例用唯一前缀造 3 张申请单、再用 `keyword` 过滤，总数恒为 3——
这条纪律和之前「审批流改精确查询」是同一个思路：**断言的可重复性优先于用例的简洁性**。

- 回归：串行 **173 passed + 5 xfailed（10.20s）**、`-n 4` 连续 3 轮同结果、`ruff check .` 通过。

## 18. 接口覆盖率：从人工对照变成可计算（2026-11-24）

之前「覆盖了多少接口」只能靠人读 `docs/接口清单.md`。现在改成运行期统计：

1. `ApiClient` 每发一次请求就上报（方法 + URL + 状态码）；
2. 路径归一化后与 YAML 清单比对：`/api/cart/12` → `/api/cart/{id}`、
   `/images/upload-abc.png` → `/images/{file}`、`/api/admin/products/1509/status`
   → `/api/admin/products/{id}/status`；
3. 输出 `reports/api_coverage.md`（人看）+ `api_coverage.json`（看板/门禁），终端同时打表。

### 清单

`projects/shopping/data/api_inventory.yaml` —— 43 条「方法 + 路径」，带 `group` / `name` /
`covered_by`。清单只声明**存在哪些接口**；覆盖率不按 `covered_by` 推断，而是按真实请求算。
`接口清单.md` 保留说明与实测行为，两边的职责分开：**人读说明，机器算覆盖**。

### 实测结果

| 跑法 | 覆盖率 |
| --- | --- |
| 全量（串行 / `-n 4`） | **43/43 = 100.0%** |
| 只跑 `test_01_health.py` | **5/43 = 11.6%** |

两次都是真的按请求统计（不是常量），这也是对统计逻辑本身的验证。

终端输出：

```text
[coverage] 接口覆盖率 43/43 = 100.0%
  清单外请求 1 条：
    - GET /api/__definitely_not_exists__（404×1）
```

「清单外请求」是有意保留的一项：`test_undefined_endpoint_returns_404` 会故意打一个不存在的
路径，被单独列出来而不是混进覆盖率——**清单外 ≠ 覆盖率低**，但能发现「新接口写了用例却忘了
登记清单」这种情况。

### xdist 合并

沿用 cleanup 的机制：worker 退出时把本进程命中写 `.api_coverage_<worker>.json`，
主进程在 `pytest_unconfigure` 合并后删除临时文件。已实测 `-n 4` 下覆盖率仍为 43/43。

### CI

- 表格写进 GitHub Actions 运行页摘要（`$GITHUB_STEP_SUMMARY`），不用点进 artifact 才看得到；
- `reports/api_coverage.md` / `.json` 进 artifact；
- 门禁是**可选**的：设仓库变量 `API_COVERAGE_MIN=90` 才会执行
  `python -m framework.coverage --min 90`，低于阈值返回非 0 让流水线失败。
  阈值策略留在流水线里，框架不去改 pytest 的退出码。

### 内核单测

111 → **140 条**（新增覆盖率 29 条：归一化 7 组、清单校验、汇总统计、
清单外请求、markdown/terminal 渲染、worker 合并、CLI 退出码）。

## 19. 配置校验时机修正：从 import 期改到启动体检（2026-11-25）

### 问题

`Settings.require()` 原本在缺失时**立即抛 `ValueError`**，而它是在
`projects/<name>/config.py` 的模块级被调用的——等于把「环境没备好」变成了
「模块导入失败」。后果有三层：

1. `pytest --collect-only` 也崩，而收集用例根本不需要配置；
2. 报错是一段 `ImportError ... ValueError` 堆栈，和「后端没起」那条漂亮的一行 ERROR 完全不是一个形态；
3. 同一个问题（环境没备好）被拆成两套表达，README 里也得写两遍。

这就是 CI 第一次失败的真正机制：`cp .env.example .env` 只是补上了缺的文件，
**没有解决「配置校验发生在错误的时机」**。

### 改法

- `Settings.require()` 改为**登记**缺项（`MISSING_REQUIRED`），返回缺失键列表，不抛错；
- 启动体检新增第一项 **「必填配置」**，把缺项一次性说清；
- 需要老行为时设 `API_CONFIG_STRICT=1`，立即在 import 期报错（给「宁可炸在最早一步」的场景）；
- 顺带修掉一个连带问题：体检中止时**跳过覆盖率统计**，否则会把「环境没备好」写成
  覆盖率从 43/43 掉到 1/43 的假回归（`preflight.aborted()` 标记）。

### 实测（把 `.env` 临时移走）

| 场景 | 改造前 | 改造后 |
| --- | --- | --- |
| `pytest --collect-only` | `ImportError`，退出码 4 | **退出码 0**，正常收集 178 条 |
| `pytest` | `ImportError` 堆栈 | **退出码 4**，一条 ERROR，用例零执行 |
| `API_CONFIG_STRICT=1` + 缺配置 | `ValueError` | `ValueError`（行为保持） |

改造后的输出（第一项就是配置）：

```text
ERROR: 启动体检未通过：5 项检查中 2 项失败、2 项跳过，本次未执行任何用例。

  [FAIL] 必填配置 — 缺少必填配置：SHOPPING_UPLOAD_DIR[default]（请在 .env 或进程环境变量中补充）（0 ms）
         提示：照 .env.example 补齐缺项；CI 从 .env.example 生成 .env 即为此项服务
  [FAIL] 后端可达 — 无法连接 http://127.0.0.1:8080：连接被拒绝（服务未启动或端口不对）（2061 ms）
```

### 顺带修掉一条不稳定用例

验证时串行跑出一次 `XPASS(strict)`：并发支付那条**这一轮没触发竞态**（后端串行化了），
于是 xfail 变成 XPASS 被 strict 判失败。竞态窗口只有「SELECT 购物车 → INSERT 订单」几毫秒，
线程启动时间差就能错过。

改法：用 `threading.Barrier` 让三个请求**同时**发出，并跑 **3 轮**——任一轮出现重复订单即判缺陷存在。
连续 8 次单跑全部稳定 xfailed，全量串行/并行各 2 轮均 173 passed + 5 xfailed。

- 内核单测 140 → **155 条**（新增配置登记语义 12 条、中止标记 3 条）；`ruff check .` 通过。

---

## 20. 会话态收敛：SessionState（2026-11-25）

### 问题

六处模块各自持有进程级全局状态：

| 模块 | 原全局变量 | 用途 |
| --- | --- | --- |
| `config.py` | `MISSING_REQUIRED` | 必填键登记 |
| `preflight.py` | `RECORDS` / `ABORTED` | 体检结果、中止标记 |
| `coverage.py` | `HITS` / `INVENTORY` | 请求命中、清单路径 |
| `cleanup.py` | `CLEANUP_LOG` | 清理汇总 |
| `hooks.py` | `REPORT_OPTIONS` / `REPORT_ENHANCE_ERROR` | 报告选项、增强错误 |
| 业务 `conftest.py` | `_TOKENS` | 登录态缓存 |

其中 cleanup 与 coverage **各写了一遍几乎相同的**「xdist worker 落盘 → 主进程合并」逻辑；
跨模块判断（体检中止 → 跳过覆盖率）只能靠全局变量打信号，状态来源不唯一。

### 改法

- 新增 `framework/state.py`：`SessionState` 进程级单例，显式声明全部会话态字段；
- **容器原地清空**：`reset()` / `reset_*()` 用 `.clear()` 而非重新赋值，各模块保留的
  兼容别名（`config.MISSING_REQUIRED`、`preflight.RECORDS`、`coverage.HITS`、
  `cleanup.CLEANUP_LOG` 等）永远指向同一对象，外部代码与既有测试零改写；
- **xdist 分区注册表**：cleanup / coverage 各自注册「前缀 + dump + merge」，
  worker 退出由 `state.dump_worker()` 一次写出全部分区，主进程由
  `state.load_workers()` 一次合并——删掉两处重复的落盘/合并代码；
- 业务登录态用 `state.namespace('shopping.tokens')` 私有槽位，内核不认识业务字段；
- 标量状态（`ABORTED`、`INVENTORY`）改为读写 `state.*`，消除第二来源。

### 兼容性

公开 API 全部保留：`coverage.record/reset/dump/load_dumps/collect_main`、
`preflight.records/aborted`、`config.missing_required/clear_missing_required`、
`cleanup.dump_log/load_logs`、`hooks.configure_report` 签名与行为不变。

### 实测

| 验证项 | 结果 |
| --- | --- |
| `ruff check .` | 通过 |
| 内核单测 | 155 → **169 条**（新增 `test_state.py` 14 条：别名存活、隔离、分区合并、并发、损坏文件） |
| 收集阶段 `--collect-only` | 178 条，退出码 0 |
| 全量串行 | 173 passed + 5 xfailed，覆盖率 43/43 |
| 全量 `-n 4` | 173 passed + 5 xfailed，覆盖率 43/43，worker 临时文件无残留 |

---

## 21. 覆盖率双口径：触达 vs 有效（2026-11-25）

### 问题

旧覆盖率只要 `ApiClient` 发出请求就算命中——5 条 xfail 的 500、鉴权异常的 401、
故意打不存在的路径，都和正常成功调用一样计进 43/43。数字漂亮，但
"接口被测过" 和 "接口的成功路径被验证过" 是两回事。

另有一个反向问题：`test_01_health` 故意请求 `/api/__definitely_not_exists__` 验证
404 兜底，这类**合法负向调用**若直接纳入"清单外请求门禁"会造成误报。

### 改法

- **双口径**：
  - 触达（covered）：接口至少被请求过一次（含 4xx/5xx）；
  - 有效（effective）：接口至少有一次**成功响应**——JSON 响应要求 HTTP 2xx 且业务
    code 成功（`result.ok`）；静态图片等二进制响应没有业务信封，HTTP 2xx 即有效。
- **采集层**：`coverage.record(..., ok=...)` 记 `success` 计数；
  `client.coverage_success()` 统一判定，断言仍用 `result.ok` 不受影响；
  xdist 合并兼容旧 `success` 缺失的报告（按 HTTP 2xx 推断）。
- **白名单**：清单顶层 `allowed_unexpected` 登记已知清单外请求（负向用例路径），
  不计违规但仍在报告单列，避免静默漏登记新接口。
- **报告**：markdown / 终端同时展示两种覆盖率，新增"仅错误态触达"与
  "已知清单外请求"两节；`api_coverage.json` 增加 `effective` / `effective_ratio`
  / `ineffective` / `known_extra` 字段。
- **CLI 门禁**：`--metric {touched,effective}`（默认 touched，兼容旧脚本）、
  `--fail-on-unexpected`；CI 默认按 effective + 开启清单外检查，阈值仍由
  `API_COVERAGE_MIN` 控制（可用 `API_COVERAGE_METRIC` 覆盖口径）。

### 实测

| 验证项 | 结果 |
| --- | --- |
| `ruff check .` | 通过 |
| 内核单测 | 169 → **190 条**（新增双口径 8、白名单 4、CLI 门禁 5、二进制判定 4） |
| 全量 `-n 4` | 触达 43/43 = 100%，**有效 43/43 = 100%**，173 passed + 5 xfailed |
| 门禁正向 | `--metric effective --min 90 --fail-on-unexpected` → 退出码 0 |
| 门禁反向（临时移除白名单） | 抓到 `GET /api/__definitely_not_exists__`，退出码 1；恢复后归零 |

期间发现并修正一个真实误判：静态图片回源返回 HTTP 200 二进制，旧 `result.ok`
因无业务 code 判 False，一度被标成"仅错误态触达"；改由 `coverage_success()` 特判
后恢复为有效覆盖。

---

## 22. 已知缺陷台账：xfail 与缺陷记录双向绑定（2026-11-25）

> 人读版汇总（缺陷明细 + 对应用例的触发条件与断言）：`projects/shopping/docs/已知缺陷台账.md`。

### 问题

5 条 `xfail(strict=True)` 用例把后端缺陷钉在了测试里，但存在两个缺口：

- `reason` 只描述现象、没有缺陷编号，XPASS 让 CI 变红时说不清归属；
- 后端修好后，开发者常只删标记、忘改缺陷状态（或反过来），下一轮才知道漏了一处。

### 改法

- **单一事实源** `projects/shopping/data/known_defects.yaml`：每条缺陷带 `DEF-001` 编号、
  绑定的用例 nodeid、状态 open/fixed、现象、预期、接口、级别、发现日期；
- **收集清单自动落盘**：pytest 收集钩子写 `reports/shopping_xfail_manifest.json`
  （全部 nodeid + xfail 子集）。按项目名隔离——跑内核单测不会覆盖业务项目的清单；
  xdist 下 worker 各写分片，主进程汇总后清理；
- **双向校验** `python -m framework.defects --project shopping --check`：
  - 台账 open + 用例无 xfail → 提示改 fixed；
  - 台账 fixed + 用例仍有 xfail → 提示删标记（否则修补后 XPASS 变红）；
  - 用例有 xfail 但台账没登记 → 孤儿标记；
  - 台账 nodeid 未被收集到 → 拼写错或用例已删；
  - xfail 非 strict、reason 缺缺陷号 → 同样判失败。
- **reason 前缀带编号**：5 条 xfail 的 reason 均以 `[DEF-00x]` 开头，XPASS 输出可直接反查台账；
- **报告沉淀**：每轮 `run_summary.json` 写入 `known_defects` 统计，`known_defects.md`
  由台账渲染（不再手工维护第二份 Markdown），CI 摘要和 artifact 都带上。

### 修复缺陷时的标准动作（两步，缺一不可）

1. 删除用例上的 `@pytest.mark.xfail`；
2. 台账里把该条 `status` 改为 `fixed`，补 `fixed_date`。

CI 在跑用例前用 `--collect-only` 生成清单并做门禁，上述任一处遗漏都会立即失败。

### 实测

| 验证项 | 结果 |
| --- | --- |
| `ruff check .` | 通过 |
| 内核单测 | 190 → **230 条**（新增 `test_defects.py` 40 条：台账结构、双向校验、CLI、xdist 分片、项目隔离） |
| 收集 + 门禁 | 178 条用例、5 条 xfail 全部 strict 且带编号，退出码 0 |
| 反向：台账改 fixed 忘删标记 | 抓到 DEF-001，退出码 1；恢复后归零 |
| 反向：reason 缺编号 | 抓到 DEF-003，退出码 1；恢复后归零 |
| 全量串行 / `-n 4` | 173 passed + 5 xfailed，双口径覆盖率 43/43；台账摘要进终端与报告，分片无残留 |

---

## 23. 三项可信度补强：报告回归 / 兜底清理 / 内核去业务名（2026-11-25）

### 23.1 报告增强层加回归测试

`framework/reporting/enhancer.py` 靠正则解析 pytest-html 私有的 `data-jsonblob`
属性并做字符串注入，过去在 `pytest_unconfigure` 里被 `try/except` 吞掉异常：
插件升级导致结构变化后，报告静默退回原始版本，CI 仍旧全绿。

- **结构契约显式化**：缺 `data-jsonblob`、JSON 坏掉、或缺 `</head>` / `<body>` /
  `</body>` 任一注入锚点，`enhance()` 直接抛 `ValueError`，不再"找不到就不注入"；
- **golden HTML 测试**（`framework/tests/test_report_enhancer.py`）：最小报告验证
  仪表盘/CSS/JS 注入、用例与接口统计、业务 code 与 HTTP 状态分栏、幂等性；
  结构变更四类场景全部断言抛错；
- **失败可见**：增强失败除写入报告横幅，还追加到 `run_summary.json` 的
  `report_enhance_error` 字段；CI 新增 `Verify report enhancement` 步骤显式检查，
  失败即非 0——测试结论不变红，但"报告没仪表盘"藏不住。

### 23.2 清理兜底 sweep

`Cleaner` 是注册式的：用例中途异常、或新人忘了 `register()`，产生的数据就没人收。

- 内核新增 `register_sweep(name, discover, clean, fallback, prefixes)` 与
  `run_sweeps()`：业务只回答"扫什么 / 怎么删"，内核负责调度、记录与结果汇总；
- **前缀二次校验**：`prefixes=('API',)` 由内核在 `clean()` 之前再验一次，
  `discover` 即使扫宽了也删不到真实数据；
- **只在主进程跑一次**：xdist 下先合并 worker 记录再扫描，避免并行 worker 互删；
  启动体检中止（用例零执行）时跳过，防止环境没备好时刷出误导性 FAIL；
- **报告单列**：清理横幅与 `run_summary.json` 都把"注册式清理"和"兜底清理"
  分开统计，兜底数 > 0 意味着有用例漏登记，值得单独追查；
- 业务侧在 `projects/shopping/conftest.py` 注册四类扫描器（用户/商品/分类/审批），
  底层走 `dbclean.scan_test_keys()` 的白名单只读查询；业务用例文件一行未改。

反向验证：人为插入 `APIUSWEEPX`（测试残留）与 `REALUSERX`（真实账号），
跑最小用例集后前者被清、后者保留，`cleanup.sweep` 记 1；`-n 4` 下同样只清 1 次。

### 23.3 缺陷台账去除业务名硬编码

`framework/defects.py` 原有 `DEFAULT_LEDGER = 'projects/shopping/data/...'`，
内核认识具体业务名。改为：

- 删除该常量；CLI 用 `--ledger` 显式传入，或由 `--project <名>` 按约定推导
  `projects/<项目名>/data/known_defects.yaml`；两者都没传时明确报错（退出码 2）；
- CI 命令简化为 `--project shopping`，不再写死台账路径；
- `ledger_for_project()` 单测用临时 ROOT 验证推导与显式参数优先级。

### 实测

| 验证项 | 结果 |
| --- | --- |
| `ruff check .` | 通过 |
| 内核单测 | 230 → **256 条**（报告增强 11、兜底清理 12、台账 CLI 3） |
| 全量串行 / `-n 4` | 173 passed + 5 xfailed，触达/有效覆盖率均 43/43，台账一致 |
| 报告门禁 | 正常报告无 `report_enhance_error`，退出码 0；结构变更单测确认抛错并留痕 |
| 兜底门禁 | 正向 sweep=0；反向残留被清且真实账号保留；并行只清 1 次 |
| 台账门禁 | `--project shopping --check` 推导路径成功，退出码 0 |

---

## 24. scenario 引擎取舍（2026-11-25）

### 决策：保留为「能力储备」，不迁主流程

上轮评估留下二选一：要么把支付 / 审批主流程迁进 YAML 引擎提高复用，要么在文档里
明确标为能力储备。**选择后者**。三条理由：

1. **现有两条 YAML 场景与 Python 专项用例刻意重叠**（审批入库 ↔ `test_11`、
   购物车 ↔ `test_05`），引擎已有真实使用证据，不是无人调用的死代码；
2. **主流程用例的断言强度不能退化**：`test_06` 的落库断言 + 软断言、`test_11` 的
   自审 / 驳回 / 撤回负向面、`new_client` 多身份隔离——这些正是 YAML 引擎刻意不支持
   （也不该支持）的能力，迁进去等于把强断言降级成「只看 HTTP/业务信封」；
3. **真正的问题是定位歧义**：§12 原先「正向链路用例不再必须写 Python」的说法容易让
   新人误以为主流程也该写 YAML。删引擎浪费 272 行已测代码，迁主流程降断言质量，
   标注边界才是成本最低、收益最实的做法。

### 适用边界（写用例前先对照）

| 场景 | 用 YAML 场景引擎？ | 说明 |
| --- | --- | --- |
| 线性正向链路：创建 → 审批 → 查询 | ✅ 适合 | 只请求、断言信封、提取变量、清理 |
| 负向 / 异常面（非法值参数化、鉴权异常、越权矩阵） | ❌ 写 Python | parametrize + marker 表达力更强 |
| 落库断言 / 软断言 / 多身份 client 切换 | ❌ 写 Python | 引擎刻意不支持，避免退化成另一个 pytest |
| 条件分支 / 循环 / 按响应决定下一步 | ❌ 写 Python | YAML 不引入控制流 |

### 落地改动

- `framework/scenario.py` 模块 docstring 写明适用边界与「不硬塞 YAML」清单；
- `projects/shopping/testcases/test_15_scenarios.py` 标注为示范入口，列出主流程对应
  的专项用例；`data/scenarios.yaml` 头部注释同步重叠说明；
- `docs/新系统接入指南.md` §6.5 与脚手架模板 `test_04_scenarios.py.tpl`、
  `scenarios.yaml.tpl` 同步定位，新项目从生成起就看到正确用法。

结论：本轮**不改引擎行为、不迁移任何业务用例**，只把定位说清楚。引擎行为由
`framework/tests/test_scenario.py` 16 条单测继续保障，两条示范场景保持原样。

## 25. 契约外置与双向校验（2026-11-26）

契约此前写在 `api_cases.yaml` 的 `response_schemas` 段里，只有消费方自己看得见：
服务方改了字段，消费方只知道「测试红了」，不知道是否违反约定。现在契约独立成
`projects/shopping/data/contracts.yaml`，成为双方共用的可评审资产。

### 契约格式

```yaml
version: 1
project: shopping
contracts:
  health:
    method: GET              # 接口标识，便于服务方定位
    path: /api/health
    token: null              # 仅说明需要哪种角色，不参与校验
    response:                # JSON Schema Draft 7，校验整个响应体
      type: object
      required: [code, data]
      properties:
        code: {type: integer}
        data: {type: object}
```

加载时自检：version 必须为 1、contracts 非空、每条有 method/path/response、
schema 必须是合法 Draft 7——错误直接报出契约名与字段，不会静默跳过。

### 两个方向

| 方向 | 实现 | 时机 |
| --- | --- | --- |
| 消费方校验 | `test_14_contract.py` 用 `assert_contract` 按契约校验真实响应；另有测试校验契约 method/path 已在接口清单登记 | 每次跑 pytest |
| 提供方门禁 | `framework.contract check` 对比基线（push 取 `HEAD^1`、PR 取 `origin/<base_ref>`），破坏性变更返回 1 | CI `Contract compatibility` 步骤（checkout 需 `fetch-depth: 0`） |

### 破坏性变更判定

| 拦截 | 放行 |
| --- | --- |
| 删除字段、删除数组元素约束、删除整条契约 | 新增可选字段、新增契约 |
| 类型改变 | 移除必填约束 |
| 新增必填字段（required 增加） | minimum 变小 / maximum 变大等放宽 |
| minimum/minLength/minItems 变大、maximum/maxLength/maxItems 变小 | enum 扩大 |
| const 改变、enum 缩小、新增/改变 pattern | — |
| 新增 `additionalProperties: false` | — |

### 命令

```bash
python -m framework.contract validate --file projects/shopping/data/contracts.yaml
python -m framework.contract check \
  --current projects/shopping/data/contracts.yaml \
  --baseline /tmp/baseline.yaml       # 0=兼容，1=破坏性变更，2=文件错误
```

反向验证过：删除 `health.data.database` 字段后门禁输出
`契约 health.response.data: 删除字段 database` 并返回 1。

脚手架模板已同步 `data/contracts.yaml.tpl`，新项目生成后即带契约样例。

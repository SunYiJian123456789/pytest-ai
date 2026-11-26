# 脚手架模板使用说明

本目录是 `python -m framework.scaffold <项目名>` 的源模板。脚手架会把所有 `*.tpl` 复制到
`projects/<项目名>/` 并替换占位符；**本文件不是 `.tpl`，不会被复制**，它只解释模板本身怎么用。

生成出来的项目里另有一份 `README.md`（由 `README.md.tpl` 渲染而来），那是给"接手这个项目的人"看的
快速上手卡；本文是给"要基于这套模板接新系统的人"看的机制说明书。

---

## 1. 这套模板解决什么

框架内核（`framework/`）已经把通用能力做完了：请求客户端、响应信封、软断言、覆盖率、缺陷台账、
报告增强、清理、xdist 汇总……业务项目不该重复实现这些。模板的作用是**生成一个只填业务差异、
开箱就能跑通内核全链路的最小项目**，并把已经踩过的坑（Cookie 串号、体检 import 期崩溃、
台账漏登记）在起点就规避掉。

生成的项目与 shopping 项目是同一能力基线的两个实例，内核零改动。

## 2. 三分钟跑起来

```bash
# 1. 生成项目（项目名必须是 Python 标识符，不能以下划线开头）
python -m framework.scaffold order_system \
    --base-url http://127.0.0.1:8080 \
    --prefix ORDER_

# 2. 从仓库根目录复制环境变量样例，按 ORDER_ 前缀填被测地址与账号
cp .env.example .env

# 3. 先收集，确认 import / fixture / 占位符都没问题（这一步不联网）
python -m pytest projects/order_system/testcases --collect-only -q

# 4. 跑用例（启动体检会先探活 + 登录，环境没备好直接一条 ERROR 中止）
python -m pytest -o testpaths=projects/order_system/testcases
```

参数说明：

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--base-url` | `http://127.0.0.1:8080` | 写入 `config.py` 的 `API_BASE_URL` 兜底值 |
| `--prefix` | 项目名大写 + `_` | 环境变量前缀，如 `ORDER_API_BASE_URL` |
| `--force` | 关闭 | 目标目录已存在时覆盖 |

## 3. 生成了哪些文件

| 文件 | 职责 |
| --- | --- |
| `README.md` | 项目快速上手卡（由 `README.md.tpl` 渲染） |
| `config.py` | 被测地址、超时、鉴权、成功码、报告展示信息 |
| `conftest.py` | **五套机制的接入口**（体检 / 配置登记 / 台账 / 清理 / 身份隔离） |
| `helpers.py` | 项目级小工具，如唯一串 `uid()` |
| `data/api_cases.yaml` | 静态用例数据集（路径、非法值、权限矩阵） |
| `data/api_inventory.yaml` | 接口清单（method + path），覆盖率门禁的基准 |
| `data/contracts.yaml` | 响应契约（method + path + JSON Schema），消费方校验与提供方门禁共用 |
| `data/scenarios.yaml` | 线性正向链路场景（YAML 编排） |
| `data/known_defects.yaml` | 已知缺陷台账，空台账 `defects: []` |
| `testcases/test_01_smoke.py` | 冒烟 + 数据驱动范式示例 |
| `testcases/test_02_permissions.py` | 权限矩阵范式示例 |
| `testcases/test_03_contract.py` | 响应契约（JSON Schema）范式示例 |
| `testcases/test_04_scenarios.py` | YAML 场景通用入口，**通常不用改** |

占位符在生成时全部替换，无需手动处理：

- `{{PROJECT}}` → 项目名（`order_system`）
- `{{PROJECT_UPPER}}` → 大写项目名（`ORDER_SYSTEM`，用于报告标题）
- `{{PREFIX}}` → 环境变量前缀（`ORDER_`）
- `{{BASE_URL}}` → 传入的被测地址

## 4. 生成后按什么顺序改

1. **`.env`**：复制根目录 `.env.example`，填 `<前缀>API_BASE_URL`、`AUTH_*` 账号；机器相关的必填键
   （如上传目录）用 `CFG.require('KEY')` 登记到 `config.py`。
2. **`config.py`**：改 `SUCCESS_CODE`、`MODULE_LABELS`、`REPORT_NOTES`；鉴权由 `AuthSpec` 通配，
   一般只配环境变量即可，不必改代码。
3. **`data/api_inventory.yaml`**：把被测接口按 `method + path` 登记进去，覆盖率门禁才有基准。
4. **`data/contracts.yaml`**：按真实响应结构改契约；不需要契约校验的项目可删掉该文件与 `test_03_contract.py`。
5. **`data/api_cases.yaml`**：按真实场景增删数据集（见 §6）。
6. **`conftest.py`**：多角色项目按 §5.5 拆登录；有可扫存储时按 §5.4 注册兜底清理。
7. **`testcases/`**：把示例断言换成真实业务用例，或直接新增文件（约定 `test_` 前缀即可被收集）。

## 5. conftest 的五套机制（重点）

### 5.1 启动体检

`pytest_sessionstart` 在收集用例前跑四项检查，任一必检项失败就**一条 ERROR 中止、用例零执行**，
不让每条用例各报一次 `ConnectionRefused`：

| 检查项 | 内容 | 失败处理 |
| --- | --- | --- |
| 必填配置 | `CFG.require()` 登记的键是否齐 | 中止 |
| 后端可达 | `GET /api/health` 是否连得上、HTTP 200 | 中止 |
| 服务自检 | 健康接口 `status == UP` | `required=False`，只告警 |
| 登录可用 | 用配置账号登录一次 | 中止 |

- 四项只读、快速失败；某项挂掉不影响其余项跑完，一轮把问题说全。
- 前置不满足时抛 `Skipped`，把"没测"与"测了不通过"区分开。
- 探活用短超时且**不重试、不注入 trace**（`retry_enabled=False, trace_enabled=False`），服务没起时
  重试只会翻倍等待。
- 开关：`--collect-only` 不联网；`API_PREFLIGHT_ENABLED=0` 关闭；`API_PREFLIGHT_STRICT=0` 只告警
  不中止。
- 有数据库的项目可照 shopping 加一项 `SELECT 1`，`required` 由 `DB_STRICT` 决定（本地无库可跳过，
  CI 必须可用）。

### 5.2 必填配置登记

`CFG.require()` **不在 import 期抛错**（否则 `--collect-only` 也会崩），只登记缺项，由体检的
"必填配置"检查一次性汇总报出。确需旧的"缺失即报错"行为时设 `API_CONFIG_STRICT=1`。
这是上一轮修过的坑，新项目不要退回 import 期校验。

### 5.3 缺陷台账

`pytest_configure` 里 `defects.configure(path, project='<项目名>')` 绑定台账与收集清单，
两者双向校验：台账登记了但没收集的用例、收集到 xfail 但台账没有的用例，都能被
`--check` 门禁发现。台账按项目名隔离清单文件（`reports/<项目名>_xfail_manifest.json`），
多项目并行不会串。登记方式见 `data/known_defects.yaml` 头部注释，strict xfail 的 reason 里带
`[DEF-xxx]` 编号。

### 5.4 清理：注册式 + 兜底 sweep

- **注册式 `cleaner`**：用例主动登记要删的数据，teardown 统一执行并写入报告汇总。
- **兜底 `sweep`**：补"用例中途异常 / 新人忘了 register"留下的脏数据。`_register_sweeps()` 是扩展点，
  留空不影响注册式清理。有可扫存储时这样注册：

  ```python
  register_sweep('测试用户', discover=db.scan_test_keys,
                 clean=db.delete_test_keys,
                 fallback='按前缀扫描的残留删除失败', prefixes=('ORDER',))
  ```

  `prefixes` 由内核在删除前**二次校验**，`discover` 扫宽了也删不到真实数据；sweep 只在主进程执行，
  xdist worker 不重复清理。

### 5.5 多身份隔离（最容易踩坑）

模板默认只有单账号，`tokens` 里 `'user'` 与 `'admin'` **指向同一个 token**，仅用于演示。
这不是疏忽，而是明确警告：在 Cookie 优先的后端上，请求头写着 A、服务端按 Cookie 认成 B，
会**静默串号**——越权用例可能假绿。真实多角色项目必须：

1. 在 `_fill_tokens()` 里逐角色登录，全部成功再写入 `_TOKENS`，避免留下半套 token 掩盖真正原因；
2. `tokens` / `role_tokens` 返回各角色独立 token；
3. 同时存在多个身份的用例**不要用共享的 `api` fixture**（它的 Session 会累积 `Set-Cookie`），
   改用 `new_client`：

   ```python
   def test_cross_user(new_client, tokens):
       alice = new_client(tokens['user'])
       bob = new_client(tokens['admin'])
       # 各自独立 cookie jar，互不串号
   ```

`new_client` 是工厂，每次创建独立客户端，fixture 结束统一 `close()`。
`_TOKENS` 用 `state.namespace('<项目名>.tokens')` 隔离，体检登录与 fixture 共用一次登录，
不重复请求。

## 6. 写用例的三种范式

| 范式 | 什么时候用 | 落点 |
| --- | --- | --- |
| 数据驱动 | 一批同构输入（路径、非法值、权限） | `data/api_cases.yaml` + `@pytest.mark.parametrize` |
| 契约校验 | 响应结构约定（服务方与消费方共用） | `data/contracts.yaml` + `test_03` 通用入口 |
| YAML 场景 | **线性正向链路**（无分支、无落库断言、单身份） | `data/scenarios.yaml` + `test_04` 通用入口 |
| Python 强断言 | 负向面、落库核对、软断言、多身份、条件分支 | 自己写 `test_*.py` |

场景引擎是**能力储备**，不是主流程的替代品。复杂主流程请写 Python，不要用 YAML 把强断言降级成
"只看 HTTP / 业务信封"。

`data/api_cases.yaml` 里的数据集直接喂给用例：

- `smoke_paths` → `test_01` 的路径探活
- `invalid_ids` → 非法 ID 参数化
- `permission_matrix` → `test_02` 的角色 × 接口 × 期望结果（角色取自 `role_tokens`）

契约单独放 `data/contracts.yaml`，由 `test_03` 按契约名校验响应。
契约变更的兼容性门禁见 §9；ci 用上一版契约作基线，删字段/改类型会直接失败。

多字段校验用软断言，一次报全，别让第一个字段失败挡住后面的信息：

```python
def test_fields(api, soft):
    result = api.get('/api/xxx')
    soft.ok(result, '查询成功')
    soft.equal(result.code, 200, '业务码')
    soft.assert_all()
```

## 7. fixtures 速查

| fixture | 作用域 | 用途 |
| --- | --- | --- |
| `api` | function | 共享客户端，注入登录 cookies 与 token，带报告 extras |
| `new_client` | function | 独立 cookie jar 工厂，多身份 / 越权用例用 |
| `token` / `tokens` / `role_tokens` | session | 登录态与角色映射 |
| `auth_state` | session | 体检登录态复用，未体检则在此登录 |
| `cleaner` | function | 注册式清理，teardown 统一执行 |
| `ctx` | function | 依赖链：`remember` 上游值、`render` 下游参数 |
| `scenario_variables` | function | YAML 场景的 `${token}` / `${uid}`，每条场景唯一 |
| `soft` | function | 软断言收集器（定义在根 `conftest.py`，所有项目可用） |

通用断言在 `framework.assertions`：`assert_ok` / `assert_status` / `assert_code` /
`assert_message_contains` / `assert_fields` / `assert_elapsed` 等。

## 8. 运行与报告

```bash
# 只跑本项目
python -m pytest -o testpaths=projects/order_system/testcases

# 并行（内核已做分区注册表与分片汇总，worker 临时文件会自动清理）
python -m pytest -o testpaths=projects/order_system/testcases -n 4
```

报告输出到 `reports/`：`report.html`（仪表盘、请求明细、失败请求存档、清理汇总）、
`run_summary.json`、`junit.xml` 及覆盖率数据，均由内核自动生成，业务项目无需关心。
报告增强层有结构契约校验：JSON blob 损坏或 HTML 骨架缺失会直接抛错并写入
`run_summary.json` 的 `report_enhance_error`，CI 应检查此字段为空。

## 9. CI 门禁清单

按 shopping 的 `.github/workflows/api-tests.yml` 复制改造（runner、环境变量前缀、端口按项目改）：

```bash
# 1. 内核单测（不依赖被测服务）
python -m pytest framework/tests -q

# 2. 覆盖率（effective 口径，出现清单外请求即失败；阈值按需加 --min 80）
python -m framework.coverage --format terminal --metric effective --fail-on-unexpected

# 3. 契约双向校验（消费方在 test_03 校验响应；这里做提供方门禁）
python -m framework.contract validate --file projects/order_system/data/contracts.yaml
git show 'HEAD^:projects/order_system/data/contracts.yaml' > /tmp/baseline.yaml
python -m framework.contract check \
  --current projects/order_system/data/contracts.yaml --baseline /tmp/baseline.yaml

# 4. 缺陷台账（先生成收集清单，再校验一致性）
python -m pytest --collect-only -q > /dev/null
python -m framework.defects --project order_system --check

# 5. 报告增强校验
#    检查 reports/run_summary.json 不含 report_enhance_error
```

CI 环境记得从 `.env.example` 生成 `.env`，并按需设 `API_CONFIG_STRICT` / `DB_STRICT` /
`API_PREFLIGHT_STRICT`。

## 10. 避坑清单

- [ ] 项目名是合法 Python 标识符，且不与 `framework` / `projects` / `reports` 冲突
- [ ] 环境变量用 `<前缀>` 开头，地址写在 `.env`，不写死在代码里
- [ ] 机器相关的必填键已用 `CFG.require()` 登记（不是 import 期校验）
- [ ] `api_inventory.yaml` 已登记全部被测接口，否则覆盖率会有"清单外请求"
- [ ] 多角色项目已拆独立登录，`tokens` 不再是同 token；越权用例用 `new_client`
- [ ] 有可扫存储的项目已在 `_register_sweeps()` 注册兜底清理并配好 `prefixes`
- [ ] 台账里每条已知缺陷都有对应的 strict xfail，reason 带 `[DEF-xxx]`
- [ ] YAML 场景只放线性正向链路，复杂流程写 Python
- [ ] CI 从 `.env.example` 生成 `.env`，四项门禁都加上

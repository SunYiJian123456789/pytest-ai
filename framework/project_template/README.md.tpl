# {{PROJECT}} 接口自动化测试

由 `python -m framework.scaffold {{PROJECT}}` 生成，复用仓库根目录的 `framework/` 内核。

## 需要改的地方

1. `config.py`：被测地址前缀 `{{PREFIX}}` 对应的环境变量、账号、业务成功码。鉴权由 `AuthSpec` 通配，通常只需在 `.env` 配 `{{PREFIX}}AUTH_*`，不必改代码。
2. `.env`（复制根目录 `.env.example`）：填写 `{{PREFIX}}API_BASE_URL` 等，不写进代码。
3. `data/api_cases.yaml`：按系统真实场景增删数据集。
4. `data/api_inventory.yaml`、`data/scenarios.yaml`、`data/known_defects.yaml`：接口清单、线性正向场景、已知缺陷台账（空台账，随缺陷登记补充）。
5. `conftest.py`：`tokens` 目前是单账号演示（`user`/`admin` 同 token）——**多角色项目必须改成分别登录**，并用 `new_client` 给每个身份独立客户端，否则 Cookie 优先的后端会静默串号；`_register_sweeps()` 按需注册兜底清理。
6. `testcases/`：把示例断言替换成真实业务用例；通用断言在 `framework.assertions`。

## 运行

```bash
python -m pytest -o testpaths=projects/{{PROJECT}}/testcases
```

启动体检会先检查配置/服务/登录，环境没备好直接一条 ERROR 中止；`--collect-only` 不联网。
报告输出到 `reports/report.html`，仪表盘、请求明细、失败请求存档、清理汇总均由 framework 自动生成。

## CI 门禁清单（照 shopping 的 `.github/workflows/api-tests.yml` 复制改造）

1. 内核单测：`python -m pytest framework/tests -q`（不依赖被测服务）；
2. 覆盖率：`python -m framework.coverage --format terminal --metric effective --fail-on-unexpected`（阈值加 `--min N`）；
3. 缺陷台账：`python -m pytest --collect-only -q >/dev/null` 后
   `python -m framework.defects --project {{PROJECT}} --check`；
4. 报告增强校验：检查 `reports/run_summary.json` 无 `report_enhance_error`。

CI 环境记得从 `.env.example` 生成 `.env`，并按需设 `API_CONFIG_STRICT` / `DB_STRICT` / `API_PREFLIGHT_STRICT`。

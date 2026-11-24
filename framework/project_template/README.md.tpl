# {{PROJECT}} 接口自动化测试

由 `python -m framework.scaffold {{PROJECT}}` 生成，复用仓库根目录的 `framework/` 内核。

## 需要改的地方

1. `config.py`：被测地址前缀 `{{PREFIX}}` 对应的环境变量、账号、业务成功码。鉴权由 `AuthSpec` 通配，通常只需在 `.env` 配 `{{PREFIX}}AUTH_*`，不必改代码。
2. `.env`（复制根目录 `.env.example`）：填写 `{{PREFIX}}API_BASE_URL` 等，不写进代码。
3. `data/api_cases.yaml`：按系统真实场景增删数据集。
4. `testcases/`：把示例断言替换成真实业务用例；通用断言在 `framework.assertions`。

## 运行

```bash
python -m pytest -o testpaths=projects/{{PROJECT}}/testcases
```

报告输出到 `reports/report.html`，仪表盘、请求明细、失败请求存档、清理汇总均由 framework 自动生成。

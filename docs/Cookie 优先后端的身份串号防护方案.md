# Cookie 优先后端的身份串号防护方案

> 适用：后端「Cookie 优先于 `Authorization` 头」的系统（shopping 的 `CookieUtil.token`
> 就是先读 Cookie、再用请求头兜底）。本文回答一个具体问题：**同一个测试客户端先后
> 用两个身份时，请求头写着 A、服务端却按 Cookie 认成 B，导致用例静默假绿，怎么办。**

---

## 1. 根因：一个客户端 = 一个 Cookie jar

`ApiClient` 内部持有一个 `requests.Session`。登录、注册返回的 `Set-Cookie` 会
一直留在这个 Session 里，直到显式清空或客户端销毁。

```text
ApiClient（共享 Session）
  ├─ Cookie: session=alice    ← 第一次登录写入，不会自动消失
  └─ Authorization: Bearer bob ← 第二次请求显式传的 token

后端 CookieUtil.token：先读 Cookie → 认成 alice
结果：断言在测 bob，实际请求的是 alice → 静默假绿
```

关键在「静默」：HTTP 200、业务 code 成功、断言也可能过，只是**测错了身份**。
越权用例若因此假绿，比失败更危险。

## 2. 四层防护

框架提供四层，从「必须靠人」到「框架自动」依次增强。建议全部启用。

### 第 1 层：隔离（首选，根本解）

**一个身份 = 一个客户端。** 每个身份开独立的 `ApiClient`，各自独立 Cookie jar，
从物理上杜绝串号。

```python
def test_cross_user_access(new_client, role_tokens):
    alice = new_client(role_tokens['user'])   # 独立 Session
    bob = new_client(role_tokens['admin'])    # 独立 Session

    # 用 alice 的 token 访问 bob 的资源，断言 403
    assert alice.get('/api/orders/%s' % bob_order_id).code == 403
```

`new_client` 是工厂 fixture，每次创建一个新客户端，fixture 结束统一 `close()`。
模板与 shopping 项目的 conftest 都已提供。

### 第 2 层：清理（复用客户端时必做）

确实要在同一客户端上换身份时，**切换前清空 Cookie**：

```python
api.clear_cookies()                    # 清空 session.cookies + 重置身份追踪
api.default_token = other_token        # 再切换 token
```

`clear_cookies()` 会一并重置内部身份追踪，因此清理后切换不会被守护误报。

### 第 3 层：检测（框架自动，默认开启）

内核在 `ApiClient.request()` 发出请求前自动检测「换 token 但 Cookie 未清」
的高危条件。三种模式，通过环境变量 `API_COOKIE_GUARD` 或构造参数 `cookie_guard` 控制：

| 模式 | 行为 | 适用场景 |
| --- | --- | --- |
| `off` | 不检查 | 后端确认 Header 优先，或存量用例暂时无法清理 |
| `warn`（**默认**） | 发 `UserWarning`，不中断 | 本地日常，把静默风险变成可见告警 |
| `strict` | 抛 `IdentityConflictError`，用例立即失败 | CI 门禁，杜绝假绿 |

```bash
# CI 里设 strict，任何身份混用都直接失败
API_COOKIE_GUARD=strict python -m pytest -n 4
```

检测同时覆盖两种触发点：

- **显式传 token 切换**：同一客户端先带 token A 请求，再显式传 token B，且会话带 Cookie；
- **二次登录**：`login()` 已登录身份 A，又登录身份 B，且会话带 Cookie。

为避免误报，以下情况**不触发**：

- 构造时给了 `default_token`（已确立身份）后首次显式传 token——视为正常用法；
- 注册后首次用注册返回的 token 请求——属同一身份；
- 同一 token 重复请求；
- 会话里没有 Cookie（后端不写 Cookie 时无从串号）；
- 只改了 `default_token`、未显式传 token 的请求（由 `login()` 路径单独把关）。

异常信息会给出修复指引（用 `new_client` 或 `clear_cookies`），并说明如何关闭检查。

### 第 4 层：规范（约定与模板）

- 越权、会话隔离、权限矩阵用例**只用 `new_client`**，不碰共享 `api` fixture；
- 写坏 token / 缺少 token 的鉴权负向用例也用 `new_client()` 起干净会话——
  否则服务端按 Cookie 认成合法用户，401 用例会假绿（shopping 实测踩过）；
- 权限矩阵的 `check_permission` 若在同一客户端上切角色 token，必须用
  `new_client` 提供的客户端，不能复用共享 `api`。

## 3. 接入新系统时的操作清单

1. **确认后端是否 Cookie 优先**：看鉴权工具类（如 `CookieUtil.token`），
   若先读 Cookie 再读 Header，按本文全量防护；若只认 Header，风险较低。
2. **CI 开 strict**：workflow 的 job env 加 `API_COOKIE_GUARD: strict`。
3. **模板 conftest 的 `tokens` 拆成独立登录**：脚手架默认只有单账号，
   `user`/`admin` 指向同一 token（占位）。真实项目必须分别登录，
   每个角色用 `new_client()` 独立会话。
4. **多身份用例改造**：按第 1 层把共享 `api` 换成 `new_client(...)`。
5. **本地先跑 warn**：观察告警定位还有哪些用例在混用身份，逐个改完再开 strict。
   workflow 默认未强开 strict（避免存量用例误报直接把 CI 跑红）——确认告警归零后，
   在 `.github/workflows/api-tests.yml` 的 job `env` 里加 `API_COOKIE_GUARD: strict` 即可。

## 4. 验证

内核单测 `framework/tests/test_identity_guard.py` 覆盖 14 条场景：

- 三档模式行为（off 静默 / warn 告警 / strict 失败）；
- 首次 token、同 token 重复、无 Cookie、清 Cookie 后切换、注册后首用返回 token
  五类不误报场景；
- 二次登录不同身份、显式 token 切换两类触发场景；
- 环境变量配置与非法模式拒绝。

```bash
python -m pytest framework/tests/test_identity_guard.py -o addopts= -q
# 14 passed
```

## 5. 边界与说明

- 守护靠「token 字符串不同」判定身份切换，**无法识别同一账号的不同 token**
  （如刷新后的新 token）——这种情况请显式 `clear_cookies()` 或用 `new_client`。
- `auth.mode=cookie` 下不注入 Header，守护不适用；该模式本来就只能靠
  `new_client` 隔离。
- 守护默认 `warn` 是为了兼容既有用例；新项目接入时建议在 CI 直接开 `strict`。

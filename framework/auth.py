# -*- coding: utf-8 -*-
"""通用鉴权描述（framework 内核）。

把「怎么登录、token 在哪、怎么带上去」从用例代码里抽出来，交给 AuthSpec。
换系统时只改 .env 的 <前缀>AUTH_* 变量，不再改 conftest 或客户端代码。

支持的模式：
- bearer / header：请求头带 token（默认 Authorization: Bearer <token>）
- cookie：登录后由 requests.Session 自动携带 Cookie，不注入请求头
- auto：登录响应里能提取到 token 就走 header，否则有 Cookie 就走 cookie
- none：不带任何鉴权（用于公开接口测试）
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from framework.config import Settings


@dataclass
class AuthSpec:
    mode: str = 'bearer'
    login_path: str = '/api/auth/login'
    username_field: str = 'username'
    password_field: str = 'password'
    token_field: str = 'token'
    token_path: str = ''          # 点分路径，如 data.access_token；留空则用 token_field
    header: str = 'Authorization'
    scheme: str = 'Bearer'
    cookie_name: str = ''         # cookie 模式下关心的 cookie 名（用于报告与断言）
    extra_login_body: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, settings: Settings, prefix: str = 'AUTH_') -> 'AuthSpec':
        """从项目配置读取 <项目前缀>AUTH_* 环境变量。"""
        return cls(
            mode=settings.get(prefix + 'MODE', 'bearer'),
            login_path=settings.get(prefix + 'LOGIN_PATH', '/api/auth/login'),
            username_field=settings.get(prefix + 'USERNAME_FIELD', 'username'),
            password_field=settings.get(prefix + 'PASSWORD_FIELD', 'password'),
            token_field=settings.get(prefix + 'TOKEN_FIELD', 'token'),
            token_path=settings.get(prefix + 'TOKEN_PATH', ''),
            header=settings.get(prefix + 'HEADER', 'Authorization'),
            scheme=settings.get(prefix + 'SCHEME', 'Bearer'),
            cookie_name=settings.get(prefix + 'COOKIE_NAME', ''),
        )

    def token_from(self, payload: Any) -> Optional[str]:
        """按 token_path / token_field 提取 token，支持嵌套结构。

        同时兼容两种常见包装：token 在顶层，或在 ``data`` 里（由 token_path 指定）。
        """
        path = self.token_path or self.token_field
        roots = [payload]
        if isinstance(payload, dict) and isinstance(payload.get('data'), dict):
            roots.append(payload['data'])
        for root in roots:
            node: Any = root
            for part in path.split('.') if path else []:
                node = node.get(part) if isinstance(node, dict) else None
            if node is not None and node != '':
                return str(node)
        return None

    def uses_header(self) -> bool:
        """auto 在未探测前也按 header 处理，显式传 token 时同理。"""
        return self.mode not in ('cookie', 'none')

    def header_value(self, token: str) -> str:
        return (self.scheme + ' ' + token).strip() if self.scheme else token

    def login_body(self, username: str, password: str) -> Dict[str, Any]:
        body = {
            self.username_field: username,
            self.password_field: password,
        }
        body.update(self.extra_login_body)
        return body

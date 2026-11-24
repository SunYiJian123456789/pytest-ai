# -*- coding: utf-8 -*-
"""鉴权异常输入：篡改 / 乱码 / 超长 / 注入式 token 一律不得放行。

**必须用全新会话**：本后端 ``CookieUtil.token`` 是 Cookie 优先、Authorization 兜底，
而注册用户会拿到 ``Set-Cookie``。若复用注册过用户的客户端，cookie 会盖掉放进请求头
的坏 token，用例会假绿（实测确实如此）。所以这里统一用 ``new_client()`` 起干净会话。
"""
import pytest

from projects.shopping.helpers import register_user


@pytest.fixture
def valid_token(api, cleaner):
    """一个真实可用的 token，用来派生「坏 token」并做有效对照。"""
    return register_user(api, cleaner, prefix='APIATH')['token']


def _tamper(token):
    return token[:-1] + ('0' if token[-1] != '0' else '1')


@pytest.mark.parametrize('label,bad_token', [
    ('篡改一个字符', _tamper),
    ('随机乱码 32 位', lambda token: 'Z' * 32),
    ('超长 2000 字符', lambda token: 'A' * 2000),
    ('注入式字符串', lambda token: "' OR '1'='1"),
], ids=['篡改', '乱码', '超长', '注入'])
@pytest.mark.auth
def test_me_rejects_malformed_token(new_client, valid_token, label, bad_token):
    """坏 token 必须被识别为未登录，且响应里不能漏出任何用户信息。"""
    client = new_client()
    result = client.get('/api/auth/me', token=bad_token(valid_token))

    assert result.code == 401, '%s 应判未登录，实际 code=%s：%s' % (
        label, result.code, result.describe(),
    )
    assert result.status < 500, '%s 不应打成服务端错误：%s' % (label, result.describe())
    assert result.data in (None, {}), '%s 的 401 响应不应携带用户数据：%r' % (label, result.data)


@pytest.mark.auth
def test_me_rejects_missing_token(new_client):
    """完全不带凭证时同样必须是 401，而不是放行或 500。"""
    result = new_client().get('/api/auth/me')
    assert result.code == 401, '未携带 token 应判未登录：%s' % result.describe()
    assert result.data in (None, {}), '未登录响应不应携带用户数据：%r' % (result.data,)


@pytest.mark.auth
def test_valid_token_still_passes(new_client, valid_token):
    """对照用例：证明上面的 401 是「识别出坏 token」，而不是接口恒返回 401。"""
    result = new_client().get('/api/auth/me', token=valid_token)
    assert result.ok, '有效 token 应通过：%s' % result.describe()
    assert result.data.get('username'), '应返回当前用户信息：%r' % (result.data,)

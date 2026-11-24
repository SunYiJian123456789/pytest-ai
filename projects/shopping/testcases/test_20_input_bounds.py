# -*- coding: utf-8 -*-
"""超长输入与特殊字符：长度上限、通配符转义、注入载荷、不崩 5xx。

长度边界来自库表列宽：``sys_user.username varchar(64)``、``product.name varchar(128)``、
``product.subtitle varchar(255)``、``description text(65535 字节)``。
有前置校验的走 400 业务码；只靠库表兜底的会撞成 500——后者是缺陷，用 xfail 登记。
"""
import pytest

from projects.shopping.helpers import product_payload, uid


def _submit(api, tokens, cleaner, payload):
    result = api.post('/api/admin/products', json_body=payload, token=tokens['admin'])
    if isinstance(result.data, dict) and result.data.get('id'):
        cleaner.approval(result.data['id'])
    return result


@pytest.mark.xfail(
    strict=True,
    reason='已知缺陷（后端）：注册接口没有用户名校验，sys_user.username 是 varchar(64)，'
           '65 个字符起触发 SQL 数据过长异常，未处理 → 500 默认错误页。'
           '64 字符可成功、65 字符必 500，边界已实测确认。应有 400「用户名长度不合法」。',
)
def test_register_rejects_oversize_username(api):
    """用户名超过列宽应被 400 拒绝，而不是服务端 500。"""
    result = api.post('/api/auth/register', json_body={
        'username': 'U' * 65, 'password': 'Test@123456',
    })
    assert result.status < 500, '超长用户名不应打成 5xx：%s' % result.describe()
    assert result.code == 400, '超长用户名应返回 400，实际 %s' % result.code


def test_product_rejects_oversize_name(api, tokens, cleaner):
    """商品名上限 128，超长应有明确业务提示而不是截断或入库。"""
    result = _submit(api, tokens, cleaner, product_payload(uid('LONG') + 'N' * 129))
    assert result.code == 400, result.describe()
    assert '128' in result.message, '提示应指出上限 128，实际 %r' % result.message


def test_product_rejects_oversize_subtitle(api, tokens, cleaner):
    """副标题上限 255。"""
    result = _submit(api, tokens, cleaner,
                     product_payload(uid('LONG'), subtitle='副' * 256))
    assert result.code == 400, result.describe()
    assert '255' in result.message, '提示应指出上限 255，实际 %r' % result.message


@pytest.mark.xfail(
    strict=True,
    reason='已知缺陷（后端）：商品描述没有长度校验，description 是 TEXT（65535 字节），'
           '25000 个汉字约 75000 字节直接撞库，未处理 → 500 默认错误页。'
           '应在入库前校验并返回 400。',
)
def test_product_rejects_oversize_description(api, tokens, cleaner):
    """描述超出 TEXT 列容量应被 400 拒绝，而不是 500。"""
    result = _submit(api, tokens, cleaner,
                     product_payload(uid('LONG'), description='述' * 25000))
    assert result.status < 500, '超长描述不应打成 5xx：%s' % result.describe()
    assert result.code == 400, '超长描述应返回 400，实际 %s' % result.code


@pytest.mark.parametrize('keyword,label', [
    ('%', '百分号通配'),
    ('_', '下划线通配'),
    ("' OR '1'='1", 'SQL 注入载荷'),
])
def test_keyword_wildcards_and_injection_are_inert(api, tokens, keyword, label):
    """LIKE 通配符与注入载荷都必须被当成普通字符：不能匹配全量、不能报错。"""
    result = api.get('/api/admin/products', params={'keyword': keyword},
                     token=tokens['admin'])
    assert result.status < 500, '%s 不应打成 5xx：%s' % (label, result.describe())
    assert result.code == 200, '%s 应正常返回 200，实际 %s' % (label, result.code)
    assert result.data['total'] == 0, (
        '%s 被当成了通配/注入：本库没有含该字面量的商品，结果应为 0 条，实际 %s 条'
        % (label, result.data['total'])
    )


def test_overlong_keyword_is_client_error_not_500(api, tokens):
    """超长关键词（1000 汉字，URL 远超 8KB 头限制）应是客户端错误，不能 5xx。"""
    result = api.get('/api/admin/products', params={'keyword': '关' * 1000},
                     token=tokens['admin'])
    assert result.status < 500, '超长关键词不应打成 5xx：%s' % result.describe()
    assert result.status == 400, '超长请求应被 400 拒绝，实际 %s' % result.status


def test_special_characters_are_stored_verbatim(api, tokens, cleaner):
    """引号、尖括号、emoji 混排的商品名：要么明确拒绝，要么原样保存，不能 5xx 或悄悄截断。"""
    name = '%s<img src=x onerror=alert(1)>🎧"\'%s' % (uid('SPEC'), uid('X'))
    assert len(name) <= 128, '构造的名称需在 128 字以内，实际 %d' % len(name)

    result = _submit(api, tokens, cleaner, product_payload(name))
    assert result.status < 500, '特殊字符不应打成 5xx：%s' % result.describe()
    assert result.code in (200, 400), '应成功或明确拒绝，实际 code=%s' % result.code
    if result.code == 200:
        assert result.data['name'] == name, (
            '特殊字符应原样入库，不得被截断或转义：期望 %r，实际 %r'
            % (name, result.data.get('name'))
        )

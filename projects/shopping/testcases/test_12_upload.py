# -*- coding: utf-8 -*-
"""本地图片上传接口：类型校验与静态回源。"""
import base64

import pytest

# 1x1 透明 PNG
PNG_BYTES = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
)


@pytest.mark.xfail(
    strict=True,
    reason='已知缺陷（后端）：非 multipart 请求缺 file part 时，Spring 的 MultipartException '
           '无人处理，直接返回 500 并回落到默认错误页（无 code/message 包装）。'
           '正确行为应为 400 或 415。修复后本用例会变成 XPASS 并被 strict 判失败，'
           '届时删除本标记即可。',
)
def test_upload_requires_file(api):
    """缺少 multipart body 属于客户端请求错误，应由 4xx 拒绝，而不是服务端 500。"""
    result = api.post('/api/upload')
    assert result.ok is False, '缺少 file part 不应被认为上传成功：%r' % (result,)
    assert result.status in (400, 415), (
        '非 multipart 请求应返回 400/415（客户端错误），实际 %s——5xx 说明服务端未处理异常：%s'
        % (result.status, result.describe())
    )


def test_upload_rejects_empty_file(api):
    """file part 存在但内容为空 → 业务拒绝，且不产生落盘文件。"""
    result = api.post('/api/upload', files={'file': ('empty.png', b'', 'image/png')})
    assert result.code == 400, result
    assert '空' in result.message, result.message


def test_upload_rejects_non_image(api):
    result = api.post('/api/upload', files={
        'file': ('note.txt', b'not an image', 'text/plain'),
    })
    assert result.code == 400 and '图片' in result.message, result


def test_upload_image_and_fetch_from_backend(api, cleaner):
    result = api.post('/api/upload', files={
        'file': ('api-auto.png', PNG_BYTES, 'image/png'),
    })
    assert result.ok, result
    path = result.data
    assert path.startswith('/images/') and path.endswith('.png'), path
    cleaner.upload(path)

    fetched = api.get(path)
    assert fetched.status == 200, fetched
    assert fetched.content_type.startswith('image/'), fetched.content_type

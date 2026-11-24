# -*- coding: utf-8 -*-
"""本地图片上传接口：类型校验与静态回源。"""
import base64

# 1x1 透明 PNG
PNG_BYTES = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
)


def test_upload_requires_file(api):
    # 缺少 multipart part 时 Spring 在进入 Controller 前就拒绝，返回 400/500 均属正常防护。
    result = api.post('/api/upload')
    assert result.status in (400, 500), result
    assert result.ok is False, result


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

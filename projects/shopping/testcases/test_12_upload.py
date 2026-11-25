# -*- coding: utf-8 -*-
"""本地图片上传接口：类型校验、大小上限、文件名安全与静态回源。"""
import base64
import re

import pytest

# 1x1 透明 PNG
PNG_BYTES = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
)

# 服务端自行生成的落盘名：upload-<12 位十六进制>.<由 MIME 推导的扩展名>
SAFE_NAME = re.compile(r'^/images/upload-[0-9a-f]{12}\.(png|jpg|webp|gif)$')


@pytest.mark.xfail(
    strict=True,
    reason='[DEF-001] 已知缺陷（后端）：非 multipart 请求缺 file part 时，'
           'Spring 的 MultipartException 无人处理，直接返回 500 并回落到默认错误页'
           '（无 code/message 包装）。正确行为应为 400 或 415。'
           '修复后本用例会 XPASS，请按 DEF-001 台账同时删除标记并改状态为 fixed。',
)
def test_upload_requires_file(api):
    """缺少 multipart body 属于客户端请求错误，应由 4xx 拒绝，而不是服务端 500。"""
    result = api.post('/api/upload')
    assert result.ok is False, '缺少 file part 不应被认为上传成功：%s' % result.describe()
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


@pytest.mark.xfail(
    strict=True,
    reason='[DEF-002] 已知缺陷（后端）：application.yml 配了 multipart.max-file-size=10MB，'
           '超限时 Spring 抛 MaxUploadSizeExceededException，项目没有 @ControllerAdvice 处理，'
           '直接回落 500 默认错误页（无 code/message）。11MB、20MB 实测均返回 500。'
           '正确行为应为 413 Payload Too Large（或 400）。',
)
def test_upload_rejects_oversize_file(api):
    """超过 multipart 上限（10MB）应被 4xx 拒绝，而不是 500。"""
    oversize = PNG_BYTES + b'\x00' * (11 * 1024 * 1024)
    result = api.post('/api/upload', files={'file': ('huge.png', oversize, 'image/png')})
    assert result.status in (400, 413), (
        '超出 10MB 上限应返回 413/400，实际 %s——5xx 说明异常未被处理：%s'
        % (result.status, result.describe())
    )


def test_upload_derives_extension_from_mime_not_filename(api, cleaner):
    """扩展名与 MIME 不符时，落盘名以服务端为准：忽略客户端文件名，按 MIME 定扩展名。"""
    result = api.post('/api/upload', files={
        'file': ('note.txt', PNG_BYTES, 'image/png'),
    })
    assert result.ok, result.describe()
    path = result.data
    cleaner.upload(path)

    assert SAFE_NAME.match(path), '落盘名应由服务端生成（upload-<hex>.<扩展名>），实际 %r' % (path,)
    assert path.endswith('.png'), '扩展名应按 image/png 推导为 .png，实际 %r' % (path,)
    assert 'note' not in path and '.txt' not in path, '客户端文件名不应进入落盘路径：%r' % (path,)


def test_upload_filename_traversal_is_neutralised(api, cleaner):
    """文件名带 ../ 时不得写到目标目录之外，返回路径必须是干净的 /images/ 相对路径。"""
    result = api.post('/api/upload', files={
        'file': ('../../evil.png', PNG_BYTES, 'image/png'),
    })
    assert result.ok, result.describe()
    path = result.data
    cleaner.upload(path)

    assert '..' not in path, '返回路径不得包含路径穿越片段：%r' % (path,)
    assert not path.startswith('/images/../'), '不得跳出 images 目录：%r' % (path,)
    assert SAFE_NAME.match(path), '落盘名应由服务端生成，实际 %r' % (path,)
    assert 'evil' not in path, '恶意文件名不应被沿用：%r' % (path,)

    fetched = api.get(path)
    assert fetched.status == 200, '落盘后可回源：%s' % fetched.describe()
    assert fetched.content_type.startswith('image/'), fetched.content_type

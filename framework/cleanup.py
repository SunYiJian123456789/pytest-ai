# -*- coding: utf-8 -*-
"""注册式数据清理器（framework 内核）。

业务项目只需把「怎么删」注册进来，框架负责统一执行、结构化记录、失败可见：
报告顶部会展示清理汇总（成功 / 跳过 / 失败），残留数据不再被静默吞掉。

示例::

    cleaner = CleanupRegistry()
    cleaner.register('delete order %s' % no, lambda: api.delete('/api/orders/%s' % no))
    cleaner.run()
"""
import json
import os
from pathlib import Path

CLEANUP_LOG: list[dict] = []


def dump_log(path: Path):
    """xdist worker 退出时把本进程的清理记录落盘，供主进程汇总。"""
    Path(path).write_text(
        json.dumps(CLEANUP_LOG, ensure_ascii=False), encoding='utf-8',
    )


def load_logs(directory: Path):
    """主进程合并所有 worker 的清理记录并删除临时文件。"""
    root = Path(directory)
    for file in sorted(root.glob('.cleanup_*.json')):
        try:
            CLEANUP_LOG.extend(json.loads(file.read_text(encoding='utf-8')))
        except Exception:  # noqa: BLE001 - 单个损坏文件不应影响报告
            pass
        finally:
            file.unlink(missing_ok=True)


def record(action: str, result, fallback: str = '') -> dict:
    """把一次清理动作的结果记入全局汇总。"""
    if getattr(result, 'skipped', False):
        state, detail = 'SKIP', (getattr(result, 'error', '') or 'client not found')[:200]
    elif result is None or getattr(result, 'ok', False):
        state, detail = 'OK', ''
    else:
        msg = getattr(result, 'message', None) or getattr(result, 'error', '') or fallback
        state, detail = 'FAIL', (msg or 'unknown error')[:200]
    entry = {'action': action, 'state': state, 'detail': detail}
    CLEANUP_LOG.append(entry)
    return entry


class CleanupRegistry:
    """按注册顺序执行清理动作；业务层可继承并添加语义化方法。"""

    def __init__(self):
        self._actions: list[tuple] = []

    def register(self, action: str, func, fallback: str = ''):
        self._actions.append((action, func, fallback))
        return self

    def run(self):
        for action, func, fallback in self._actions:
            try:
                record(action, func(), fallback)
            except Exception as exc:  # noqa: BLE001 - 单项失败不影响其他清理
                record(action, None, str(exc))
        return CLEANUP_LOG

    @property
    def actions(self):
        return list(self._actions)


def cleanup_banner_html(extra_errors=None) -> str:
    """把清理汇总与报告增强失败渲染成报告顶部的状态卡片。"""
    total = len(CLEANUP_LOG)
    failed = [row for row in CLEANUP_LOG if row['state'] == 'FAIL']
    skipped = [row for row in CLEANUP_LOG if row['state'] == 'SKIP']
    extra_errors = list(extra_errors or [])
    if not total and not extra_errors:
        return ''
    parts = ['<div class="enh-cleanup" style="margin:12px 0;padding:12px 16px;'
             'border:1px solid #d1d5db;border-radius:10px;background:#f9fafb;'
             'font:13px/1.6 system-ui,sans-serif;color:#1f2937">']
    parts.append('<b style="font-weight:600">测试后清理汇总</b> · 执行 %d 项' % total)
    parts.append(' · <span style="color:#15803d">成功 %d</span>' % (total - len(failed) - len(skipped)))
    parts.append(' · <span style="color:#b45309">跳过 %d</span>' % len(skipped))
    parts.append(' · <span style="color:#b91c1c">失败 %d</span>' % len(failed))
    details = failed + skipped
    if details:
        parts.append('<ul style="margin:8px 0 0 18px;padding:0">')
        for row in details:
            tone = '#b91c1c' if row['state'] == 'FAIL' else '#b45309'
            parts.append('<li style="color:%s">[%s] %s — %s</li>'
                         % (tone, row['state'], row['action'], row['detail']))
        parts.append('</ul>')
    for error in extra_errors:
        parts.append('<p style="margin:8px 0 0;color:#b91c1c">'
                     '报告增强失败，当前为原始 pytest-html 报告：%s</p>' % error)
    parts.append('</div>')
    return ''.join(parts)


def inject_banner(target: Path, extra_errors=None):
    """在报告 </body> 前插入清理汇总横幅（幂等）。"""
    banner = cleanup_banner_html(extra_errors)
    if not banner:
        return
    try:
        text = Path(target).read_text(encoding='utf-8')
        if 'enh-cleanup' in text:
            return
        Path(target).write_text(
            text.replace('</body>', banner + '</body>'), encoding='utf-8',
        )
    except Exception:  # noqa: BLE001 - 横幅注入失败不应影响测试结论
        pass


def remove_uploaded_files(directory: str | Path, paths) -> None:
    """删除本轮上传的文件；业务层注册后由框架统一记录结果。"""
    root = Path(directory)
    for path in paths:
        candidate = root / Path(path).name
        if candidate.exists():
            os.remove(str(candidate))

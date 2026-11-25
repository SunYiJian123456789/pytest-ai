# -*- coding: utf-8 -*-
"""注册式数据清理器（framework 内核）。

业务项目只需把「怎么删」注册进来，框架负责统一执行、结构化记录、失败可见：
报告顶部会展示清理汇总（成功 / 跳过 / 失败），残留数据不再被静默吞掉。

示例::

    cleaner = CleanupRegistry()
    cleaner.register('delete order %s' % no, lambda: api.delete('/api/orders/%s' % no))
    cleaner.run()
"""
import os
from pathlib import Path
from types import SimpleNamespace

from framework.state import state as session

# 兼容别名：真实状态在 SessionState（原地清空，别名始终有效）。
# 导入用 session 别名：本模块 record() 有局部变量 state 表示状态字符串。
CLEANUP_LOG: list[dict] = session.cleanup_log

# 兜底扫描器注册表：业务只回答「扫什么 / 怎么删」，内核负责调度、去重与记录。
# 放在 state 私有槽位，随 SessionState 一起重置，不新增第二处全局态。
SWEEP_KEY = 'framework.cleanup.sweeps'


def _merge_logs(payload) -> None:
    """把 worker 落盘的清理记录合并进本进程。"""
    if isinstance(payload, list):
        session.cleanup_log.extend(payload)


session.register_partition(
    'cleanup', prefix='.cleanup_', dump=lambda: list(session.cleanup_log),
    merge=_merge_logs)


def dump_log(path: Path):
    """兼容旧入口：xdist worker 退出时落盘本进程的清理记录。"""
    session.dump_partition('cleanup', path)


def load_logs(directory: Path):
    """兼容旧入口：主进程合并所有 worker 的清理记录并删除临时文件。"""
    session.load_partition('cleanup', directory)


def record(action: str, result, fallback: str = '', *, sweep: bool = False) -> dict:
    """把一次清理动作的结果记入全局汇总。

    ``sweep=True`` 标记为兜底扫描清理，与注册式清理在报告里分开统计；
    既有调用不传该参数，行为与语义完全不变。
    """
    if getattr(result, 'skipped', False):
        state, detail = 'SKIP', (getattr(result, 'error', '') or 'client not found')[:200]
    elif result is None or getattr(result, 'ok', False):
        state, detail = 'OK', ''
    else:
        msg = getattr(result, 'message', None) or getattr(result, 'error', '') or fallback
        state, detail = 'FAIL', (msg or 'unknown error')[:200]
    entry = {'action': action, 'state': state, 'detail': detail}
    if sweep:
        entry['sweep'] = True
    session.cleanup_log.append(entry)
    return entry


def register_sweep(name: str, discover, clean, fallback: str = '',
                   prefixes: tuple[str, ...] = ()) -> None:
    """注册一个兜底清理器（内核只调度，不认识业务表/接口）。

    - ``name``：报告里展示的资源名，如 ``APIU 测试用户``；
    - ``discover()``：返回本轮残留的候选标识列表；
    - ``clean(identifier)``：删除单个标识，返回带 ``ok`` / ``skipped`` 的结果对象；
    - ``fallback``：清理失败时的兜底说明；
    - ``prefixes``：允许清理的标识前缀。内核二次校验，``discover`` 即使扫宽了
      也不会删到真实数据；留空表示由业务自行保证安全。

    业务应在 conftest 的 ``pytest_configure`` 里注册；内核在 session 收尾、
    所有 worker 结束后统一执行一次，避免并行 worker 互相删除。
    """
    sweeps = session.namespace(SWEEP_KEY).setdefault('providers', [])
    sweeps.append({'name': name, 'discover': discover, 'clean': clean,
                   'fallback': fallback, 'prefixes': tuple(prefixes)})


def _is_test_key(key: str, prefixes: tuple[str, ...]) -> bool:
    """只处理显式登记的前缀，杜绝兜底清理误删真实数据。"""
    text = str(key)
    return any(text.startswith(prefix) for prefix in prefixes)


def run_sweeps() -> list[dict]:
    """执行所有已注册的兜底清理器，返回本轮新增的清理记录。

    单个扫描器失败（查询报错、权限不足）只记一条 FAIL，不影响其他扫描器；
    ``discover`` 返回的非字符串条目被忽略，避免把脏数据传给删除函数。
    """
    providers = session.namespace(SWEEP_KEY).get('providers') or []
    before = len(session.cleanup_log)
    for provider in providers:
        name = provider['name']
        try:
            found = provider['discover']() or []
        except Exception as exc:  # noqa: BLE001 - 扫描失败要可见但不应中断收尾
            # record() 对 None 的语义是「无需清理=成功」，失败必须显式构造失败结果
            failed = SimpleNamespace(ok=False, message=str(exc))
            record('sweep scan %s' % name, failed, str(exc), sweep=True)
            continue
        for key in found:
            if not isinstance(key, str) or not key:
                continue
            prefixes = provider.get('prefixes') or ()
            if prefixes and not _is_test_key(key, prefixes):
                failed = SimpleNamespace(ok=False, message='标识不在允许前缀内，已跳过')
                record('sweep %s %s' % (name, key), failed, '', sweep=True)
                continue
            try:
                result = provider['clean'](key)
            except Exception as exc:  # noqa: BLE001 - 单项失败不影响其他残留
                failed = SimpleNamespace(
                    ok=False, message='%s: %s' % (provider['fallback'], exc))
                record('sweep %s %s' % (name, key), failed, '', sweep=True)
            else:
                record('sweep %s %s' % (name, key), result,
                       provider['fallback'], sweep=True)
    return session.cleanup_log[before:]


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
    """把清理汇总与报告增强失败渲染成报告顶部的状态卡片。

    注册式清理（用例主动登记）与兜底清理（session 收尾扫描）分开统计：
    兜底清理数量 > 0 意味着有用例漏登记或中途异常，值得单独关注。
    """
    sweep_rows = [row for row in CLEANUP_LOG if row.get('sweep')]
    registered = [row for row in CLEANUP_LOG if not row.get('sweep')]
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
    parts.append('<div style="margin-top:4px;color:#4b5563">'
                 '注册式清理 %d 项 · <b style="color:#1d4ed8">兜底清理 %d 项</b>'
                 '</div>' % (len(registered), len(sweep_rows)))
    details = failed + skipped
    if details:
        parts.append('<ul style="margin:8px 0 0 18px;padding:0">')
        for row in details:
            tone = '#b91c1c' if row['state'] == 'FAIL' else '#b45309'
            source = '兜底' if row.get('sweep') else '注册'
            parts.append('<li style="color:%s">[%s/%s] %s — %s</li>'
                         % (tone, source, row['state'], row['action'], row['detail']))
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

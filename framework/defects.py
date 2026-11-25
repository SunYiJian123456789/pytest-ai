# -*- coding: utf-8 -*-
"""已知缺陷台账（framework 内核）：strict xfail 与缺陷记录的双向一致性校验。

要解决的问题
------------
``@pytest.mark.xfail(strict=True)`` 能在缺陷修好后用 XPASS 把 CI 变红，
但失败信息本身说不清「这是哪条缺陷、该找谁、当时现象是什么」。
反过来，开发者修好后端后常忘记删标记，或删了标记却忘记更新缺陷状态。

本模块把两件事绑在一起：

1. **台账**（业务维护，YAML）：每条缺陷一个 ``DEF-xxx`` 编号，绑定用例 nodeid；
2. **收集清单**（pytest 钩子自动落盘）：本轮收集到的全部用例 + 其中带 xfail 的用例。

校验是双向的：

- 台账 open + 用例无 xfail → 缺陷疑似已修，提示改状态；
- 台账 fixed + 用例仍有 xfail → 提示删标记（否则 XPASS 会让 CI 变红）；
- 用例有 xfail + 台账无条目 → 孤儿标记；
- 台账引用的 nodeid 根本没被收集到 → 拼写错误或用例已删除。

内核不认识任何业务字段：台账里的 ``endpoint`` / ``severity`` 等只做展示，
校验只依赖 ``id`` / ``test`` / ``status`` 三个约定字段。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

_ID_PATTERN = re.compile(r'^DEF-\d{3,}$')
VALID_STATUS = ('open', 'fixed')
REQUIRED_FIELDS = ('id', 'test', 'status', 'title', 'symptom', 'expected')

# 可由业务 conftest 配置；CLI 通过 --ledger 显式传入，不依赖此值
DEFAULT_LEDGER = 'projects/shopping/data/known_defects.yaml'
DEFAULT_MANIFEST = 'reports/xfail_manifest.json'


def configure(path: str | Path | None, *, project: str | None = None) -> None:
    """业务 conftest 在 pytest_configure 中登记台账路径与项目名。

    ``project`` 决定收集清单文件名（``<project>_xfail_manifest.json``），
    避免跑内核单测时把业务项目的清单覆盖掉。
    """
    from framework.state import state
    state.defects_ledger = Path(path) if path else None
    state.defects_project = project


def load_ledger(path: str | Path) -> list[dict]:
    """读取并校验台账结构；结构错误直接抛 ValueError（不静默忽略）。"""
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError('缺陷台账不存在：%s' % target)
    payload = yaml.safe_load(target.read_text(encoding='utf-8')) or {}
    if not isinstance(payload, dict):
        raise ValueError('台账顶层必须是映射，实际 %s' % type(payload).__name__)
    rows = payload.get('defects')
    if not isinstance(rows, list):
        raise ValueError('台账缺少 defects 列表')

    seen_ids: set[str] = set()
    seen_tests: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError('第 %d 条缺陷必须是映射' % index)
        for field in REQUIRED_FIELDS:
            if not row.get(field):
                raise ValueError('第 %d 条缺陷缺少必填字段 %s' % (index, field))
        defect_id = str(row['id'])
        if not _ID_PATTERN.match(defect_id):
            raise ValueError('缺陷编号 %r 不符合 DEF-001 格式' % defect_id)
        if defect_id in seen_ids:
            raise ValueError('缺陷编号重复：%s' % defect_id)
        seen_ids.add(defect_id)
        test = str(row['test'])
        if '::' not in test:
            raise ValueError('%s 的 test 必须是「文件::用例」nodeid：%r' % (defect_id, test))
        if test in seen_tests:
            raise ValueError('用例重复绑定：%s' % test)
        seen_tests.add(test)
        if row['status'] not in VALID_STATUS:
            raise ValueError('%s 的 status 必须是 open/fixed，实际 %r'
                             % (defect_id, row['status']))
    return rows


def collect_manifest(items) -> dict:
    """从 pytest 收集结果构造清单：全部 nodeid + xfail 子集。"""
    xfails = []
    for item in items:
        mark = item.get_closest_marker('xfail')
        if mark is None:
            continue
        xfails.append({
            'nodeid': item.nodeid,
            'strict': bool(mark.kwargs.get('strict', False)),
            'reason': str(mark.kwargs.get('reason') or ''),
        })
    return {
        'count': len(items),
        'collected': [item.nodeid for item in items],
        'xfails': xfails,
    }


def write_manifest(manifest: dict, path: str | Path) -> Path:
    """把收集清单落盘（pytest 钩子在收尾阶段调用）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                      encoding='utf-8')
    return target


def load_manifest(path: str | Path) -> dict:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError('收集清单不存在：%s（先跑一次 pytest 或 --collect-only）' % target)
    payload = json.loads(target.read_text(encoding='utf-8'))
    if not isinstance(payload, dict) or not isinstance(payload.get('collected'), list):
        raise ValueError('收集清单格式不对：%s' % target)
    payload.setdefault('xfails', [])
    return payload


def check(ledger: list[dict], manifest: dict) -> dict:
    """双向校验台账与收集清单，返回结构化结果（不抛异常）。"""
    issues: list[dict] = []
    collected = set(manifest.get('collected') or [])
    xfails = {row['nodeid']: row for row in (manifest.get('xfails') or [])}

    def add(level: str, defect_id: str, message: str) -> None:
        issues.append({'level': level, 'defect': defect_id, 'message': message})

    for row in ledger:
        defect_id = str(row['id'])
        test = str(row['test'])
        hit = xfails.get(test)

        if test not in collected:
            add('error', defect_id, '用例未被收集到：%s（nodeid 拼错或用例已删除）' % test)
            continue

        if row['status'] == 'open':
            if hit is None:
                add('error', defect_id,
                    '台账仍为 open，但用例已无 xfail——确认修复后把 status 改为 fixed，'
                    '或恢复 xfail 标记：%s' % test)
                continue
            if not hit['strict']:
                add('error', defect_id,
                    'xfail 未设 strict=True，缺陷修复后不会以 XPASS 提醒解标记：%s' % test)
            if defect_id not in hit.get('reason', ''):
                add('error', defect_id,
                    'xfail 的 reason 未包含 %s，XPASS 时无法反查台账：%s'
                    % (defect_id, test))
        else:  # fixed
            if hit is not None:
                add('error', defect_id,
                    '台账已标记 fixed，但用例仍有 xfail——请删除标记，否则修补后 XPASS 会变红：%s'
                    % test)

    bound = {str(row['test']) for row in ledger}
    for nodeid in xfails:
        if nodeid not in bound:
            add('error', '-', '孤儿 xfail（未登记台账）：%s' % nodeid)

    errors = [item for item in issues if item['level'] == 'error']
    stats = {
        'ledger_total': len(ledger),
        'open': sum(1 for row in ledger if row['status'] == 'open'),
        'fixed': sum(1 for row in ledger if row['status'] == 'fixed'),
        'xfail_count': len(xfails),
        'strict_xfail': sum(1 for row in xfails.values() if row['strict']),
        'issues': len(errors),
    }
    return {'ok': not errors, 'issues': issues, 'stats': stats}


def render_markdown(ledger: list[dict], result: dict | None = None) -> str:
    """人类可读台账：直接写进 CI 摘要，不再手工维护第二份 Markdown。"""
    lines = [
        '# 已知缺陷台账',
        '',
        '> 每条缺陷绑定一个 `strict=True` 的 xfail 用例；后端修复后请**同时**'
        '删除标记并把状态改为 `fixed`，CI 会校验两者一致性。',
        '',
    ]
    if result is not None:
        stats = result['stats']
        lines += [
            '本轮校验：%d 条缺陷（open %d / fixed %d），%d 条 xfail，问题 %d 项。'
            % (stats['ledger_total'], stats['open'], stats['fixed'],
               stats['xfail_count'], stats['issues']),
            '',
        ]
    lines += [
        '| 编号 | 用例 | 接口 | 状态 | 级别 | 发现日期 | 现象 | 预期 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |',
    ]
    for row in ledger:
        lines.append('| %s | `%s` | `%s` | %s | %s | %s | %s | %s |' % (
            row['id'], row['test'], row.get('endpoint') or '-', row['status'],
            row.get('severity') or '-', row.get('discovered') or '-',
            str(row.get('symptom') or '').replace('\n', ' '),
            str(row.get('expected') or '').replace('\n', ' '),
        ))
    lines.append('')

    if result is not None and result['issues']:
        lines += ['## 校验问题', '']
        for issue in result['issues']:
            lines.append('- **[%s]** %s：%s'
                         % (issue['level'].upper(), issue['defect'], issue['message']))
        lines.append('')
    return '\n'.join(lines)


def render_terminal(result: dict) -> str:
    stats = result['stats']
    parts = [
        '[defects] 台账 %d 条（open %d / fixed %d），xfail %d 条（strict %d）'
        % (stats['ledger_total'], stats['open'], stats['fixed'],
           stats['xfail_count'], stats['strict_xfail']),
    ]
    if result['issues']:
        parts.append('[defects] 发现 %d 项不一致：' % len(result['issues']))
        parts += ['  - [%s] %s：%s' % (issue['defect'], issue['level'], issue['message'])
                  for issue in result['issues']]
    else:
        parts.append('[defects] 台账与用例一致')
    return '\n'.join(parts)


def main(argv=None) -> int:
    """命令行入口：``python -m framework.defects --check`` 做 CI 门禁。"""
    import argparse

    parser = argparse.ArgumentParser(prog='python -m framework.defects')
    parser.add_argument('--ledger', default=DEFAULT_LEDGER, help='缺陷台账 YAML 路径')
    parser.add_argument('--manifest', default=None,
                        help='pytest 收集清单 JSON 路径（默认按 --project 推导）')
    parser.add_argument('--project', default=None,
                        help='项目名：清单默认位于 reports/<project>_xfail_manifest.json')
    parser.add_argument('--format', choices=['md', 'terminal', 'json'], default='terminal')
    parser.add_argument('--check', action='store_true',
                        help='校验台账与收集清单一致性；不一致返回非 0')
    parser.add_argument('--write', metavar='PATH', default=None,
                        help='把 Markdown 台账写到指定文件（CI 摘要/归档用）')
    args = parser.parse_args(argv)
    manifest_path = args.manifest or (
        'reports/%s_xfail_manifest.json' % args.project
        if args.project else DEFAULT_MANIFEST)

    try:
        ledger = load_ledger(args.ledger)
    except (OSError, ValueError) as exc:
        print('[defects] 台账读取失败：%s' % exc)
        return 2

    result = None
    if args.check:
        try:
            manifest = load_manifest(manifest_path)
        except (OSError, ValueError) as exc:
            print('[defects] 收集清单读取失败：%s' % exc)
            return 2
        result = check(ledger, manifest)

    if args.format == 'md' or args.write:
        text = render_markdown(ledger, result)
        if args.write:
            target = Path(args.write)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8')
        if args.format == 'md':
            print(text)
        elif result is not None:
            # --write 只写文件时也要在终端给出校验结论，否则 CI 日志一片空白
            print(render_terminal(result))
    elif args.format == 'json':
        print(json.dumps(result if result is not None else ledger,
                         ensure_ascii=False, indent=2))
    elif result is not None:
        print(render_terminal(result))
    else:
        print('[defects] 台账 %d 条（--check 可与收集清单比对）' % len(ledger))

    if result is not None and not result['ok']:
        return 1
    return 0


if __name__ == '__main__':  # pragma: no cover - CLI 由 main() 单测覆盖
    raise SystemExit(main())

__all__ = [
    'configure', 'load_ledger', 'collect_manifest', 'write_manifest',
    'load_manifest', 'check', 'render_markdown', 'render_terminal', 'main',
]

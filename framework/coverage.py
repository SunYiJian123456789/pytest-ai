# -*- coding: utf-8 -*-
"""接口覆盖率（framework 内核）。

把「接口清单」从人工对照变成可计算的事实：

1. 运行期由 ``ApiClient`` 上报每一次真实请求（方法 + URL + 状态码）；
2. 路径按占位符归一化（``/api/cart/12`` → ``/api/cart/{id}``、
   ``/images/upload-abc.png`` → ``/images/{file}``）；
3. 与 YAML 清单（``method`` + ``path``）比对，算出覆盖 / 未覆盖 / 清单外请求；
4. 输出 ``reports/api_coverage.json`` 与 ``api_coverage.md``，并在终端打一张表。

xdist 下每个 worker 各自把自己的命中落盘（``.api_coverage_<worker>.json``），
主进程在 ``pytest_unconfigure`` 合并——与 cleanup 用同一套机制。

清单文件由业务项目通过 ``configure(inventory=...)`` 指定，内核不认识任何具体系统。
"""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from framework.state import state

# 归一化占位符：纯数字段 → {id}，最后一段带扩展名的文件名 → {file}
_ID_SEGMENT = re.compile(r'^\d+$')

# 兼容别名：真实状态在 SessionState（HITS 原地清空，别名始终有效）。
# INVENTORY 是标量路径，读写统一走 state.coverage_inventory。
HITS: dict[tuple[str, str], dict] = state.coverage_hits


def configure(inventory=None) -> None:
    """业务 conftest 在 pytest_configure 中调用，指定接口清单路径。"""
    state.coverage_inventory = Path(inventory) if inventory else None


def normalize_path(url_or_path: str) -> str:
    """把具体 URL 归一化成清单里的样子，用于同一条接口的多次调用合并计数。"""
    raw = url_or_path or ''
    path = urlsplit(raw).path if '://' in raw else raw.split('?')[0]
    segments = [seg for seg in path.split('/') if seg]
    if not segments:
        return '/'
    normalized = []
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if _ID_SEGMENT.match(segment):
            normalized.append('{id}')
        elif last and '.' in segment:
            normalized.append('{file}')
        else:
            normalized.append(segment)
    return '/' + '/'.join(normalized)


def record(method: str, url: str, status: int = 0) -> None:
    """记一次真实请求；重复调用只累加计数，不改变键。"""
    key = (method.upper(), normalize_path(url))
    with state.lock:
        entry = state.coverage_hits.setdefault(key, {'count': 0, 'statuses': {}})
        entry['count'] += 1
        bucket = str(status)
        entry['statuses'][bucket] = entry['statuses'].get(bucket, 0) + 1


def reset() -> None:
    state.reset_coverage()


def snapshot() -> dict:
    with state.lock:
        return {'%s %s' % method_path: dict(value)
                for method_path, value in state.coverage_hits.items()}


# ---------------- xdist 落盘 / 合并 ----------------

def _merge_hits(payload) -> None:
    """把 worker 落盘的命中合并进本进程（键为 'METHOD /path' 字符串）。"""
    with state.lock:
        for key, value in (payload or {}).items():
            method, _, path = key.partition(' ')
            entry = state.coverage_hits.setdefault(
                (method, path), {'count': 0, 'statuses': {}})
            entry['count'] += int(value.get('count', 0))
            for status, times in (value.get('statuses') or {}).items():
                entry['statuses'][status] = entry['statuses'].get(status, 0) + int(times)


state.register_partition(
    'coverage', prefix='.api_coverage_', dump=snapshot, merge=_merge_hits)


def dump(path: Path) -> None:
    """兼容旧入口：worker 退出时落盘本进程命中。"""
    state.dump_partition('coverage', path)


def load_dumps(directory: Path) -> None:
    """兼容旧入口：主进程合并所有 worker 的命中并删除临时文件。"""
    state.load_partition('coverage', directory)


# ---------------- 清单与报告 ----------------

REQUIRED_FIELDS = ('method', 'path')


def load_inventory(path: Path) -> list[dict]:
    """读取并校验接口清单；缺字段直接报错，避免清单写错后静默少算覆盖率。"""
    data = yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
    endpoints = data.get('endpoints')
    if not isinstance(endpoints, list) or not endpoints:
        raise ValueError('接口清单缺少 endpoints 列表：%s' % path)

    rows, seen = [], set()
    for index, raw in enumerate(endpoints, 1):
        missing = [field for field in REQUIRED_FIELDS if not str(raw.get(field) or '').strip()]
        if missing:
            raise ValueError('接口清单第 %d 条缺少字段 %s' % (index, missing))
        key = (str(raw['method']).upper(), raw['path'])
        if key in seen:
            raise ValueError('接口清单第 %d 条重复登记：%s %s' % (index, key[0], key[1]))
        seen.add(key)
        rows.append({
            'method': key[0],
            'path': raw['path'],
            'name': raw.get('name', ''),
            'group': raw.get('group', '未分组'),
            'covered_by': list(raw.get('covered_by') or []),
        })
    return rows


def _string_keyed(hits) -> dict:
    """统一成 ``"METHOD /path"`` 形式的键：外部 JSON 与内存快照都用这套格式。"""
    if hits is None:
        return snapshot()
    result = {}
    for key, value in hits.items():
        text = '%s %s' % key if isinstance(key, tuple) else key
        result[text] = value
    return result


def build_report(inventory: list[dict], hits=None) -> dict:
    hits = _string_keyed(hits)
    declared = {(row['method'], row['path']) for row in inventory}

    rows = []
    for endpoint in inventory:
        key = '%s %s' % (endpoint['method'], endpoint['path'])
        hit = hits.get(key) or {}
        rows.append(dict(endpoint, covered=bool(hit),
                         count=int(hit.get('count', 0)),
                         statuses=dict(hit.get('statuses') or {})))

    unexpected = []
    for key, value in hits.items():
        method, _, path = key.partition(' ')
        if (method, path) not in declared:
            unexpected.append({
                'method': method, 'path': path,
                'count': int(value.get('count', 0)),
                'statuses': dict(value.get('statuses') or {}),
            })
    unexpected.sort(key=lambda row: (row['path'], row['method']))

    covered = sum(1 for row in rows if row['covered'])
    total = len(rows)
    return {
        'total': total,
        'covered': covered,
        'ratio': round(covered / total, 4) if total else 0.0,
        'rows': rows,
        'missed': [row for row in rows if not row['covered']],
        'unexpected': unexpected,
    }


def _status_text(statuses: dict) -> str:
    if not statuses:
        return '-'
    return '/'.join('%s×%s' % (code, times) for code, times in sorted(statuses.items()))


def render_markdown(report: dict) -> str:
    lines = [
        '# 接口覆盖率',
        '',
        '本次运行触达 **%d / %d** 个「方法 + 路径」组合，覆盖率 **%.1f%%**。'
        % (report['covered'], report['total'], report['ratio'] * 100),
        '',
        '> 覆盖率由运行期真实请求统计（`ApiClient` 上报），不是按用例文件推断。',
        '',
    ]

    groups: dict[str, list] = {}
    for row in report['rows']:
        groups.setdefault(row['group'], []).append(row)

    for group, rows in groups.items():
        lines += ['## %s' % group, '',
                  '| 方法 | 路径 | 说明 | 命中 | 状态码 | 覆盖 |',
                  '| --- | --- | --- | --- | --- | --- |']
        for row in rows:
            lines.append('| %s | `%s` | %s | %d | %s | %s |' % (
                row['method'], row['path'], row['name'] or '-', row['count'],
                _status_text(row['statuses']), '✅' if row['covered'] else '❌',
            ))
        lines.append('')

    if report['missed']:
        lines += ['## 未覆盖（%d）' % len(report['missed']), '']
        for row in report['missed']:
            lines.append('- `%s %s` %s' % (row['method'], row['path'], row['name']))
        lines.append('')

    if report['unexpected']:
        lines += ['## 清单外请求（%d）' % len(report['unexpected']), '',
                  '> 调用了但没登记在清单里——新接口忘了登记，或负向用例故意打不存在的路径。',
                  '',
                  '| 方法 | 路径 | 命中 | 状态码 |',
                  '| --- | --- | --- | --- |']
        for row in report['unexpected']:
            lines.append('| %s | `%s` | %d | %s |' % (
                row['method'], row['path'], row['count'], _status_text(row['statuses'])))
        lines.append('')

    return '\n'.join(lines)


def render_terminal(report: dict) -> str:
    head = '[coverage] 本次运行接口覆盖率 %d/%d = %.1f%%' % (
        report['covered'], report['total'], report['ratio'] * 100)
    parts = [head]
    if report['missed']:
        parts.append('  未覆盖 %d 条：' % len(report['missed']))
        parts += ['    - %s %s %s' % (row['method'], row['path'], row['name'])
                  for row in report['missed']]
    if report['unexpected']:
        parts.append('  清单外请求 %d 条：' % len(report['unexpected']))
        parts += ['    - %s %s（%s）' % (row['method'], row['path'], _status_text(row['statuses']))
                  for row in report['unexpected']]
    return '\n'.join(parts)


def write_reports(reports_dir: Path, report: dict) -> dict:
    """落盘 json（供看板/外部比对）与 md（供人看），返回两个路径。"""
    root = Path(reports_dir)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / 'api_coverage.json'
    md_path = root / 'api_coverage.md'
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    md_path.write_text(render_markdown(report), encoding='utf-8')
    return {'json': str(json_path), 'markdown': str(md_path)}


def collect_main(reports_dir: Path) -> dict:
    """主进程：合并 worker 命中 → 读清单 → 出报告 → 落盘。返回报告字典。"""
    load_dumps(reports_dir)
    inventory = state.coverage_inventory
    if inventory is None:
        return {}
    report = build_report(load_inventory(inventory))
    report['inventory'] = str(inventory)
    write_reports(reports_dir, report)
    return report


def main(argv=None) -> int:
    """命令行入口：读已落盘的 api_coverage.json，输出表格或做阈值判定。

    CI 用它做门禁（``python -m framework.coverage --min 90``），
    这样阈值策略留在流水线里，框架本身不改 pytest 退出码。
    """
    import argparse

    parser = argparse.ArgumentParser(prog='python -m framework.coverage')
    parser.add_argument('--report', default='reports/api_coverage.json',
                        help='pytest 运行后生成的覆盖率 JSON')
    parser.add_argument('--format', choices=['md', 'json', 'terminal'], default='md',
                        help='输出格式，默认 markdown（可直接写进 CI 摘要）')
    parser.add_argument('--min', type=float, default=None,
                        help='覆盖率下限（百分比）；低于则返回非 0')
    args = parser.parse_args(argv)

    path = Path(args.report)
    if not path.exists():
        print('[coverage] 找不到覆盖率报告：%s（先跑一轮 pytest）' % path)
        return 2
    report = json.loads(path.read_text(encoding='utf-8'))

    if args.format == 'md':
        print(render_markdown(report))
    elif args.format == 'terminal':
        print(render_terminal(report))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.min is not None:
        ratio = report['covered'] / report['total'] * 100 if report.get('total') else 0.0
        if ratio < args.min:
            print('[coverage] 覆盖率 %.1f%% 低于阈值 %.1f%%' % (ratio, args.min))
            return 1
        print('[coverage] 覆盖率 %.1f%% 达标（阈值 %.1f%%）' % (ratio, args.min))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

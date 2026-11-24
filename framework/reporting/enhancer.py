# -*- coding: utf-8 -*-
"""把 pytest-html 的默认报告增强为带仪表盘的可视化报告。

只做后处理：pytest-html 在 sessionfinish 写出自包含 HTML，本模块在
unconfigure 阶段读取该文件，注入概览卡片、模块分布、接口调用统计和
更友好的请求明细样式，不改动插件原生结构与数据。
"""
import html
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from framework.reporting.assets import CSS, JS

# 通用默认值；业务项目通过 enhance(..., **REPORT_OPTIONS) 覆盖
DEFAULT_OPTIONS = {
    'project_label': 'API · REGRESSION',
    'module_labels': {},
    'base_url': '',
    'database': '',
    'data_source': '',
    'notes': [],
    'success_code': '200',
}

CALL_RE = re.compile(
    r'data-method="(?P<method>[^"]+)"\s+'
    r'data-path="(?P<path>[^"]+)"\s+'
    r'data-status="(?P<status>[^"]+)"\s+'
    r'data-code="(?P<code>[^"]+)"\s+'
    r'data-ms="(?P<ms>[^"]+)"\s+'
    r'data-ok="(?P<ok>[^"]+)"'
)


def _seconds(text) -> float:
    """把 pytest 的 '9 ms' / '1.2 s' / '1m 5s' 统一换算为秒。"""
    if not text:
        return 0.0
    text = str(text).strip()
    match = re.fullmatch(r'([\d.]+)\s*(ms|s|m)', text)
    if match:
        value = float(match.group(1))
        return value / 1000 if match.group(2) == 'ms' else value * 60 if match.group(2) == 'm' else value
    match = re.fullmatch(r'(\d+)m\s*([\d.]+)s', text)
    if match:
        return int(match.group(1)) * 60 + float(match.group(2))
    return 0.0


def _read_report_data(source: str):
    match = re.search(r'data-jsonblob="(.*?)"\s*>', source, re.S)
    if not match:
        raise ValueError('未找到 pytest-html 数据块')
    return json.loads(html.unescape(match.group(1)))


def _collect(source: str):
    data = _read_report_data(source)
    tests = data.get('tests') or {}

    stats = {
        'total': len(tests),
        'passed': 0, 'failed': 0, 'skipped': 0, 'other': 0,
        'duration': 0.0,
        'modules': defaultdict(lambda: {'total': 0, 'passed': 0, 'failed': 0, 'duration': 0.0}),
        'endpoints': defaultdict(lambda: {'count': 0, 'ms': 0, 'max': 0, 'fail': 0}),
        'status': defaultdict(int),
        'business': defaultdict(int),
        'calls': 0,
        'failed_cases': [],
    }

    for test_id, reports in tests.items():
        report = (reports or [{}])[0]
        result = report.get('result') or ''
        duration = _seconds(report.get('duration'))
        module = test_id.split('::')[0].split('/')[-1]
        bucket = stats['modules'][module]
        bucket['total'] += 1
        bucket['duration'] += duration
        stats['duration'] += duration

        if result == 'Passed':
            stats['passed'] += 1
            bucket['passed'] += 1
        elif result in ('Failed', 'Error'):
            stats['failed'] += 1
            bucket['failed'] += 1
            stats['failed_cases'].append(test_id)
        elif result == 'Skipped':
            stats['skipped'] += 1
        else:
            stats['other'] += 1

        for extra in report.get('extras') or []:
            if extra.get('format_type') != 'html':
                continue
            for found in CALL_RE.finditer(extra.get('content') or ''):
                method = found.group('method')
                path = html.unescape(found.group('path'))
                status = int(found.group('status') or 0)
                ms = int(found.group('ms') or 0)
                ok = found.group('ok') == 'true'
                key = (method, path)
                endpoint = stats['endpoints'][key]
                endpoint['count'] += 1
                endpoint['ms'] += ms
                endpoint['max'] = max(endpoint['max'], ms)
                if not ok:
                    endpoint['fail'] += 1
                code_text = found.group('code')
                biz = '无响应体' if code_text == '-' else code_text
                stats['business'][biz] += 1
                stats['status']['2xx' if 200 <= status < 300 else '4xx' if status < 500 else '5xx'] += 1
                stats['calls'] += 1

    return stats, data


def _kpi(label, value, sub, tone):
    return (
        '<div class="enh-kpi enh-kpi-{tone}">'
        '<div class="enh-kpi-label">{label}</div>'
        '<div class="enh-kpi-value">{value}</div>'
        '<div class="enh-kpi-sub">{sub}</div>'
        '</div>'
    ).format(tone=tone, label=html.escape(label), value=value, sub=html.escape(sub))


def _module_rows(stats, module_labels):
    modules = sorted(stats['modules'].items(), key=lambda kv: kv[1]['total'], reverse=True)
    peak = max((v['total'] for _, v in modules), default=1) or 1
    rows = []
    for filename, item in modules:
        label = module_labels.get(filename, filename)
        pct = item['total'] / peak * 100
        fail_cls = 'enh-bar-fail' if item['failed'] else ''
        row = (
            '<div class="enh-bar-row">'
            '<div class="enh-bar-label" title="{filename}">{label}</div>'
            '<div class="enh-bar-track"><div class="enh-bar-fill {fail_cls}" style="width:{pct:.1f}%"></div></div>'
            '<div class="enh-bar-num">{total} <span>/ {ms:.0f} ms</span></div>'
            '</div>'
        ).format(
            filename=html.escape(filename), label=html.escape(label), pct=pct,
            fail_cls=fail_cls, total=item['total'], ms=item['duration'] * 1000,
        )
        rows.append(row)
    return ''.join(rows)


def _endpoint_rows(stats):
    endpoints = sorted(
        stats['endpoints'].items(),
        key=lambda kv: (-kv[1]['count'], kv[0][1]),
    )[:14]
    rows = []
    for (method, path), item in endpoints:
        avg = item['ms'] / item['count'] if item['count'] else 0
        row = (
            '<tr>'
            '<td><span class="enh-method enh-m-{mlow}">{method}</span></td>'
            '<td class="enh-endpoint-path">{path}</td>'
            '<td class="enh-num">{count}</td>'
            '<td class="enh-num">{avg:.0f} ms</td>'
            '<td class="enh-num">{maxms} ms</td>'
            '<td class="enh-num">{fail}</td>'
            '</tr>'
        ).format(
            mlow=method.lower(), method=html.escape(method),
            path=html.escape(path), count=item['count'], avg=avg,
            maxms=item['max'], fail=item['fail'],
        )
        rows.append(row)
    return ''.join(rows)


def _failed_rows(stats):
    if not stats['failed_cases']:
        return '<div class="enh-empty">本次执行没有失败用例</div>'
    return ''.join(
        '<div class="enh-fail-item">%s</div>' % html.escape(case)
        for case in stats['failed_cases']
    )


def _business_cells(stats, success_code='200'):
    """业务 code 分布：成功码与各类失败分开显示，口径与 HTTP 状态无关。"""
    success = str(success_code)
    labels = {
        success: '成功', '400': '参数校验', '401': '未授权',
        '404': '不存在', '500': '服务端', '无响应体': '无 code',
    }
    ordered = [success, '400', '401', '404', '500', '无响应体']
    codes = ordered + [k for k in sorted(stats['business']) if k not in ordered]
    cells = []
    for code in codes:
        count = stats['business'].get(code, 0)
        if not count:
            continue
        tone = 's2' if code == success else 's5' if code in ('500', '无响应体') else 's4'
        cell = (
            '<div class="enh-status-item {tone}"><b>{count}</b>'
            '<span>code {code} {label}</span></div>'
        ).format(tone=tone, count=count, code=html.escape(code),
                 label=html.escape(labels.get(code, '其他')))
        cells.append(cell)
    return ''.join(cells)


def _dashboard(stats, options):
    total = stats['total'] or 1
    passed = stats['passed']
    rate = passed / total * 100
    other = stats['other'] or stats['skipped']
    status2, status4, status5 = (stats['status'][k] for k in ('2xx', '4xx', '5xx'))
    biz_fail = stats['calls'] - stats['business'].get(str(options['success_code']), 0)
    biz_cells = _business_cells(stats, options['success_code'])
    generated = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    notes_text = ' '.join(html.escape(str(n)) for n in (options.get('notes') or []))

    return (
        '<div id="enh-dashboard" class="enh-root">'
        '<div class="enh-hero">'
        '<div>'
        '<div class="enh-eyebrow">{project_label}</div>'
        '<h1>接口自动化测试报告</h1>'
        '<div class="enh-hero-sub">pytest + requests · {data_source} · 生成于 {generated}</div>'
        '</div>'
        '<div class="enh-rate" style="--rate:{rate:.2f}">'
        '<div class="enh-rate-inner"><b>{rate:.0f}%</b><span>通过率</span></div>'
        '</div>'
        '</div>'
        '<div class="enh-kpis">'
        '{kpi_total}{kpi_passed}{kpi_failed}{kpi_skipped}{kpi_duration}{kpi_calls}'
        '</div>'
        '<div class="enh-grid">'
        '<section class="enh-card enh-card-wide">'
        '<h3>模块用例分布 <small>按用例数排序</small></h3>'
        '<div class="enh-bars">{bars}</div>'
        '</section>'
        '<section class="enh-card">'
        '<h3>接口调用概览 <small>TOP 14 · 失败 = 业务失败或 HTTP 非 2xx</small></h3>'
        '<table class="enh-table"><thead><tr><th>方法</th><th>路径</th><th>次数</th><th>均耗</th><th>峰值</th><th>失败</th></tr></thead>'
        '<tbody>{endpoints}</tbody></table>'
        '</section>'
        '<section class="enh-card">'
        '<h3>响应状态分布 <small>HTTP 与业务双层口径</small></h3>'
        '<div class="enh-sub-title">HTTP 状态码</div>'
        '<div class="enh-status-grid">'
        '<div class="enh-status-item s2"><b>{s2}</b><span>2xx 成功</span></div>'
        '<div class="enh-status-item s4"><b>{s4}</b><span>4xx 客户端</span></div>'
        '<div class="enh-status-item s5"><b>{s5}</b><span>5xx 服务端</span></div>'
        '</div>'
        '<div class="enh-sub-title">业务 code（Result.code）</div>'
        '<div class="enh-status-grid enh-status-codes">{biz_cells}</div>'
        '<div class="enh-note">说明：HTTP 状态与业务 code 是两个口径，HTTP 2xx 不等于业务成功；表格「失败」列按业务口径统计（共 <b>{biz_fail}</b> 次）。{notes_text}</div>'
        '<h3 class="enh-gap">失败用例</h3>{failed}'
        '</section>'
        '<section class="enh-card">'
        '<h3>运行环境</h3>'
        '<dl class="enh-env">'
        '<dt>被测服务</dt><dd>{base_url}</dd>'
        '<dt>数据库</dt><dd>{database}</dd>'
        '<dt>用例总数</dt><dd>{total}</dd>'
        '<dt>总耗时</dt><dd>{duration:.2f} s</dd>'
        '<dt>请求明细</dt><dd>{calls} 条</dd>'
        '<dt>数据源</dt><dd>{data_source}</dd>'
        '</dl>'
        '</section>'
        '</div>'
        '<div class="enh-toolbar">'
        '<button type="button" onclick="enhToggleAll(true)">展开全部请求</button>'
        '<button type="button" onclick="enhToggleAll(false)">折叠全部请求</button>'
        '<a href="#results-table">查看逐条用例 ↓</a>'
        '</div>'
        '</div>'
    ).format(
        generated=generated, rate=rate,
        project_label=html.escape(str(options['project_label'])),
        data_source=html.escape(str(options['data_source'] or '真实数据源')),
        notes_text=notes_text,
        kpi_total=_kpi('用例总数', total, 'collected', 'indigo'),
        kpi_passed=_kpi('通过', passed, '%.0f%% 通过率' % rate, 'green'),
        kpi_failed=_kpi('失败', stats['failed'], '需要关注', 'red' if stats['failed'] else 'slate'),
        kpi_skipped=_kpi('跳过 / 其他', other, '非执行结果', 'amber'),
        kpi_duration=_kpi('总耗时', '%.2f<span class="enh-unit">s</span>' % stats['duration'], '全部用例', 'blue'),
        kpi_calls=_kpi('接口调用', stats['calls'], '含每次请求', 'purple'),
        bars=_module_rows(stats, options['module_labels']),
        endpoints=_endpoint_rows(stats),
        s2=status2, s4=status4, s5=status5,
        biz_cells=biz_cells, biz_fail=biz_fail,
        failed=_failed_rows(stats),
        base_url=html.escape(str(options['base_url'] or '-')),
        database=html.escape(str(options['database'] or '-')),
        total=total, duration=stats['duration'], calls=stats['calls'],
    )


def enhance(report_path: Path, **options):
    """对 pytest-html 报告做后处理；options 由业务项目注入，内核不感知业务。"""
    merged = dict(DEFAULT_OPTIONS)
    merged.update({k: v for k, v in options.items() if k in merged})
    source = Path(report_path).read_text(encoding='utf-8')
    if 'id="enh-dashboard"' in source:
        return
    stats, _ = _collect(source)
    enhanced = source.replace('</head>', CSS + '</head>', 1)
    enhanced = enhanced.replace('<body>', '<body>' + _dashboard(stats, merged), 1)
    enhanced = enhanced.replace('</body>', JS + '</body>', 1)
    Path(report_path).write_text(enhanced, encoding='utf-8')

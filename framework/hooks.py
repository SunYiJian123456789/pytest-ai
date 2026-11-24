# -*- coding: utf-8 -*-
"""通用 pytest 钩子（framework 内核）。

根 conftest.py 显式导入这里的钩子；业务 conftest 只需在 pytest_configure 中
更新 ``REPORT_OPTIONS``（项目名、模块标签、运行环境等），报告就能带上业务信息，
而钩子本身与任何系统无关。

结果沉淀：
- 报告按时间戳归档到 ``reports/archive/``（保留最近 API_REPORT_KEEP 份，默认 30）；
- 每轮运行结束写 ``reports/run_summary.json``（结果计数、环境、耗时），
  供外部系统采集趋势；CI 配合 junit.xml（pytest.ini）接入测试看板。
"""
import json
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path

from framework.cleanup import dump_log, inject_banner, load_logs
from framework.config import ROOT, env

# 业务项目可覆盖这些选项；enhancer 只消费这份字典，不 import 业务模块
REPORT_OPTIONS: dict = {
    'title': '接口自动化测试报告（pytest + requests）',
    'project_label': 'API · REGRESSION',
    'module_labels': {},
    'base_url': '',
    'database': '',
    'data_source': '',
    'notes': [],
    'success_code': '200',
}

REPORT_ENHANCE_ERROR: list[str] = []


def configure_report(**options):
    """供业务 conftest 在 pytest_configure 中调用，合并报告展示选项。"""
    REPORT_OPTIONS.update(options)


def pytest_configure(config):
    """`--collect-only` 不覆盖正式报告；xdist worker 记录清理日志供主进程汇总。"""
    if config.getoption('collectonly', default=False):
        config.option.htmlpath = str(
            Path(tempfile.gettempdir()) / 'api-automation-collect-only-report.html'
        )
    config._cleanup_dump = None
    if getattr(config, 'workerinput', None):
        worker_id = config.workerinput.get('workerid', 'worker')
        config._cleanup_dump = ROOT / 'reports' / ('.cleanup_%s.json' % worker_id)
    else:
        config._session_started = time.monotonic()  # 结果沉淀用：本轮起始时间


def pytest_html_report_title(report):
    report.title = REPORT_OPTIONS['title']


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """结果沉淀：本轮结果概要写入 reports/run_summary.json（仅主进程）。"""
    if getattr(config, 'workerinput', None) or config.getoption('collectonly', default=False):
        return
    stats = terminalreporter.stats
    counts = {key: len(stats.get(key) or [])
              for key in ('passed', 'failed', 'error', 'skipped', 'xfailed', 'xpassed')}
    started = getattr(config, '_session_started', None)
    summary = {
        'timestamp': datetime.now().isoformat(timespec='seconds'),
        'env': env('API_ENV', '') or 'default',
        'project': REPORT_OPTIONS.get('project_label', ''),
        'exitstatus': int(exitstatus),
        'duration_seconds': round(time.monotonic() - started, 2) if started else None,
        'total': sum(counts.values()),
        **counts,
    }
    try:
        target = ROOT / 'reports' / 'run_summary.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    except OSError:  # 沉淀失败不影响测试结论
        pass


def _archive_report(target: Path):
    """报告按时间戳归档，保留最近 API_REPORT_KEEP 份（默认 30，0 表示关闭）。"""
    keep = int(env('API_REPORT_KEEP', '30') or 0)
    if keep <= 0:
        return
    archive_dir = target.parent / 'archive'
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    shutil.copy2(target, archive_dir / ('report_%s.html' % stamp))
    for old in sorted(archive_dir.glob('report_*.html'))[:-keep]:
        old.unlink(missing_ok=True)


def pytest_unconfigure(config):
    """worker 只落盘清理日志；主进程合并后增强报告、注入汇总横幅并归档。"""
    if getattr(config, 'workerinput', None):
        dump = getattr(config, '_cleanup_dump', None)
        if dump:
            dump.parent.mkdir(parents=True, exist_ok=True)
            dump_log(dump)
        return
    load_logs(ROOT / 'reports')
    if config.getoption('collectonly', default=False):
        return
    html_path = getattr(config.option, 'htmlpath', None)
    if not html_path:
        return
    target = Path(html_path)
    if not target.is_absolute():
        target = config.rootpath / target
    if not target.exists():
        return
    try:
        from framework.reporting.enhancer import enhance
        enhance(target, **REPORT_OPTIONS)
    except Exception as exc:  # noqa: BLE001 - 报告美化失败不应影响测试结论
        REPORT_ENHANCE_ERROR.append(str(exc)[:300])
        print('[report-enhancer] 跳过报告增强：%s' % exc)
    inject_banner(target, REPORT_ENHANCE_ERROR)
    try:
        _archive_report(target)
    except Exception:  # noqa: BLE001 - 归档失败不影响测试结论
        pass

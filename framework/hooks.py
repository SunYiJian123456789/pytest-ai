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

from framework.cleanup import inject_banner
from framework.config import ROOT, env
from framework.preflight import records as preflight_records
from framework.state import state

# 兼容别名：报告选项与增强错误的真实状态在 SessionState（原地更新/清空）。
# 业务项目可覆盖这些选项；enhancer 只消费这份字典，不 import 业务模块。
REPORT_OPTIONS: dict = state.report_options
REPORT_ENHANCE_ERROR: list[str] = state.report_enhance_errors


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
    config._coverage_dump = None
    if getattr(config, 'workerinput', None):
        config._worker_id = config.workerinput.get('workerid', 'worker')
    else:
        config._session_started = time.monotonic()  # 结果沉淀用：本轮起始时间


def _manifest_name(project: str | None = None) -> str:
    """主清单文件名：按项目隔离，内核单测不会覆盖业务项目的清单。"""
    return '%sxfail_manifest.json' % ('%s_' % project if project else '')


def _shard_pattern(project: str | None = None) -> str:
    return '.%sxfail_manifest_*.json' % ('%s_' % project if project else '')


def pytest_collection_modifyitems(items, config):
    """落盘本轮收集清单，供 ``python -m framework.defects --check`` 双向校验。

    xdist 下收集钩子只在 worker 触发，主进程拿不到 items——所以 worker 各写
    一份带 id 的分片（每个 worker 收集到的全集相同），由主进程在结果沉淀前
    汇总成 ``xfail_manifest.json``。``--collect-only`` 单进程直接写主文件。
    """
    from framework.defects import collect_manifest, write_manifest
    worker = getattr(config, 'workerinput', None)
    project = state.defects_project
    reports_dir = ROOT / 'reports'
    target = (reports_dir / ('.%sxfail_manifest_%s.json'
                             % ('%s_' % project if project else '',
                                worker.get('workerid', 'worker')))
              if worker else reports_dir / _manifest_name(project))
    try:
        write_manifest(collect_manifest(items), target)
    except OSError:  # 沉淀失败不影响测试结论
        pass


def _merge_manifest_shards():
    """主进程汇总 worker 分片；任取一份完整清单即可，随后删除分片。"""
    root = ROOT / 'reports'
    project = state.defects_project
    shards = sorted(root.glob(_shard_pattern(project)))
    if not shards:
        return
    payload = None
    for file in shards:
        try:
            candidate = json.loads(file.read_text(encoding='utf-8'))
            if payload is None and candidate.get('collected'):
                payload = candidate
        except (OSError, ValueError):  # noqa: BLE001 - 单个坏分片不影响整体
            pass
        finally:
            # 不能 break：跳出循环会让后续分片漏删，污染下一轮统计
            file.unlink(missing_ok=True)
    if payload is not None:
        try:
            (root / _manifest_name(project)).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError:
            pass


def pytest_html_report_title(report):
    report.title = REPORT_OPTIONS['title']


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """结果沉淀：本轮结果概要写入 reports/run_summary.json（仅主进程）。"""
    if getattr(config, 'workerinput', None) or config.getoption('collectonly', default=False):
        return
    # 兜底清理只在主进程跑一次：先合并各 worker 的清理记录，再扫描残留。
    # 体检中止时用例零执行，此时扫库只会产生误导性 FAIL，直接跳过。
    from framework.cleanup import run_sweeps
    from framework.preflight import aborted
    state.load_workers(ROOT / 'reports')
    sweep_rows = [] if aborted() else run_sweeps()
    _merge_manifest_shards()
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
    # 清理汇总：注册式 / 兜底分开，兜底 > 0 说明有用例漏登记或中途异常
    registered = [row for row in state.cleanup_log if not row.get('sweep')]
    summary['cleanup'] = {
        'registered': len(registered),
        'sweep': len(sweep_rows),
        'sweep_failed': sum(1 for row in sweep_rows if row['state'] == 'FAIL'),
    }
    if sweep_rows:
        terminalreporter.write_line('')
        terminalreporter.write_line(
            '[cleanup] 兜底清理 %d 项（失败 %d）：注册式清理之外的残留，'
            '报告里单列统计'
            % (len(sweep_rows), summary['cleanup']['sweep_failed']))
    # 启动体检结果（哪几项通过/告警、各耗时多少）：环境问题事后可追溯，
    # xdist 下主进程不跑体检，此时为空、不写该键
    preflight = preflight_records()
    if preflight:
        summary['preflight'] = preflight

    # 已知缺陷台账：业务项目登记路径后，把一致性校验结果一并沉淀，
    # 这样「哪条 xfail 归属哪条缺陷、是否已解标记」事后可追溯。
    if state.defects_ledger is not None:
        try:
            from framework.defects import (check, load_ledger, load_manifest,
                                           render_markdown, render_terminal)
            ledger = load_ledger(state.defects_ledger)
            manifest = load_manifest(
                ROOT / 'reports' / _manifest_name(state.defects_project))
            result = check(ledger, manifest)
            summary['known_defects'] = dict(result['stats'], ok=result['ok'])
            reports_dir = ROOT / 'reports'
            reports_dir.mkdir(parents=True, exist_ok=True)
            (reports_dir / 'known_defects.md').write_text(
                render_markdown(ledger, result), encoding='utf-8')
            terminalreporter.write_line('')
            for line in render_terminal(result).splitlines():
                terminalreporter.write_line(line)
        except (OSError, ValueError) as exc:  # 台账沉淀失败不影响测试结论
            summary['known_defects_error'] = str(exc)[:200]

    try:
        target = ROOT / 'reports' / 'run_summary.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    except OSError:  # 沉淀失败不影响测试结论
        pass


def _record_enhance_error(error: str) -> None:
    """把报告增强失败写进 run_summary，让 CI 能显式检查而不是静默降级。

    pytest_terminal_summary 在 unconfigure 之前执行，summary 已落盘；这里
    读改写一次，追加 ``report_enhance_error`` 字段。写失败只告警，
    不再往 REPORT_ENHANCE_ERROR 里追加（避免重复记录）。
    """
    target = ROOT / 'reports' / 'run_summary.json'
    try:
        payload = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
        payload['report_enhance_error'] = error
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    except (OSError, ValueError) as exc:  # noqa: BLE001 - 沉淀失败不影响测试结论
        print('[report-enhancer] 无法写入 run_summary.json：%s' % exc)


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


def _write_coverage(config):
    """主进程：合并各 worker 的命中，与接口清单比对后落盘并在终端打表。"""
    from framework import coverage
    from framework.preflight import aborted
    if aborted():
        print('[coverage] 本轮因启动体检未通过而中止，跳过覆盖率统计'
              '（否则会把「环境没备好」写成覆盖率骤降的假回归）')
        return
    if not coverage.snapshot():
        print('[coverage] 本轮没有任何请求，跳过覆盖率统计')
        return
    try:
        report = coverage.collect_main(ROOT / 'reports')
    except Exception as exc:  # noqa: BLE001 - 覆盖率统计失败不应影响测试结论
        print('[coverage] 覆盖率统计失败：%s' % exc)
        return
    if not report:
        return
    reporter = config.pluginmanager.get_plugin('terminalreporter')
    lines = coverage.render_terminal(report).splitlines()
    if reporter is not None:
        reporter.write_line('')
        for line in lines:
            reporter.write_line(line)
    else:
        print('\n'.join(lines))


def pytest_unconfigure(config):
    """worker 一次落盘全部分区；主进程合并后增强报告、注入汇总横幅并归档。"""
    if getattr(config, 'workerinput', None):
        state.dump_worker(ROOT / 'reports', getattr(config, '_worker_id', 'worker'))
        return
    # 一次合并全部已注册分区（清理记录 + 覆盖率命中），替代过去的两次手动 load
    state.load_workers(ROOT / 'reports')
    if config.getoption('collectonly', default=False):
        return
    _write_coverage(config)
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
        message = str(exc)[:300]
        REPORT_ENHANCE_ERROR.append(message)
        print('[report-enhancer] 跳过报告增强：%s' % exc)
        # 不让测试结论变红，但把失败写进 run_summary + CI 门禁，避免静默降级
        _record_enhance_error(message)
    inject_banner(target, REPORT_ENHANCE_ERROR)
    try:
        _archive_report(target)
    except Exception:  # noqa: BLE001 - 归档失败不影响测试结论
        pass

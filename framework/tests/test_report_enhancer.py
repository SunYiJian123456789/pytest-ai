# -*- coding: utf-8 -*-
"""报告增强层的回归测试：不依赖真实 pytest-html，只用最小 golden HTML。

增强器靠正则解析 pytest-html 的私有 ``data-jsonblob`` 属性并做字符串注入，
插件升级一旦改结构就可能"注入失败但仍旧全绿"。这里把解析与注入契约钉死：
结构正常 → 仪表盘完整；结构变化 → 明确抛错，不再静默降级。
"""
import html
import json

import pytest

from framework import hooks
from framework.reporting import enhancer
from framework.state import state


def _call(method='/api/health', status=200, code=200, ok=True):
    return ('<div data-method="%s" data-path="%s" data-status="%s" '
            'data-code="%s" data-ms="12" data-ok="%s"></div>'
            % (method, method, status, code, str(ok).lower()))


def _golden(tests=None):
    """构造最小 pytest-html 报告：data-jsonblob 是 HTML 转义后的 JSON。"""
    payload = {'tests': tests or {
        'projects/shopping/testcases/test_a.py::test_ok': [{
            'result': 'Passed', 'duration': '9 ms',
            'extras': [{'format_type': 'html', 'content': _call()}],
        }],
        'projects/shopping/testcases/test_b.py::test_bad': [{
            'result': 'Failed', 'duration': '1.2 s', 'extras': [],
        }],
    }}
    blob = html.escape(json.dumps(payload), quote=True)
    return '<html><head><title>report</title></head><body><div data-jsonblob="%s"></div></body></html>' % blob


@pytest.fixture(autouse=True)
def clean_state():
    state.reset()
    yield
    state.reset()


class TestGoldenReport:
    def test_enhances_dashboard_and_stats(self, tmp_path):
        target = tmp_path / 'report.html'
        target.write_text(_golden(), encoding='utf-8')
        enhancer.enhance(target, project_label='SHOPPING', base_url='http://x')
        text = target.read_text(encoding='utf-8')
        assert 'id="enh-dashboard"' in text
        assert '.enh-root{' in text and 'function enhToggleAll' in text
        # 2 条用例：1 passed / 1 failed；1 次接口调用
        assert '<div class="enh-kpi-value">2</div>' in text
        assert '<div class="enh-kpi-value">1</div>' in text
        assert '/api/health' in text
        assert 'SHOPPING' in text and 'http://x' in text

    def test_enhance_is_idempotent(self, tmp_path):
        target = tmp_path / 'report.html'
        target.write_text(_golden(), encoding='utf-8')
        enhancer.enhance(target)
        first = target.read_text(encoding='utf-8')
        enhancer.enhance(target)
        assert target.read_text(encoding='utf-8') == first
        assert first.count('id="enh-dashboard"') == 1

    def test_business_code_and_http_status_are_separate(self, tmp_path):
        tests = {
            'a.py::test_http_ok_biz_fail': [{
                'result': 'Passed', 'duration': '5 ms',
                'extras': [{'format_type': 'html',
                            'content': _call(status=200, code=500, ok=False)}],
            }],
        }
        target = tmp_path / 'report.html'
        target.write_text(_golden(tests), encoding='utf-8')
        enhancer.enhance(target)
        text = target.read_text(encoding='utf-8')
        assert '2xx 成功' in text
        assert 'code 500' in text
        assert '业务口径统计' in text


class TestStructureChangesFailLoudly:
    @pytest.mark.parametrize('anchor', ['</head>', '<body>', '</body>'])
    def test_missing_anchor_raises(self, tmp_path, anchor):
        target = tmp_path / 'report.html'
        target.write_text(_golden().replace(anchor, ''), encoding='utf-8')
        with pytest.raises(ValueError, match='注入锚点'):
            enhancer.enhance(target)
        assert target.read_text(encoding='utf-8') == _golden().replace(anchor, '')

    def test_missing_jsonblob_raises(self, tmp_path):
        target = tmp_path / 'report.html'
        target.write_text('<html><head></head><body></body></html>', encoding='utf-8')
        with pytest.raises(ValueError, match='未找到 pytest-html 数据块'):
            enhancer.enhance(target)

    def test_broken_jsonblob_raises(self, tmp_path):
        target = tmp_path / 'report.html'
        target.write_text(
            '<html><head></head><body><div data-jsonblob="{broken">',
            encoding='utf-8',
        )
        with pytest.raises(ValueError):
            enhancer.enhance(target)


class TestEnhanceFailureVisible:
    def test_record_error_writes_run_summary(self, tmp_path, monkeypatch):
        monkeypatch.setattr(hooks, 'reports_dir', lambda: tmp_path / 'reports')
        (tmp_path / 'reports').mkdir()
        summary = tmp_path / 'reports' / 'run_summary.json'
        summary.write_text(json.dumps({'passed': 1}), encoding='utf-8')
        hooks._record_enhance_error('结构变了')
        payload = json.loads(summary.read_text(encoding='utf-8'))
        assert payload['passed'] == 1
        assert payload['report_enhance_error'] == '结构变了'

    def test_record_error_tolerates_missing_summary(self, tmp_path, monkeypatch):
        monkeypatch.setattr(hooks, 'reports_dir', lambda: tmp_path / 'reports')
        (tmp_path / 'reports').mkdir()
        hooks._record_enhance_error('boom')  # 不应抛
        payload = json.loads(
            (tmp_path / 'reports' / 'run_summary.json').read_text(encoding='utf-8'))
        assert payload['report_enhance_error'] == 'boom'

    def test_unconfigure_marks_failure_in_report_and_summary(self, tmp_path, monkeypatch):
        """增强失败：测试结论不变，但报告横幅与 run_summary 都必须留痕。"""
        monkeypatch.setattr(hooks, 'reports_dir', lambda: tmp_path / 'reports')
        reports = tmp_path / 'reports'
        reports.mkdir()
        (reports / 'run_summary.json').write_text(json.dumps({'passed': 1}), encoding='utf-8')
        target = reports / 'report.html'
        # 缺 data-jsonblob → enhancer 明确抛错
        target.write_text('<html><head></head><body></body></html>', encoding='utf-8')

        class _Options:
            htmlpath = str(target)

        class _Config:
            option = _Options()
            rootpath = tmp_path

            def getoption(self, name, default=None):
                return False

        hooks.pytest_unconfigure(_Config())

        assert any('pytest-html' in err for err in hooks.REPORT_ENHANCE_ERROR)
        assert '报告增强失败' in target.read_text(encoding='utf-8')
        payload = json.loads((reports / 'run_summary.json').read_text(encoding='utf-8'))
        assert 'report_enhance_error' in payload

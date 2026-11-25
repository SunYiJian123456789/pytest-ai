# -*- coding: utf-8 -*-
"""内核单测：路径归一化、清单校验、覆盖率报告与 xdist 合并，不依赖真实服务。"""
import json

import pytest

from framework import coverage


@pytest.fixture(autouse=True)
def clean_hits():
    coverage.reset()
    yield
    coverage.reset()


class TestNormalizePath:
    @pytest.mark.parametrize('url,expected', [
        ('http://127.0.0.1:8080/api/cart/12', '/api/cart/{id}'),
        ('http://h/api/admin/products/1509/status', '/api/admin/products/{id}/status'),
        ('http://h/api/admin/approvals/1509/approve', '/api/admin/approvals/{id}/approve'),
        ('http://h/images/upload-abc123.png', '/images/{file}'),
        ('http://h/api/products/7?page=2', '/api/products/{id}'),
        ('/api/admin/approvals/pending-count', '/api/admin/approvals/pending-count'),
        ('/api/admin/products/batch-status', '/api/admin/products/batch-status'),
    ])
    def test_normalizes_dynamic_segments(self, url, expected):
        assert coverage.normalize_path(url) == expected

    def test_strips_query_and_trailing_slash(self):
        assert coverage.normalize_path('/api/products/?page=1') == '/api/products'
        assert coverage.normalize_path('/api/products/') == '/api/products'

    def test_root(self):
        assert coverage.normalize_path('http://h/') == '/'


class TestRecord:
    def test_accumulates_same_endpoint(self):
        coverage.record('get', 'http://h/api/cart/1', 200)
        coverage.record('GET', 'http://h/api/cart/2', 200)
        coverage.record('GET', 'http://h/api/cart/3', 400)
        hits = coverage.snapshot()
        assert hits['GET /api/cart/{id}']['count'] == 3
        assert hits['GET /api/cart/{id}']['statuses'] == {'200': 2, '400': 1}

    def test_method_is_case_insensitive(self):
        coverage.record('post', 'http://h/api/pay', 200)
        assert 'POST /api/pay' in coverage.snapshot()


class TestInventory:
    def test_loads_and_normalizes_method(self, tmp_path):
        path = tmp_path / 'inv.yaml'
        path.write_text(
            'endpoints:\n'
            '  - {method: get, path: /api/health, name: 健康, group: 公开}\n',
            encoding='utf-8',
        )
        rows = coverage.load_inventory(path)
        assert rows == [{'method': 'GET', 'path': '/api/health', 'name': '健康',
                         'group': '公开', 'covered_by': []}]

    def test_rejects_missing_field(self, tmp_path):
        path = tmp_path / 'inv.yaml'
        path.write_text('endpoints:\n  - {method: GET}\n', encoding='utf-8')
        with pytest.raises(ValueError, match='缺少字段'):
            coverage.load_inventory(path)

    def test_rejects_duplicate(self, tmp_path):
        path = tmp_path / 'inv.yaml'
        path.write_text(
            'endpoints:\n'
            '  - {method: GET, path: /api/x}\n'
            '  - {method: get, path: /api/x}\n',
            encoding='utf-8',
        )
        with pytest.raises(ValueError, match='重复登记'):
            coverage.load_inventory(path)

    def test_rejects_empty(self, tmp_path):
        path = tmp_path / 'inv.yaml'
        path.write_text('version: 1\n', encoding='utf-8')
        with pytest.raises(ValueError, match='endpoints'):
            coverage.load_inventory(path)


INVENTORY = [
    {'method': 'GET', 'path': '/api/health', 'name': '健康', 'group': '公开', 'covered_by': []},
    {'method': 'GET', 'path': '/api/cart', 'name': '购物车', 'group': '用户', 'covered_by': []},
    {'method': 'DELETE', 'path': '/api/cart/{id}', 'name': '删项', 'group': '用户', 'covered_by': []},
]


class TestBuildReport:
    def test_counts_covered_and_missed(self):
        coverage.record('GET', 'http://h/api/health', 200)
        coverage.record('GET', 'http://h/api/cart', 200)
        report = coverage.build_report(INVENTORY)
        assert report['total'] == 3
        assert report['covered'] == 2
        assert report['ratio'] == pytest.approx(0.6667, abs=1e-4)
        assert [row['path'] for row in report['missed']] == ['/api/cart/{id}']

    def test_dynamic_path_matches_placeholder(self):
        coverage.record('DELETE', 'http://h/api/cart/42', 200)
        report = coverage.build_report(INVENTORY)
        row = [r for r in report['rows'] if r['path'] == '/api/cart/{id}'][0]
        assert row['covered'] and row['count'] == 1

    def test_reports_unexpected_requests(self):
        coverage.record('GET', 'http://h/api/__not_exists__', 404)
        report = coverage.build_report(INVENTORY)
        assert report['covered'] == 0
        assert report['unexpected'] == [
            {'method': 'GET', 'path': '/api/__not_exists__', 'count': 1,
             'success': 0, 'statuses': {'404': 1}},
        ]

    def test_accepts_tuple_keyed_hits(self):
        hits = {('GET', '/api/health'): {'count': 2, 'statuses': {'200': 2}}}
        report = coverage.build_report(INVENTORY, hits)
        assert report['covered'] == 1
        assert report['rows'][0]['count'] == 2


class TestRender:
    def test_markdown_contains_ratio_and_sections(self):
        coverage.record('GET', 'http://h/api/health', 200)
        coverage.record('GET', 'http://h/api/nope', 404)
        text = coverage.render_markdown(coverage.build_report(INVENTORY))
        assert '触达 **1 / 3' in text
        assert '## 公开' in text and '## 用户' in text
        assert '未触达（2）' in text
        assert '清单外请求（1）' in text and '/api/nope' in text

    def test_terminal_summary_is_compact(self):
        coverage.record('GET', 'http://h/api/health', 200)
        text = coverage.render_terminal(coverage.build_report(INVENTORY))
        assert text.startswith('[coverage] 本次运行接口覆盖率 1/3 = 33.3%')
        assert '未触达 2 条' in text


class TestXDistsMerge:
    def test_dump_and_merge_from_workers(self, tmp_path):
        coverage.record('GET', 'http://h/api/health', 200)
        coverage.dump(tmp_path / '.api_coverage_gw0.json')

        coverage.reset()
        coverage.record('GET', 'http://h/api/cart', 200)
        coverage.record('GET', 'http://h/api/cart', 200)
        coverage.dump(tmp_path / '.api_coverage_gw1.json')

        coverage.reset()
        coverage.load_dumps(tmp_path)

        hits = coverage.snapshot()
        assert hits['GET /api/health']['count'] == 1
        assert hits['GET /api/cart']['count'] == 2
        assert not list(tmp_path.glob('.api_coverage_*.json')), '合并后应清理临时文件'

    def test_broken_worker_file_is_ignored(self, tmp_path):
        (tmp_path / '.api_coverage_bad.json').write_text('not json', encoding='utf-8')
        coverage.load_dumps(tmp_path)  # 不抛
        assert coverage.snapshot() == {}

    def test_collect_main_without_inventory_returns_empty(self, tmp_path):
        coverage.configure(None)
        assert coverage.collect_main(tmp_path) == {}


class TestWriteReports:
    def test_writes_json_and_markdown(self, tmp_path):
        coverage.record('GET', 'http://h/api/health', 200)
        report = coverage.build_report(INVENTORY)
        paths = coverage.write_reports(tmp_path, report)
        assert json.loads(open(paths['json'], encoding='utf-8').read())['covered'] == 1
        assert '# 接口覆盖率' in open(paths['markdown'], encoding='utf-8').read()


class TestCli:
    def _dump(self, tmp_path, covered=2, total=4):
        report = dict(coverage.build_report(INVENTORY),
                      total=total, covered=covered,
                      ratio=round(covered / total, 4))
        path = tmp_path / 'api_coverage.json'
        path.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
        return str(path)

    def test_missing_report_returns_2(self, tmp_path, capsys):
        code = coverage.main(['--report', str(tmp_path / 'nope.json')])
        assert code == 2
        assert '找不到覆盖率报告' in capsys.readouterr().out

    def test_threshold_pass_returns_0(self, tmp_path, capsys):
        code = coverage.main(['--report', self._dump(tmp_path, 2, 4), '--min', '50'])
        assert code == 0
        assert '达标' in capsys.readouterr().out

    def test_threshold_fail_returns_1(self, tmp_path, capsys):
        code = coverage.main(['--report', self._dump(tmp_path, 2, 4), '--min', '60'])
        assert code == 1
        assert '低于阈值' in capsys.readouterr().out

    def test_markdown_format(self, tmp_path, capsys):
        coverage.main(['--report', self._dump(tmp_path), '--format', 'md'])
        assert '# 接口覆盖率' in capsys.readouterr().out


class TestEffectiveCoverage:
    def test_success_count_tracks_ok_flag(self):
        coverage.record('GET', 'http://h/api/health', 200, ok=True)
        coverage.record('GET', 'http://h/api/health', 200, ok=False)
        coverage.record('GET', 'http://h/api/health', 500, ok=False)
        hits = coverage.snapshot()
        assert hits['GET /api/health']['count'] == 3
        assert hits['GET /api/health']['success'] == 1
        assert hits['GET /api/health']['statuses'] == {'200': 2, '500': 1}

    def test_default_ok_infers_from_status(self):
        coverage.record('GET', 'http://h/api/health', 200)   # 无 ok → 2xx 视为有效
        coverage.record('GET', 'http://h/api/cart', 404)     # 无 ok → 非 2xx 无效
        report = coverage.build_report(INVENTORY)
        assert report['effective'] == 1
        assert report['effective_ratio'] == pytest.approx(0.3333, abs=1e-4)

    def test_touched_but_no_success_is_ineffective(self):
        coverage.record('GET', 'http://h/api/health', 500, ok=False)
        report = coverage.build_report(INVENTORY)
        assert report['covered'] == 1
        assert report['effective'] == 0
        assert [row['path'] for row in report['ineffective']] == ['/api/health']

    def test_business_failure_on_200_is_not_effective(self):
        """HTTP 200 但业务 code≠200 由 result.ok=False 传入，只算触达。"""
        coverage.record('POST', 'http://h/api/pay', 200, ok=False)
        hits = coverage.snapshot()
        assert hits['POST /api/pay']['count'] == 1
        assert hits['POST /api/pay']['success'] == 0

    def test_report_rows_carry_both_flags(self):
        coverage.record('GET', 'http://h/api/health', 200, ok=True)
        report = coverage.build_report(INVENTORY)
        row = report['rows'][0]
        assert row['covered'] is True and row['effective'] is True
        assert row['success'] == 1

    def test_render_shows_both_metrics(self):
        coverage.record('GET', 'http://h/api/health', 200, ok=True)
        text = coverage.render_markdown(coverage.build_report(INVENTORY))
        assert '触达 **1 / 3' in text
        assert '有效覆盖 1 / 3' in text
        assert '成功' in text and '有效' in text

    def test_terminal_shows_effective_line(self):
        coverage.record('GET', 'http://h/api/health', 200, ok=True)
        text = coverage.render_terminal(coverage.build_report(INVENTORY))
        assert '其中有效覆盖 1/3 = 33.3%' in text

    def test_merge_infers_success_for_legacy_payload(self):
        """旧 worker 文件没有 success 字段：按 HTTP 2xx 推断，不判成零有效。"""
        legacy = {'GET /api/health': {'count': 2, 'statuses': {'200': 1, '500': 1}}}
        coverage._merge_hits(legacy)
        assert coverage.snapshot()['GET /api/health']['success'] == 1


class TestAllowedUnexpected:
    def test_known_extra_is_separated_from_violations(self):
        coverage.record('GET', 'http://h/api/known', 404, ok=False)
        coverage.record('GET', 'http://h/api/unknown', 404, ok=False)
        report = coverage.build_report(INVENTORY, allowed_extra={('GET', '/api/known')})
        assert [row['path'] for row in report['unexpected']] == ['/api/unknown']
        assert [row['path'] for row in report['known_extra']] == ['/api/known']

    def test_load_allowed_extra_from_inventory(self, tmp_path):
        path = tmp_path / 'inv.yaml'
        path.write_text(
            'version: 1\n'
            'allowed_unexpected:\n'
            '  - GET /api/__not_exists__\n'
            'endpoints:\n'
            '  - {method: GET, path: /api/health}\n',
            encoding='utf-8',
        )
        assert coverage.load_allowed_extra(path) == {('GET', '/api/__not_exists__')}

    def test_configure_loads_whitelist(self, tmp_path):
        path = tmp_path / 'inv.yaml'
        path.write_text(
            'allowed_unexpected: ["POST /api/x"]\n'
            'endpoints:\n'
            '  - {method: GET, path: /api/health}\n',
            encoding='utf-8',
        )
        coverage.configure(path)
        try:
            from framework.state import state
            assert ('POST', '/api/x') in state.coverage_allowed_extra
        finally:
            coverage.configure(None)

    def test_bad_whitelist_entry_is_rejected(self, tmp_path):
        path = tmp_path / 'inv.yaml'
        path.write_text('allowed_unexpected: ["/no-method"]\nendpoints: []\n', encoding='utf-8')
        with pytest.raises(ValueError, match='METHOD /path'):
            coverage.load_allowed_extra(path)


class TestCliGate:
    def _dump(self, tmp_path, *, covered=2, effective=1, total=4, unexpected=None):
        report = dict(coverage.build_report(INVENTORY), total=total,
                      covered=covered, ratio=round(covered / total, 4),
                      effective=effective, effective_ratio=round(effective / total, 4))
        if unexpected is not None:
            report['unexpected'] = unexpected
        path = tmp_path / 'api_coverage.json'
        path.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
        return str(path)

    def test_effective_metric_pass(self, tmp_path, capsys):
        code = coverage.main(['--report', self._dump(tmp_path, effective=3, total=4),
                              '--metric', 'effective', '--min', '70'])
        assert code == 0
        assert '有效覆盖率' in capsys.readouterr().out

    def test_effective_metric_fails(self, tmp_path, capsys):
        code = coverage.main(['--report', self._dump(tmp_path, effective=1, total=4),
                              '--metric', 'effective', '--min', '70'])
        assert code == 1
        assert '低于阈值' in capsys.readouterr().out

    def test_touched_metric_still_default(self, tmp_path, capsys):
        code = coverage.main(['--report', self._dump(tmp_path, covered=3, effective=1),
                              '--min', '70'])
        assert code == 0
        assert '触达覆盖率' in capsys.readouterr().out

    def test_fail_on_unexpected(self, tmp_path, capsys):
        code = coverage.main([
            '--report', self._dump(tmp_path, unexpected=[
                {'method': 'GET', 'path': '/api/new', 'count': 1,
                 'success': 0, 'statuses': {'404': 1}}]),
            '--fail-on-unexpected',
        ])
        assert code == 1
        assert '清单外请求' in capsys.readouterr().out

    def test_unexpected_allowed_by_default(self, tmp_path):
        code = coverage.main([
            '--report', self._dump(tmp_path, unexpected=[
                {'method': 'GET', 'path': '/api/new', 'count': 1,
                 'success': 0, 'statuses': {'404': 1}}]),
        ])
        assert code == 0

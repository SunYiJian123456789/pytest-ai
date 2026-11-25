# -*- coding: utf-8 -*-
"""内核单测：SessionState 的集中状态语义。

覆盖三件改造承诺：
1. reset 原地清空——各模块保留的兼容别名仍指向同一对象；
2. namespace 按名隔离，业务槽位不串；
3. xdist 分区统一落盘/合并，坏文件不炸、并发写入不丢计数。
"""
import json
import threading

import pytest

from framework import cleanup, config, coverage, preflight
from framework.state import DEFAULT_REPORT_OPTIONS, state


@pytest.fixture(autouse=True)
def clean_state():
    state.reset()
    yield
    state.reset()


class TestAliasesStayLiveAcrossReset:
    def test_module_aliases_point_to_state_containers(self):
        assert config.MISSING_REQUIRED is state.missing_required
        assert preflight.RECORDS is state.preflight_records
        assert coverage.HITS is state.coverage_hits
        assert cleanup.CLEANUP_LOG is state.cleanup_log

    def test_clear_via_alias_is_visible_in_state(self):
        state.missing_required['K'] = 'default'
        config.MISSING_REQUIRED.clear()
        assert state.missing_required == {}

    def test_full_reset_keeps_alias_identity(self):
        aliases = [config.MISSING_REQUIRED, preflight.RECORDS,
                   coverage.HITS, cleanup.CLEANUP_LOG]
        state.missing_required['K'] = 'v'
        coverage.record('GET', '/api/x')
        state.reset()
        assert all(a is b for a, b in zip(
            aliases, [state.missing_required, state.preflight_records,
                      state.coverage_hits, state.cleanup_log]))
        assert not state.missing_required and not state.coverage_hits

    def test_targeted_reset_does_not_touch_other_domains(self):
        state.missing_required['K'] = 'v'
        coverage.record('GET', '/api/x')
        state.reset_coverage()
        assert state.missing_required == {'K': 'v'}
        assert state.coverage_hits == {}


class TestNamespaces:
    def test_same_name_returns_same_dict(self):
        assert state.namespace('shopping.tokens') is state.namespace('shopping.tokens')

    def test_different_names_are_isolated(self):
        a = state.namespace('proj_a')
        b = state.namespace('proj_b')
        a['user'] = 'alice'
        assert 'user' not in b

    def test_reset_clears_namespaces(self):
        state.namespace('shopping.tokens')['admin'] = 't'
        state.reset()
        assert state.namespace('shopping.tokens') == {}


class TestWorkerPartitions:
    def test_both_partitions_registered(self):
        assert {'coverage', 'cleanup'} <= set(state._partitions)

    def test_dump_worker_writes_both_files(self, tmp_path):
        coverage.record('GET', '/api/health', 200)
        state.cleanup_log.append({'action': 'drop', 'state': 'OK', 'detail': ''})
        state.dump_worker(tmp_path, 'gw0')
        names = sorted(p.name for p in tmp_path.glob('*.json'))
        assert names == ['.api_coverage_gw0.json', '.cleanup_gw0.json']

    def test_load_workers_merges_and_cleans_temp_files(self, tmp_path):
        state.dump_partition('coverage', tmp_path / '.api_coverage_gw0.json')
        (tmp_path / '.api_coverage_gw1.json').write_text(json.dumps({
            'GET /api/health': {'count': 2, 'statuses': {'200': 1, '500': 1}},
        }), encoding='utf-8')
        (tmp_path / '.cleanup_gw0.json').write_text(json.dumps([
            {'action': 'drop', 'state': 'OK', 'detail': ''},
        ]), encoding='utf-8')

        state.reset_coverage()
        state.reset_cleanup()
        state.load_workers(tmp_path)

        hits = coverage.snapshot()
        assert hits['GET /api/health']['count'] == 2
        assert hits['GET /api/health']['statuses'] == {'200': 1, '500': 1}
        assert len(state.cleanup_log) == 1
        assert not list(tmp_path.glob('.*.json')), '合并后应清理临时文件'

    def test_broken_partition_file_is_ignored(self, tmp_path):
        (tmp_path / '.api_coverage_bad.json').write_text('not json', encoding='utf-8')
        state.load_workers(tmp_path)
        assert state.coverage_hits == {}


class TestConcurrency:
    def test_parallel_records_do_not_lose_counts(self):
        barrier = threading.Barrier(8)

        def worker(index):
            barrier.wait()
            for _ in range(50):
                coverage.record('GET', '/api/parallel', 200)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert coverage.snapshot()['GET /api/parallel']['count'] == 400


class TestReportOptionsInState:
    def test_defaults_live_in_state(self):
        assert state.report_options['success_code'] == DEFAULT_REPORT_OPTIONS['success_code']

    def test_reset_restores_defaults(self):
        state.report_options['title'] = 'custom'
        state.report_enhance_errors.append('boom')
        state.reset()
        assert state.report_options == DEFAULT_REPORT_OPTIONS
        assert state.report_enhance_errors == []

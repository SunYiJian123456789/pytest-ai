# -*- coding: utf-8 -*-
"""兜底清理内核单测：只测调度/安全/记录，不依赖真实数据库。

重点钉死三件事：
1. 前缀白名单由内核二次校验，discover 扫宽了也不会误删真实数据；
2. 单个扫描器失败不影响其他扫描器，且失败可见；
3. 兜底记录与注册式清理在报告里分开统计。
"""
from types import SimpleNamespace

import pytest

from framework import cleanup
from framework.state import state


def _result(ok=True, skipped=False, error='', message=''):
    return SimpleNamespace(ok=ok, skipped=skipped, error=error, message=message)


@pytest.fixture(autouse=True)
def clean_state():
    state.reset()
    yield
    state.reset()


class TestSweepSecurity:
    def test_prefix_filter_blocks_real_data(self):
        deleted = []
        cleanup.register_sweep(
            'API 测试用户',
            discover=lambda: ['APIU1234', 'real-user', 'API'],
            clean=lambda key: deleted.append(key) or _result(),
            prefixes=('API',),
        )
        rows = cleanup.run_sweeps()
        assert deleted == ['APIU1234', 'API']
        assert len(rows) == 3  # 2 条 OK + 1 条「不在前缀内」的 FAIL
        assert rows[1]['state'] == 'FAIL'
        assert '不在允许前缀' in rows[1]['detail']
        assert all(row.get('sweep') for row in rows)

    def test_empty_prefixes_trusts_business(self):
        deleted = []
        cleanup.register_sweep(
            'any', discover=lambda: ['x'],
            clean=lambda key: deleted.append(key) or _result(),
        )
        cleanup.run_sweeps()
        assert deleted == ['x']

    def test_non_string_keys_are_ignored(self):
        seen = []
        cleanup.register_sweep(
            'any', discover=lambda: [None, 123, '', 'API-X'],
            clean=lambda key: seen.append(key) or _result(),
        )
        cleanup.run_sweeps()
        assert seen == ['API-X']


class TestSweepIsolation:
    def test_failed_scan_does_not_block_others(self):
        seen = []
        cleanup.register_sweep(
            'bad', discover=lambda: (_ for _ in ()).throw(RuntimeError('db down')),
            clean=lambda key: _result(),
        )
        cleanup.register_sweep(
            'good', discover=lambda: ['API-OK'],
            clean=lambda key: seen.append(key) or _result(),
        )
        rows = cleanup.run_sweeps()
        assert seen == ['API-OK']
        assert rows[0]['state'] == 'FAIL' and rows[0]['action'] == 'sweep scan bad'
        assert 'db down' in rows[0]['detail']
        assert rows[1]['state'] == 'OK'

    def test_failed_clean_keeps_other_items(self):
        seen = []
        cleanup.register_sweep(
            'x', discover=lambda: ['API-1', 'API-2'],
            clean=lambda key: (_result(ok=False, message='boom') if key == 'API-1'
                               else seen.append(key) or _result()),
            fallback='fallback',
        )
        rows = cleanup.run_sweeps()
        assert seen == ['API-2']
        assert rows[0]['state'] == 'FAIL' and 'boom' in rows[0]['detail']
        assert rows[1]['state'] == 'OK'

    def test_skipped_result_is_recorded(self):
        cleanup.register_sweep(
            'x', discover=lambda: ['API-1'],
            clean=lambda key: _result(skipped=True, error='no driver'),
        )
        rows = cleanup.run_sweeps()
        assert rows[0]['state'] == 'SKIP' and 'no driver' in rows[0]['detail']

    def test_run_sweeps_twice_is_not_idempotent(self):
        """业务 discover 应反映当前残留；内核不缓存，重复调用会重复删。"""
        calls = []
        cleanup.register_sweep('x', discover=lambda: ['API-1'],
                               clean=lambda key: calls.append(key) or _result())
        cleanup.run_sweeps()
        cleanup.run_sweeps()
        assert calls == ['API-1', 'API-1']


class TestSweepReporting:
    def test_registered_and_sweep_rows_are_separate_in_banner(self):
        cleanup.record('delete product 1', _result())
        cleanup.register_sweep('x', discover=lambda: ['API-1'],
                               clean=lambda key: _result(ok=False, message='boom'))
        cleanup.run_sweeps()
        text = cleanup.cleanup_banner_html()
        assert '注册式清理 1 项' in text
        assert '兜底清理 1 项' in text
        assert '[兜底/FAIL]' in text

    def test_banner_empty_when_no_cleanup(self):
        assert cleanup.cleanup_banner_html() == ''

    def test_inject_banner_is_idempotent(self, tmp_path):
        target = tmp_path / 'report.html'
        target.write_text('<html><body></body></html>', encoding='utf-8')
        cleanup.register_sweep('x', discover=lambda: ['API-1'],
                               clean=lambda key: _result())
        cleanup.run_sweeps()
        cleanup.inject_banner(target)
        first = target.read_text(encoding='utf-8')
        cleanup.inject_banner(target)
        assert target.read_text(encoding='utf-8') == first
        assert first.count('enh-cleanup') == 1


class TestSweepStateIsolation:
    def test_reset_clears_registered_providers(self):
        cleanup.register_sweep('x', discover=lambda: [], clean=lambda key: _result())
        state.reset()
        assert state.namespace(cleanup.SWEEP_KEY) == {}
        assert cleanup.run_sweeps() == []

    def test_providers_are_not_shared_across_xdist_processes(self):
        """注册表在进程私有 namespace 中，worker 各自注册不会跨进程串。"""
        cleanup.register_sweep('local', discover=lambda: [], clean=lambda key: _result())
        assert len(state.namespace(cleanup.SWEEP_KEY)['providers']) == 1
        other = state.namespace('other.scope')
        assert 'providers' not in other

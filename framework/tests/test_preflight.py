# -*- coding: utf-8 -*-
"""启动体检内核单测：检查聚合、必检/非必检降级、开关、输出格式与结果沉淀。

不依赖被测服务：所有检查项都用假函数。
"""
import pytest

from framework.preflight import RECORDS, Check, Preflight, Skipped, records


def ok_check(name='通过项', detail='done', **kw):
    return Check(name, lambda: detail, **kw)


def boom_check(name='失败项', message='连接被拒绝', **kw):
    def run():
        raise AssertionError(message)

    return Check(name, run, **kw)


@pytest.fixture(autouse=True)
def clear_records():
    RECORDS.clear()
    yield
    RECORDS.clear()


class TestRun:
    def test_all_pass_keeps_detail(self):
        results = Preflight([ok_check()], strict=True).run()
        assert [row.state for row in results] == ['OK']
        assert results[0].detail == 'done'
        assert results[0].elapsed_ms >= 0

    def test_collects_all_failures_instead_of_stopping(self):
        """一轮把问题说全：某检查失败不跳过后续检查。"""
        calls = []

        def first():
            calls.append('first')
            raise AssertionError('第一项失败')

        def second():
            calls.append('second')
            return 'ok'

        def third():
            calls.append('third')
            raise AssertionError('第三项失败')

        result = Preflight([
            Check('一', first), Check('二', second), Check('三', third),
        ]).run()
        assert calls == ['first', 'second', 'third']
        assert [row.state for row in result] == ['FAIL', 'OK', 'FAIL']

    def test_optional_failure_degrades_to_warn(self):
        preflight = Preflight([boom_check(required=False)])
        preflight.run()
        assert preflight.passed is True
        assert preflight.results[0].state == 'WARN'

    def test_strict_false_turns_required_failure_into_warn(self):
        preflight = Preflight([boom_check()], strict=False)
        preflight.run()
        assert preflight.passed is True
        assert preflight.results[0].state == 'WARN'

    def test_disabled_skips_every_check(self):
        calls = []
        preflight = Preflight([Check('不该执行', lambda: calls.append(1))], enabled=False)
        assert preflight.run() == []
        assert calls == []

    def test_false_return_is_failure(self):
        preflight = Preflight([Check('返回 False', lambda: False)])
        preflight.run()
        assert preflight.results[0].state == 'FAIL'
        assert 'False' in preflight.results[0].detail

    def test_non_assertion_error_keeps_type_name(self):
        def boom():
            raise TimeoutError('timed out')

        preflight = Preflight([Check('超时', boom)])
        preflight.run()
        assert preflight.results[0].state == 'FAIL'
        assert 'TimeoutError' in preflight.results[0].detail

    def test_multiline_detail_is_flattened(self):
        preflight = Preflight([boom_check(message='第一行\n第二行')])
        preflight.run()
        assert preflight.results[0].detail == '第一行 第二行'

    def test_long_detail_is_truncated(self):
        preflight = Preflight([boom_check(message='x' * 1000)])
        preflight.run()
        assert len(preflight.results[0].detail) <= 300

    def test_skip_is_not_failure_and_keeps_reason(self):
        """前置条件不满足时记 SKIP：不阻断，也不把「没测」算成「失败」。"""

        def skipped():
            raise Skipped('后端不可达，未执行登录校验')

        preflight = Preflight([ok_check(), Check('登录可用', skipped)])
        preflight.run()
        assert preflight.passed is True
        assert preflight.results[1].state == 'SKIP'
        assert '后端不可达' in preflight.results[1].detail
        assert preflight.warnings == []

    def test_summary_counts_skip(self):
        def skipped():
            raise Skipped('前置未满足')

        preflight = Preflight([boom_check('后端可达'), Check('登录可用', skipped)])
        preflight.run()
        text = preflight.summary()
        assert '1 项跳过' in text
        assert '[SKIP] 登录可用' in text

    def test_keyboard_interrupt_is_not_swallowed(self):
        """Ctrl+C 必须照常中断，不能被体检当成「某项失败」。"""

        def interrupted():
            raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            Preflight([Check('中断', interrupted)]).run()


class TestOutput:
    def test_summary_lists_each_row_and_hint(self):
        preflight = Preflight([
            ok_check('后端可达', 'HTTP 200'),
            boom_check('数据库可用', 'Access denied', hint='检查 SHOPPING_MYSQL_*'),
        ])
        preflight.run()
        text = preflight.summary()
        assert '2 项检查中 1 项失败' in text
        assert '[ OK ] 后端可达' in text
        assert '[FAIL] 数据库可用' in text
        assert 'Access denied' in text
        assert '提示：检查 SHOPPING_MYSQL_*' in text
        assert 'API_PREFLIGHT_STRICT=0' in text

    def test_summary_mentions_warn_count(self):
        preflight = Preflight([
            boom_check('后端可达'),
            boom_check('服务自检', required=False),
        ])
        preflight.run()
        assert '1 项告警' in preflight.summary()

    def test_summary_empty_when_all_pass(self):
        preflight = Preflight([ok_check()])
        preflight.run()
        assert preflight.summary() == ''

    def test_run_or_exit_raises_usage_error(self):
        with pytest.raises(pytest.UsageError) as exc:
            Preflight([boom_check()]).run_or_exit()
        assert '启动体检未通过' in str(exc.value)

    def test_run_or_exit_warns_instead_of_exiting_when_not_strict(self):
        with pytest.warns(UserWarning, match='告警'):
            Preflight([boom_check()], strict=False).run_or_exit()

    def test_run_or_exit_silent_when_all_pass(self):
        assert Preflight([ok_check()]).run_or_exit()[0].state == 'OK'


class TestRecords:
    def test_records_published_as_dicts(self):
        Preflight([ok_check('后端可达')]).run()
        rows = records()
        assert rows[0]['name'] == '后端可达' and rows[0]['state'] == 'OK'

    def test_records_returns_copy(self):
        Preflight([ok_check('后端可达')]).run()
        records()[0]['state'] = 'FAIL'
        assert records()[0]['state'] == 'OK'


class TestEnvFlags:
    def test_enabled_flag_from_env(self, monkeypatch):
        monkeypatch.setenv('API_PREFLIGHT_ENABLED', '0')
        assert Preflight([]).enabled is False

    def test_strict_flag_from_env(self, monkeypatch):
        monkeypatch.setenv('API_PREFLIGHT_STRICT', '0')
        assert Preflight([]).strict is False

    def test_defaults_when_env_absent(self, monkeypatch):
        monkeypatch.delenv('API_PREFLIGHT_ENABLED', raising=False)
        monkeypatch.delenv('API_PREFLIGHT_STRICT', raising=False)
        preflight = Preflight([])
        assert preflight.enabled is True and preflight.strict is True

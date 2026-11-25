# -*- coding: utf-8 -*-
"""内核单测：必填配置的「登记 + 体检」语义，不依赖真实服务。

核心约束：``require()`` 在 import 期不能抛错（否则 --collect-only 和任何
import 该模块的场景都会崩在堆栈里），缺项必须留给启动体检统一报。
"""
import pytest

from framework.config import (
    Settings, clear_missing_required, missing_required,
)


@pytest.fixture(autouse=True)
def clean_registry():
    clear_missing_required()
    yield
    clear_missing_required()


class TestRequireRegisters:
    def test_missing_key_is_registered_not_raised(self, monkeypatch):
        monkeypatch.delenv('TESTCFG_UPLOAD_DIR', raising=False)
        cfg = Settings('TESTCFG_')
        missing = cfg.require('UPLOAD_DIR')          # 不抛
        assert missing == ['TESTCFG_UPLOAD_DIR']
        assert missing_required() == {'TESTCFG_UPLOAD_DIR': 'default'}

    def test_present_key_registers_nothing(self, monkeypatch):
        monkeypatch.setenv('TESTCFG_UPLOAD_DIR', 'D:/uploads')
        assert Settings('TESTCFG_').require('UPLOAD_DIR') == []
        assert missing_required() == {}

    def test_collects_all_missing_at_once(self, monkeypatch):
        monkeypatch.delenv('TESTCFG_A', raising=False)
        monkeypatch.delenv('TESTCFG_B', raising=False)
        missing = Settings('TESTCFG_').require('A', 'B')
        assert sorted(missing) == ['TESTCFG_A', 'TESTCFG_B']
        assert set(missing_required()) == {'TESTCFG_A', 'TESTCFG_B'}

    def test_records_api_env(self, monkeypatch):
        monkeypatch.setattr('framework.config.ENV', 'staging')
        monkeypatch.delenv('TESTCFG_X', raising=False)
        Settings('TESTCFG_').require('X')
        assert missing_required() == {'TESTCFG_X': 'staging'}

    def test_empty_string_counts_as_missing(self, monkeypatch):
        monkeypatch.setenv('TESTCFG_X', '')
        assert Settings('TESTCFG_').require('X') == ['TESTCFG_X']


class TestStrictMode:
    def test_strict_raises_immediately(self, monkeypatch):
        monkeypatch.delenv('TESTCFG_X', raising=False)
        monkeypatch.setenv('API_CONFIG_STRICT', '1')
        with pytest.raises(ValueError, match='缺少必填配置'):
            Settings('TESTCFG_').require('X')

    @pytest.mark.parametrize('value', ['0', 'false', '', 'no'])
    def test_non_strict_values_do_not_raise(self, monkeypatch, value):
        monkeypatch.delenv('TESTCFG_X', raising=False)
        monkeypatch.setenv('API_CONFIG_STRICT', value)
        assert Settings('TESTCFG_').require('X') == ['TESTCFG_X']


class TestRegistry:
    def test_clear_resets(self, monkeypatch):
        monkeypatch.delenv('TESTCFG_X', raising=False)
        Settings('TESTCFG_').require('X')
        clear_missing_required()
        assert missing_required() == {}

    def test_snapshot_is_a_copy(self, monkeypatch):
        monkeypatch.delenv('TESTCFG_X', raising=False)
        Settings('TESTCFG_').require('X')
        snapshot = missing_required()
        snapshot.clear()
        assert missing_required() == {'TESTCFG_X': 'default'}, '快照不应影响内部登记表'

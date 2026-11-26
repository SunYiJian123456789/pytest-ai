# -*- coding: utf-8 -*-
"""路径语义单测：PACKAGE_ROOT（包自身）与 WORKSPACE_ROOT（调用方工作区）分离。

这是 pip 分发能否成立的地基——安装后包在 site-packages，报告却必须写在调用方
工作区。测试覆盖探测规则、显式覆盖优先级、校准后各模块是否同步到新路径。
"""
import importlib

import pytest

from framework import client, config, defects, hooks, scaffold


def _reload_config(monkeypatch, *, cwd, explicit=None):
    """在指定 cwd / 环境变量下重新加载 config，返回加载后的模块。"""
    monkeypatch.chdir(cwd)
    if explicit is None:
        monkeypatch.delenv('API_WORKSPACE_ROOT', raising=False)
    else:
        monkeypatch.setenv('API_WORKSPACE_ROOT', str(explicit))
    return importlib.reload(config)


class TestWorkspaceDetection:
    def test_source_repo_uses_package_root(self, tmp_path, monkeypatch):
        """cwd 在包根内（含子目录）时，工作区就是包根——源码仓库行为不变。"""
        pkg_root = config.PACKAGE_ROOT
        mod = _reload_config(monkeypatch, cwd=pkg_root / 'projects')
        try:
            assert mod.workspace_root() == pkg_root.resolve()
            assert mod.reports_dir() == pkg_root.resolve() / 'reports'
        finally:
            importlib.reload(config)

    def test_installed_mode_uses_cwd(self, tmp_path, monkeypatch):
        """cwd 在包根外时视为调用方工作区，报告不写进 site-packages。"""
        outside = tmp_path / 'consumer'
        outside.mkdir()
        mod = _reload_config(monkeypatch, cwd=outside)
        try:
            assert mod.workspace_root() == outside.resolve()
            assert mod.reports_dir() == outside.resolve() / 'reports'
        finally:
            importlib.reload(config)

    def test_explicit_env_wins(self, tmp_path, monkeypatch):
        """显式 API_WORKSPACE_ROOT 优先于 cwd 探测。"""
        cwd = tmp_path / 'cwd'
        cwd.mkdir()
        declared = tmp_path / 'declared'
        declared.mkdir()
        mod = _reload_config(monkeypatch, cwd=cwd, explicit=declared)
        try:
            assert mod.workspace_root() == declared.resolve()
        finally:
            importlib.reload(config)

    def test_package_root_never_follows_workspace(self, tmp_path, monkeypatch):
        """包根是固定的，工作区怎么变都不影响包内资源定位。"""
        before = config.package_root()
        outside = tmp_path / 'elsewhere'
        outside.mkdir()
        _reload_config(monkeypatch, cwd=outside)
        try:
            assert config.package_root() == before
        finally:
            importlib.reload(config)


class TestRecalibration:
    def test_set_workspace_root_updates_all_consumers(self, tmp_path, monkeypatch):
        """pytest_configure 校准后，client / defects / hooks 都指向新工作区。"""
        monkeypatch.delenv('API_WORKSPACE_ROOT', raising=False)
        original = config.workspace_root()
        target = tmp_path / 'ws'
        target.mkdir()
        try:
            config.set_workspace_root(target, reload_env=False)
            assert config.workspace_root() == target.resolve()
            assert config.ROOT == target.resolve()
            assert config.reports_dir() == target.resolve() / 'reports'
            assert client.ApiClient('http://x').reports_dir == target.resolve() / 'reports'
            assert defects.ledger_for_project('demo') == (
                target.resolve() / 'projects' / 'demo' / 'data' / 'known_defects.yaml')
            assert scaffold.create.__globals__['workspace_root']() == target.resolve()
        finally:
            config.set_workspace_root(original, reload_env=False)

    def test_explicit_env_not_overridden_by_rootdir(self, tmp_path, monkeypatch):
        """显式声明过工作区时，pytest 的 rootdir 不得悄悄覆盖。"""
        declared = tmp_path / 'declared'
        declared.mkdir()
        monkeypatch.setenv('API_WORKSPACE_ROOT', str(declared))
        other = tmp_path / 'rootdir'
        other.mkdir()
        try:
            result = config.set_workspace_root(other, reload_env=False)
            assert result == declared.resolve()
        finally:
            monkeypatch.delenv('API_WORKSPACE_ROOT', raising=False)


def test_hook_recalibrates_from_config_rootpath(tmp_path, monkeypatch):
    """pytest_configure 用 config.rootpath 校准，不需要业务 conftest 配合。"""
    monkeypatch.delenv('API_WORKSPACE_ROOT', raising=False)
    original = config.workspace_root()

    class _Opt:
        htmlpath = None

    class _Config:
        rootpath = tmp_path
        option = _Opt()

        def getoption(self, name, default=False):
            return default

    try:
        hooks.pytest_configure(_Config())
        assert config.workspace_root() == tmp_path.resolve()
    finally:
        config.set_workspace_root(original, reload_env=False)


def test_hooks_no_longer_expose_stale_root_alias():
    """内部模块不再持有 ROOT 快照，路径全部走动态函数。"""
    assert not hasattr(hooks, 'ROOT')
    assert callable(hooks.reports_dir)
    assert not hasattr(defects, 'ROOT')
    assert not hasattr(client, 'DEFAULT_REPORTS_DIR')


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__]))

# -*- coding: utf-8 -*-
"""framework.defects 的单测：不依赖被测后端，只校验台账规则本身。"""
import json

import pytest

from framework import defects
from framework.state import state

LEDGER_TEXT = """\
version: 1
defects:
  - id: DEF-001
    test: tests/test_a.py::test_one
    status: open
    title: 缺陷一
    symptom: 现象
    expected: 期望
    endpoint: POST /api/x
  - id: DEF-002
    test: tests/test_a.py::test_two
    status: fixed
    title: 缺陷二
    symptom: 现象
    expected: 期望
"""


def _write_ledger(tmp_path, text=LEDGER_TEXT):
    path = tmp_path / 'known_defects.yaml'
    path.write_text(text, encoding='utf-8')
    return path


def _manifest(collected, xfails=()):
    return {'count': len(collected), 'collected': list(collected),
            'xfails': list(xfails)}


def _xfail(nodeid, *, strict=True, reason='[DEF-001] 已知缺陷'):
    return {'nodeid': nodeid, 'strict': strict, 'reason': reason}


class _FakeItem:
    def __init__(self, nodeid, mark=None):
        self.nodeid = nodeid
        self._mark = mark

    def get_closest_marker(self, name):
        return self._mark if name == 'xfail' else None


class TestLoadLedger:
    def test_loads_valid_ledger(self, tmp_path):
        rows = defects.load_ledger(_write_ledger(tmp_path))
        assert [row['id'] for row in rows] == ['DEF-001', 'DEF-002']

    @pytest.mark.parametrize('field', ['id', 'test', 'status', 'title', 'symptom', 'expected'])
    def test_missing_required_field(self, tmp_path, field):
        old = '  - id: DEF-001' if field == 'id' else '    %s: ' % field
        new = '  - _id: DEF-001' if field == 'id' else '    _%s: ' % field
        text = LEDGER_TEXT.replace(old, new, 1)
        with pytest.raises(ValueError, match='缺少必填字段 %s' % field):
            defects.load_ledger(_write_ledger(tmp_path, text))

    def test_bad_id_format(self, tmp_path):
        text = LEDGER_TEXT.replace('DEF-001', 'BUG-1', 1)
        with pytest.raises(ValueError, match='DEF-001 格式'):
            defects.load_ledger(_write_ledger(tmp_path, text))

    def test_duplicate_id(self, tmp_path):
        text = LEDGER_TEXT.replace('DEF-002', 'DEF-001', 1)
        with pytest.raises(ValueError, match='编号重复'):
            defects.load_ledger(_write_ledger(tmp_path, text))

    def test_duplicate_test(self, tmp_path):
        text = LEDGER_TEXT.replace('tests/test_a.py::test_two',
                                   'tests/test_a.py::test_one', 1)
        with pytest.raises(ValueError, match='用例重复绑定'):
            defects.load_ledger(_write_ledger(tmp_path, text))

    def test_bad_status(self, tmp_path):
        text = LEDGER_TEXT.replace('status: fixed', 'status: closed', 1)
        with pytest.raises(ValueError, match='status 必须是 open/fixed'):
            defects.load_ledger(_write_ledger(tmp_path, text))

    def test_test_without_nodeid_separator(self, tmp_path):
        text = LEDGER_TEXT.replace('tests/test_a.py::test_one', 'test_one', 1)
        with pytest.raises(ValueError, match='nodeid'):
            defects.load_ledger(_write_ledger(tmp_path, text))

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            defects.load_ledger(tmp_path / 'nope.yaml')

    def test_missing_defects_key(self, tmp_path):
        with pytest.raises(ValueError, match='缺少 defects'):
            defects.load_ledger(_write_ledger(tmp_path, 'version: 1\n'))


class TestCollectManifest:
    def test_separates_xfails_from_all_items(self):
        one = _FakeItem('tests/test_a.py::test_one',
                        pytest.mark.xfail(strict=True, reason='[DEF-001] x').mark)
        two = _FakeItem('tests/test_a.py::test_two')
        manifest = defects.collect_manifest([one, two])
        assert manifest['count'] == 2
        assert manifest['collected'] == [one.nodeid, two.nodeid]
        assert manifest['xfails'][0]['strict'] is True
        assert '[DEF-001]' in manifest['xfails'][0]['reason']

    def test_write_and_load_roundtrip(self, tmp_path):
        manifest = _manifest(['a', 'b'], [_xfail('a')])
        path = defects.write_manifest(manifest, tmp_path / 'xfail_manifest.json')
        assert defects.load_manifest(path) == manifest

    def test_load_missing_manifest(self, tmp_path):
        with pytest.raises(FileNotFoundError, match='collect-only'):
            defects.load_manifest(tmp_path / 'none.json')


class TestCheck:
    def _ledger(self, tmp_path):
        return defects.load_ledger(_write_ledger(tmp_path))

    def test_consistent_ledger(self, tmp_path):
        manifest = _manifest(
            ['tests/test_a.py::test_one', 'tests/test_a.py::test_two'],
            [_xfail('tests/test_a.py::test_one')],
        )
        result = defects.check(self._ledger(tmp_path), manifest)
        assert result['ok'] is True and result['issues'] == []
        assert result['stats'] == {
            'ledger_total': 2, 'open': 1, 'fixed': 1, 'xfail_count': 1,
            'strict_xfail': 1, 'issues': 0,
        }

    def test_open_defect_without_xfail(self, tmp_path):
        manifest = _manifest(['tests/test_a.py::test_one', 'tests/test_a.py::test_two'])
        result = defects.check(self._ledger(tmp_path), manifest)
        assert result['ok'] is False
        assert 'status 改为 fixed' in result['issues'][0]['message']

    def test_fixed_defect_still_has_xfail(self, tmp_path):
        manifest = _manifest(
            ['tests/test_a.py::test_one', 'tests/test_a.py::test_two'],
            [_xfail('tests/test_a.py::test_two', reason='[DEF-002] x')],
        )
        result = defects.check(self._ledger(tmp_path), manifest)
        assert result['ok'] is False
        assert any('请删除标记' in item['message'] for item in result['issues'])

    def test_orphan_xfail(self, tmp_path):
        manifest = _manifest(
            ['tests/test_a.py::test_one', 'tests/test_a.py::test_two', 'tests/test_b.py::test_x'],
            [_xfail('tests/test_a.py::test_one'), _xfail('tests/test_b.py::test_x')],
        )
        result = defects.check(self._ledger(tmp_path), manifest)
        assert result['ok'] is False
        assert any('孤儿 xfail' in item['message'] for item in result['issues'])

    def test_non_strict_xfail(self, tmp_path):
        manifest = _manifest(
            ['tests/test_a.py::test_one', 'tests/test_a.py::test_two'],
            [_xfail('tests/test_a.py::test_one', strict=False)],
        )
        result = defects.check(self._ledger(tmp_path), manifest)
        assert result['ok'] is False
        assert 'strict=True' in result['issues'][0]['message']

    def test_reason_missing_defect_id(self, tmp_path):
        manifest = _manifest(
            ['tests/test_a.py::test_one', 'tests/test_a.py::test_two'],
            [_xfail('tests/test_a.py::test_one', reason='已知缺陷')],
        )
        result = defects.check(self._ledger(tmp_path), manifest)
        assert result['ok'] is False
        assert '无法反查台账' in result['issues'][0]['message']

    def test_ledger_references_missing_test(self, tmp_path):
        manifest = _manifest(['tests/test_a.py::test_two'])
        result = defects.check(self._ledger(tmp_path), manifest)
        assert result['ok'] is False
        assert '用例未被收集到' in result['issues'][0]['message']

    def test_issue_level_is_error(self, tmp_path):
        manifest = _manifest(['tests/test_a.py::test_two'])
        result = defects.check(self._ledger(tmp_path), manifest)
        assert {item['level'] for item in result['issues']} == {'error'}


class TestRender:
    def test_markdown_table_and_issue_section(self, tmp_path):
        ledger = defects.load_ledger(_write_ledger(tmp_path))
        result = defects.check(ledger, _manifest(['tests/test_a.py::test_two']))
        text = defects.render_markdown(ledger, result)
        assert '| 编号 | 用例 |' in text
        assert 'DEF-001' in text and 'POST /api/x' in text
        assert '## 校验问题' in text and '用例未被收集到' in text

    def test_terminal_ok_and_failure(self, tmp_path):
        ledger = defects.load_ledger(_write_ledger(tmp_path))
        good = defects.check(
            ledger,
            _manifest(['tests/test_a.py::test_one', 'tests/test_a.py::test_two'],
                      [_xfail('tests/test_a.py::test_one')]))
        assert '台账与用例一致' in defects.render_terminal(good)
        bad = defects.check(ledger, _manifest(['tests/test_a.py::test_two']))
        assert '发现 1 项不一致' in defects.render_terminal(bad)


class TestCli:
    def test_check_pass(self, tmp_path, capsys):
        ledger = _write_ledger(tmp_path)
        manifest = tmp_path / 'manifest.json'
        manifest.write_text(json.dumps(_manifest(
            ['tests/test_a.py::test_one', 'tests/test_a.py::test_two'],
            [_xfail('tests/test_a.py::test_one')])), encoding='utf-8')
        code = defects.main(['--ledger', str(ledger), '--manifest', str(manifest),
                             '--check'])
        assert code == 0
        assert '台账与用例一致' in capsys.readouterr().out

    def test_check_fails_on_stale_xfail(self, tmp_path, capsys):
        ledger = _write_ledger(tmp_path)
        manifest = tmp_path / 'manifest.json'
        manifest.write_text(json.dumps(_manifest(
            ['tests/test_a.py::test_one', 'tests/test_a.py::test_two'],
            [_xfail('tests/test_a.py::test_two', reason='[DEF-002] x')])), encoding='utf-8')
        code = defects.main(['--ledger', str(ledger), '--manifest', str(manifest),
                             '--check'])
        assert code == 1
        assert '请删除标记' in capsys.readouterr().out

    def test_write_markdown(self, tmp_path, capsys):
        ledger = _write_ledger(tmp_path)
        out = tmp_path / 'known_defects.md'
        code = defects.main(['--ledger', str(ledger), '--format', 'terminal',
                             '--write', str(out)])
        assert code == 0
        assert 'DEF-001' in out.read_text(encoding='utf-8')
        assert capsys.readouterr().out.strip() == ''

    def test_write_with_check_prints_terminal_summary(self, tmp_path, capsys):
        ledger = _write_ledger(tmp_path)
        manifest = tmp_path / 'manifest.json'
        manifest.write_text(json.dumps(_manifest(
            ['tests/test_a.py::test_one', 'tests/test_a.py::test_two'],
            [_xfail('tests/test_a.py::test_one')])), encoding='utf-8')
        code = defects.main(['--ledger', str(ledger), '--manifest', str(manifest),
                             '--check', '--write', str(tmp_path / 'known_defects.md')])
        assert code == 0
        assert '台账与用例一致' in capsys.readouterr().out

    def test_json_format(self, tmp_path, capsys):
        ledger = _write_ledger(tmp_path)
        code = defects.main(['--ledger', str(ledger), '--format', 'json'])
        assert code == 0
        assert json.loads(capsys.readouterr().out)[0]['id'] == 'DEF-001'

    def test_project_selects_manifest_path(self, tmp_path, monkeypatch, capsys):
        """--project 让 CI 清单按项目隔离，不被内核单测的运行覆盖。"""
        monkeypatch.chdir(tmp_path)
        reports = tmp_path / 'reports'
        reports.mkdir()
        manifest = _manifest(
            ['tests/test_a.py::test_one', 'tests/test_a.py::test_two'],
            [_xfail('tests/test_a.py::test_one')])
        (reports / 'shopping_xfail_manifest.json').write_text(
            json.dumps(manifest), encoding='utf-8')
        code = defects.main(['--ledger', str(_write_ledger(tmp_path)),
                             '--project', 'shopping', '--check'])
        assert code == 0
        assert '台账与用例一致' in capsys.readouterr().out

    def test_project_derives_ledger_without_business_hardcode(self, tmp_path, monkeypatch, capsys):
        """内核不认识 shopping：--project 按约定路径推导台账。"""
        monkeypatch.setattr(defects, 'ROOT', tmp_path)
        ledger = tmp_path / 'projects' / 'demo' / 'data' / 'known_defects.yaml'
        ledger.parent.mkdir(parents=True)
        ledger.write_text(_write_ledger(tmp_path).read_text(encoding='utf-8'), encoding='utf-8')
        code = defects.main(['--project', 'demo', '--format', 'json'])
        assert code == 0
        assert json.loads(capsys.readouterr().out)[0]['id'] == 'DEF-001'
        assert 'shopping' not in defects.ledger_for_project('demo').as_posix()

    def test_explicit_ledger_wins_over_project(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(defects, 'ROOT', tmp_path)
        explicit = _write_ledger(tmp_path)
        code = defects.main(['--ledger', str(explicit), '--project', 'demo',
                             '--format', 'json'])
        assert code == 0
        assert json.loads(capsys.readouterr().out)[0]['id'] == 'DEF-001'

    def test_no_ledger_and_no_project_returns_2(self, capsys):
        code = defects.main([])
        assert code == 2
        assert '请传 --ledger' in capsys.readouterr().out

    def test_missing_ledger_returns_2(self, tmp_path, capsys):
        code = defects.main(['--ledger', str(tmp_path / 'none.yaml'), '--check'])
        assert code == 2
        assert '台账读取失败' in capsys.readouterr().out

    def test_missing_manifest_returns_2(self, tmp_path, capsys):
        code = defects.main(['--ledger', str(_write_ledger(tmp_path)), '--check',
                             '--manifest', str(tmp_path / 'none.json')])
        assert code == 2
        assert '收集清单读取失败' in capsys.readouterr().out


class TestConfigure:
    def test_configure_sets_and_clears_state(self, tmp_path):
        original_ledger, original_project = state.defects_ledger, state.defects_project
        try:
            defects.configure(tmp_path / 'ledger.yaml', project='shopping')
            assert state.defects_ledger == tmp_path / 'ledger.yaml'
            assert state.defects_project == 'shopping'
            defects.configure(None)
            assert state.defects_ledger is None
            assert state.defects_project is None
        finally:
            state.defects_ledger, state.defects_project = original_ledger, original_project

    def test_load_ledger_accepts_yaml_multiline_symptom(self, tmp_path):
        text = LEDGER_TEXT.replace('symptom: 现象', 'symptom: >-\n      多行\n      现象', 1)
        rows = defects.load_ledger(_write_ledger(tmp_path, text))
        assert '多行' in rows[0]['symptom']


class TestManifestShards:
    """xdist 下 worker 分片清单由主进程汇总（否则报告里台账摘要会静默缺失）。"""

    def test_merge_shards_into_main_manifest(self, tmp_path, monkeypatch):
        from framework import hooks
        monkeypatch.setattr(hooks, 'ROOT', tmp_path)
        reports = tmp_path / 'reports'
        reports.mkdir()
        manifest = _manifest(['a', 'b'], [_xfail('a')])
        (reports / '.xfail_manifest_gw0.json').write_text(
            json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
        # 多分片：取到第一份后不能提前 break，否则剩余分片会残留
        for worker in ('gw1', 'gw2', 'gw3'):
            (reports / ('.xfail_manifest_%s.json' % worker)).write_text(
                json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
        hooks._merge_manifest_shards()
        merged = json.loads((reports / 'xfail_manifest.json').read_text(encoding='utf-8'))
        assert merged == manifest
        assert list(reports.glob('.xfail_manifest_*')) == []

    def test_bad_shard_is_ignored_and_cleaned(self, tmp_path, monkeypatch):
        from framework import hooks
        monkeypatch.setattr(hooks, 'ROOT', tmp_path)
        reports = tmp_path / 'reports'
        reports.mkdir()
        (reports / '.xfail_manifest_gw0.json').write_text('{broken', encoding='utf-8')
        hooks._merge_manifest_shards()
        assert not (reports / 'xfail_manifest.json').exists()
        assert list(reports.glob('.xfail_manifest_*')) == []

    def test_project_shards_do_not_leak(self, tmp_path, monkeypatch):
        from framework import hooks
        monkeypatch.setattr(hooks, 'ROOT', tmp_path)
        monkeypatch.setattr(state, 'defects_project', 'shopping')
        reports = tmp_path / 'reports'
        reports.mkdir()
        manifest = _manifest(['a'], [_xfail('a')])
        (reports / '.shopping_xfail_manifest_gw0.json').write_text(
            json.dumps(manifest), encoding='utf-8')
        hooks._merge_manifest_shards()
        assert (reports / 'shopping_xfail_manifest.json').exists()
        assert not (reports / 'xfail_manifest.json').exists()

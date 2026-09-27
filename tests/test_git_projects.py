"""通用远程依赖合同：测试仓库没有QuMod预设，全部使用真实本地Git。"""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from click.testing import CliRunner
from mcpywrap.cli import cli
from mcpywrap.dependencies import DependencyError, read_project, write_project
from mcpywrap.git_cache import fetch_snapshot, cache_root
from mcpywrap.git_projects import declarations, resolve_projects, LOCK_FILE
from mcpywrap.project_dependencies import GitDependencyService
from mcpywrap.builders.project_builder import AddonProjectBuilder
from test_local_dependencies import addon


class GitProjects(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mcpy-git-test-')
        self.root = Path(self.temp.name)
        def cleanup():
            from mcpywrap.source_files import long_path
            self.temp.name = str(long_path(self.root))
            self.temp.cleanup()
        self.addCleanup(cleanup)
        self.env = patch.dict(os.environ, {'MCPY_CACHE_DIR': str(self.root / 'shared-cache')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.main = addon(self.root, 'consumer', configured=True)
        self.service = GitDependencyService(self.main)

    def commit(self, repo):
        def git(*args):
            return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.STDOUT).decode().strip()
        if not (repo / '.git').exists():
            git('init', '-q')
            git('config', 'user.name', 'Tests')
            git('config', 'user.email', 'tests@example.invalid')
        git('config', 'core.longpaths', 'true')
        git('add', '.')
        git('commit', '-qm', 'fixture')
        return git('rev-parse', 'HEAD')

    def repository(self, name, kind='addon'):
        if kind == 'addon':
            repo = addon(self.root, name, configured=True)
        else:
            repo = self.root / name
            (repo / 'src').mkdir(parents=True)
            (repo / 'src/__init__.py').write_text('VALUE = 42\n')
            write_project(repo, {'project': {'name': name}, 'tool': {'mcpywrap': {
                'export': {'kind': 'code', 'path': 'src', 'target': 'Mod/' + name}}}})
        (repo / 'LICENSE').write_text('fixture license')
        return repo, self.commit(repo)

    def build(self, root=None):
        root = root or self.main
        success, error = AddonProjectBuilder(root, root / 'build').build()
        self.assertTrue(success, error)

    def test_raw_git_addon_and_metadata_code_library(self):
        repo, rev = self.repository('library', 'code')
        result = self.service.add(repo.as_uri())
        self.assertEqual(result['rev'], rev)
        self.assertEqual(result['kind'], 'code')
        self.assertEqual(result['target'], 'Mod/library')
        self.assertEqual(declarations(self.main)[0]['rev'], rev)
        self.build()
        self.assertIn('VALUE = 42', (self.main / 'build/behavior_pack/Mod/library/__init__.py').read_text())
        self.assertFalse((self.main / 'behavior_pack/Mod').exists())
        self.assertEqual(resolve_projects(self.main)[0][2]['kind'], 'code')
        dep, sha = self.repository('addon-dep')
        (dep / 'behavior_pack/unique.py').write_text('UNIQUE = True')
        sha = self.commit(dep)
        self.service.add(dep.as_uri(), ref=sha)
        self.build()
        self.assertTrue((self.main / 'build/behavior_pack/unique.py').exists())
        self.assertEqual(len(list((self.main / 'build/behavior_pack/mcpy_licenses').glob('*/LICENSE'))), 2)

    def test_recursive_git_and_internal_local_dependency(self):
        leaf, leaf_rev = self.repository('leaf', 'code')
        parent, unused = self.repository('parent')
        config = read_project(parent)
        config['tool']['mcpywrap']['git_dependencies'] = [{'name': 'leaf', 'git': leaf.as_uri(), 'rev': leaf_rev}]
        local = addon(parent, 'internal', configured=True)
        (local / 'behavior_pack/internal.py').write_text('INTERNAL = True')
        config['tool']['mcpywrap']['local_dependencies'] = ['internal']
        write_project(parent, config)
        parent_rev = self.commit(parent)
        self.service.add(parent.as_uri(), ref=parent_rev)
        self.build()
        self.assertTrue((self.main / 'build/behavior_pack/internal.py').exists())
        self.assertTrue((self.main / 'build/behavior_pack/Mod/leaf/__init__.py').exists())
        lock = json.loads((self.main / LOCK_FILE).read_text())
        self.assertEqual(len(lock['nodes']), 3)
        self.assertIn('internal', [node['source']['subdir'] for node in lock['nodes']])
        self.assertNotIn(str(self.root), (self.main / LOCK_FILE).read_text().replace(parent.as_uri(), '').replace(leaf.as_uri(), ''))

    def test_shared_source_project_isolation_and_offline_restore(self):
        repo, rev = self.repository('shared', 'code')
        self.service.add(repo.as_uri(), ref=rev)
        snapshot, _ = fetch_snapshot(repo.as_uri(), rev)
        self.assertTrue(snapshot.is_relative_to(cache_root()))
        clone = self.root / 'clone'
        shutil.copytree(self.main, clone, ignore=shutil.ignore_patterns('.mcpy'))
        with patch('mcpywrap.git_cache._git', side_effect=AssertionError('should not download')):
            result = CliRunner().invoke(cli, ['--project', str(clone), '--non-interactive', 'sync', '--json'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual((self.main / LOCK_FILE).read_bytes(), (clone / LOCK_FILE).read_bytes())
        self.build(clone)
        (clone / 'build/behavior_pack/Mod/shared/__init__.py').write_text('modified output')
        self.assertEqual((snapshot / 'src/__init__.py').read_text(), 'VALUE = 42\n')
        self.assertNotEqual(resolve_projects(self.main)[0][1], resolve_projects(clone)[0][1])

    def test_concurrent_cache_fetches_publish_one_complete_snapshot(self):
        repo, rev = self.repository('concurrent', 'code')
        script = 'from mcpywrap.git_cache import fetch_snapshot; import sys; print(fetch_snapshot(sys.argv[1],sys.argv[2])[0])'
        def run():
            return subprocess.run([sys.executable, '-c', script, repo.as_uri(), rev], capture_output=True, text=True, timeout=45)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: run(), range(2)))
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(results[0].stdout, results[1].stdout)
        self.assertEqual(len(list(cache_root().glob('git/*/*/source.json'))), 1)
        self.assertFalse(list(cache_root().glob('git/*/fetch-*')))

    def test_cycle_escape_and_layout_failure_do_not_change_project(self):
        repo, rev = self.repository('cycle')
        config = read_project(repo)
        config['tool']['mcpywrap']['local_dependencies'] = ['.']
        write_project(repo, config)
        rev = self.commit(repo)
        before = (self.main / 'pyproject.toml').read_bytes()
        with self.assertRaisesRegex(DependencyError, '循环'):
            self.service.add(repo.as_uri(), ref=rev)
        self.assertEqual(before, (self.main / 'pyproject.toml').read_bytes())
        config['tool']['mcpywrap']['local_dependencies'] = ['../../outside']
        write_project(repo, config)
        rev = self.commit(repo)
        with self.assertRaisesRegex(DependencyError, '不得离开'):
            self.service.add(repo.as_uri(), ref=rev)
        plain = self.root / 'plain'
        plain.mkdir()
        (plain / 'README.md').write_text('No export contract')
        rev = self.commit(plain)
        with self.assertRaisesRegex(DependencyError, '无法识别'):
            self.service.add(plain.as_uri(), ref=rev)

    def test_pinned_update_remove_and_tamper(self):
        repo, rev = self.repository('versions', 'code')
        first = self.service.add(repo.as_uri(), ref=rev)
        self.build()
        (repo / 'src/new.py').write_text('NEW = True')
        next_rev = self.commit(repo)
        self.assertEqual(self.service.add(repo.as_uri())['rev'], rev)
        self.service.add(repo.as_uri(), ref=next_rev)
        self.build()
        self.assertTrue((self.main / 'build/behavior_pack/Mod/versions/new.py').exists())
        self.service.add(repo.as_uri(), ref=rev)
        self.build()
        self.assertFalse((self.main / 'build/behavior_pack/Mod/versions/new.py').exists())
        resolved = resolve_projects(self.main)[0][1]
        (resolved / 'behavior_pack/Mod/versions/__init__.py').write_text('tamper')
        with self.assertRaisesRegex(DependencyError, '摘要'):
            resolve_projects(self.main)
        self.assertFalse(AddonProjectBuilder(self.main, self.main / 'build').build()[0])
        self.service.remove(first['dependency'])
        self.build()
        self.assertFalse((self.main / 'build/behavior_pack/Mod/versions').exists())

    def test_install_collision_is_not_last_writer_wins(self):
        repo, rev = self.repository('colliding', 'code')
        folder = self.main / 'behavior_pack/Mod/colliding'
        folder.mkdir(parents=True)
        (folder / '__init__.py').write_text('USER = True')
        with self.assertRaisesRegex(DependencyError, '冲突'):
            self.service.add(repo.as_uri(), ref=rev)
        self.assertEqual((folder / '__init__.py').read_text(), 'USER = True')

    def test_explicit_layout_is_preserved_on_repeat_add(self):
        repo, rev = self.repository('plain-code', 'code')
        (repo / 'pyproject.toml').unlink()
        rev = self.commit(repo)
        self.service.add(repo.as_uri(), ref=rev, kind='code', subdir='src', target='Custom/Library')
        before = (self.main / 'pyproject.toml').read_bytes()
        self.service.add(repo.as_uri())
        self.assertEqual(before, (self.main / 'pyproject.toml').read_bytes())

    def test_dev_checks_git_snapshot_before_writing(self):
        from mcpywrap.builders.watcher import ProjectWatcher
        repo, rev = self.repository('watched-addon')
        self.service.add(repo.as_uri(), ref=rev)
        self.build()
        watcher = ProjectWatcher(self.main, self.main / 'build')
        watcher.setup_from_config('consumer')
        registered = resolve_projects(self.main)[0][1]
        (registered / 'behavior_pack/tampered.py').write_text('TAMPERED = True')
        with self.assertRaisesRegex(ValueError, '摘要'):
            watcher.rebuild('behavior', 'tampered.py')
        self.assertFalse((self.main / 'build/behavior_pack/tampered.py').exists())

    def test_generic_cli_git_entry(self):
        repo, rev = self.repository('cli-lib', 'code')
        result = CliRunner().invoke(cli, ['--project', str(self.main), '--non-interactive', 'add', '--git', repo.as_uri(), '--ref', rev, '--json'])
        self.assertEqual(result.exit_code, 0, result.output)
        result = CliRunner().invoke(cli, ['--project', str(self.main), '--non-interactive', 'remove', '--git', 'cli-lib', '--json'])
        self.assertEqual(result.exit_code, 0, result.output)

    def test_deep_source_paths_work_without_system_setting(self):
        from mcpywrap.source_files import long_path
        repo, rev = self.repository('deep', 'code')
        relative = '/'.join(['long_directory_' + str(i) + '_' * 45 for i in range(4)]) + '/module.py'
        path = long_path(repo / 'src' / relative)
        path.parent.mkdir(parents=True)
        path.write_text('DEEP = True\n')
        rev = self.commit(repo)
        source, _ = fetch_snapshot(repo.as_uri(), rev)
        self.assertEqual((source / 'src' / relative).read_text(), 'DEEP = True\n')
        self.service.add(repo.as_uri(), ref=rev)
        registered = resolve_projects(self.main)[0][1]
        self.assertEqual((registered / 'behavior_pack/Mod/deep' / relative).read_text(), 'DEEP = True\n')

    def test_another_framework_needs_only_preset_data(self):
        from mcpywrap.framework_presets import FRAMEWORK_PRESETS
        from mcpywrap.frameworks import add_framework
        repo, rev = self.repository('tiny-framework', 'code')
        preset = {'title': 'Tiny framework', 'version': '0.1', 'rev': rev,
                  'sources': {'local': repo.as_uri()}, 'default_source': 'local',
                  'kind': 'code', 'subdir': 'src', 'folder': 'Rules',
                  'files': {'__init__.py': '', 'modMain.py': 'from .Rules import VALUE\n'}}
        with patch.dict(FRAMEWORK_PRESETS, {'tiny': preset}):
            result = add_framework(self.main, 'tiny', 'TinyMod')
        self.assertEqual(result['target'], 'TinyMod/Rules')
        self.assertEqual((self.main / 'behavior_pack/TinyMod/modMain.py').read_text(), 'from .Rules import VALUE\n')
        self.build()
        self.assertIn('VALUE = 42', (self.main / 'build/behavior_pack/TinyMod/Rules/__init__.py').read_text())

    @unittest.skipUnless(os.name == 'nt', 'Qt is Windows-only')
    def test_gui_raw_git_project_uses_same_service(self):
        from PyQt5.QtWidgets import QApplication
        from mcpywrap.ui import project_ui as ui
        import time
        repo, rev = self.repository('gui-code', 'code')
        app = QApplication.instance() or QApplication([])
        window = ui.GameInstanceManager(str(self.main))
        try:
            window.dependency_kind.setCurrentIndex(2)
            window.git_fields['git'].setText(repo.as_uri())
            window.git_fields['ref'].setText(rev)
            window.add_dependency()
            self.assertTrue(window.dependency_busy)
            deadline = time.monotonic() + 25
            while window.dependency_busy and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            self.assertFalse(window.dependency_busy, window.log_output.toPlainText())
            self.assertEqual(window.dependency_list.count(), 1, window.log_output.toPlainText())
            self.assertIn('Git依赖', window.dependency_list.item(0).text())
            self.assertIn('已同步', window.dependency_list.item(0).text())
        finally:
            window.close()
            app.processEvents()

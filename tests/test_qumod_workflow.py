"""QuMod 向导共享服务、CLI和离屏GUI；真实Git fixture不依赖网络。"""
import json
import copy
import inspect
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from click.testing import CliRunner
from mcpywrap.cli import cli
from mcpywrap.dependencies import DependencyDeclaration, DependencyError, DependencyService, read_project, write_project
from mcpywrap.git_projects import LOCK_FILE, declarations, resolve_projects
from mcpywrap.code_libraries import digest
from mcpywrap.frameworks import add_framework, framework_preview
from mcpywrap.framework_presets import FRAMEWORK_PRESETS

def add_qumod(root, script_dir=None):
    return add_framework(root, "qumod", script_dir)

def qumod_preview(root, script_dir=None):
    return framework_preview(root, "qumod", script_dir)

def resolve_libraries(root):
    return [{"source": path} for entry, path, node in resolve_projects(root)]
from test_local_dependencies import addon


class QuModFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mcpy-qumod-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'upstream'
        (self.repo / 'Scripts/QuModLibs').mkdir(parents=True)
        for name in ('__init__.py', 'QuMod.py', 'Server.py', 'Client.py'):
            (self.repo / 'Scripts/QuModLibs' / name).write_text('# fixture\n')
        (self.repo / 'LICENSE').write_text('BSD-3-Clause fixture\n')
        self.git('init', '-q')
        self.git('config', 'user.name', 'Tests')
        self.git('config', 'user.email', 'tests@example.invalid')
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        self.rev = self.git('rev-parse', 'HEAD')
        self.main = addon(self.root, 'project', configured=True)
        self.service = DependencyService(self.main)
        self.addCleanup(patch.stopall)
        preset = copy.deepcopy(FRAMEWORK_PRESETS['qumod'])
        preset['rev'] = self.rev
        preset['sources'] = {'github': self.repo.as_uri(), 'gitee': self.repo.as_uri() + '/'}
        patch.dict(FRAMEWORK_PRESETS, {'qumod': preset}).start()
        patch.dict(os.environ, {'MCPY_CACHE_DIR': str(self.root / 'cache')}).start()
        options = {'mix_stderr': False} if 'mix_stderr' in inspect.signature(CliRunner).parameters else {}
        self.runner = CliRunner(**options)

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.STDOUT).decode().strip()

    def call(self, *args):
        return self.runner.invoke(cli, ['--project', str(self.main), '--non-interactive', *args, '--json'])


class QuModWorkflow(QuModFixture):
    def test_resource_only_project_reports_missing_behavior_pack(self):
        shutil.rmtree(self.main / 'behavior_pack')
        with self.assertRaisesRegex(DependencyError, '行为包'):
            qumod_preview(self.main, 'Demo')

    def test_existing_legacy_declaration_is_restored_without_duplicate(self):
        folder = self.main / 'behavior_pack/Demo'
        folder.mkdir()
        (folder / 'modMain.py').write_text('EXISTING = True')
        config = read_project(self.main)
        config['tool']['mcpywrap']['code_libraries'] = [{'name': 'old-lib', 'git': self.repo.as_uri(),
            'rev': self.rev, 'subdir': 'Scripts/QuModLibs', 'target': 'Demo/QuModLibs'}]
        write_project(self.main, config)
        result = add_qumod(self.main, 'Demo')
        self.assertFalse(result['changed'])
        self.assertEqual(declarations(self.main), [])
        self.assertEqual((folder / 'modMain.py').read_text(), 'EXISTING = True')

    def test_one_command_idempotent_and_clean_clone_sync(self):
        result = self.call('add', '--qumod', '--script-dir', 'Demo')
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.stdout)
        self.assertTrue(data['new_script'])
        entry = declarations(self.main)[0]
        self.assertEqual(entry['target'], 'Demo/QuModLibs')
        self.assertFalse((self.main / 'behavior_pack/Demo/QuModLibs').exists())
        self.assertIn('EasyMod, QMain', (self.main / 'behavior_pack/Demo/modMain.py').read_text('utf-8'))
        self.assertIn('.mcpy/', (self.main / '.gitignore').read_text())
        before = (self.main / 'pyproject.toml').read_bytes(), (self.main / LOCK_FILE).read_bytes()
        result = self.call('add', '--qumod')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(json.loads(result.stdout)['changed'])
        self.assertEqual(before, ((self.main / 'pyproject.toml').read_bytes(), (self.main / LOCK_FILE).read_bytes()))
        clone = self.root / 'clone'
        shutil.copytree(self.main, clone, ignore=shutil.ignore_patterns('.mcpy'))
        result = self.runner.invoke(cli, ['--project', str(clone), '--non-interactive', 'sync', '--json'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(digest(resolve_libraries(self.main)[0]['source']), digest(resolve_libraries(clone)[0]['source']))

    def test_existing_mod_not_overwritten_and_ambiguous_target_rejected(self):
        for name in ('A', 'B'):
            folder = self.main / ('behavior_pack/' + name)
            folder.mkdir()
            (folder / 'modMain.py').write_text('HANDWRITTEN = True\n')
        with self.assertRaisesRegex(DependencyError, '多个 Mod'):
            qumod_preview(self.main)
        result = add_qumod(self.main, 'A')
        self.assertFalse(result['new_script'])
        self.assertEqual((self.main / 'behavior_pack/A/modMain.py').read_text(), 'HANDWRITTEN = True\n')
        self.assertTrue(result['warnings'])
        second = add_qumod(self.main, 'B')
        self.assertEqual(len(declarations(self.main)), 2)
        self.assertNotEqual(result['dependency'], second['dependency'])

    def test_failure_keeps_configuration_entrypoint_and_lock(self):
        before = (self.main / 'pyproject.toml').read_bytes()
        with patch('mcpywrap.project_dependencies.git_projects.prepare_graph', side_effect=DependencyError('network failed')):
            with self.assertRaisesRegex(DependencyError, 'network failed'):
                add_qumod(self.main, 'Demo')
        self.assertEqual(before, (self.main / 'pyproject.toml').read_bytes())
        self.assertFalse((self.main / LOCK_FILE).exists())
        self.assertFalse((self.main / 'behavior_pack/Demo').exists())
        with patch('mcpywrap.project_dependencies.write_project', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                add_qumod(self.main, 'Demo')
        self.assertEqual(before, (self.main / 'pyproject.toml').read_bytes())
        self.assertFalse((self.main / LOCK_FILE).exists())
        self.assertFalse((self.main / 'behavior_pack/Demo').exists())

    def test_concurrent_config_edit_not_clobbered(self):
        from mcpywrap.git_projects import prepare_graph as prepare_sync
        def download(root, config):
            locked = prepare_sync(root, config)
            current = read_project(root)
            current['project']['description'] = 'user edit'
            write_project(root, current)
            return locked
        with patch('mcpywrap.project_dependencies.git_projects.prepare_graph', side_effect=download):
            with self.assertRaisesRegex(DependencyError, '已改变'):
                add_qumod(self.main, 'Demo')
        self.assertEqual(read_project(self.main)['project']['description'], 'user edit')
        self.assertFalse((self.main / 'behavior_pack/Demo').exists())

    def test_manual_copy_conflict_precedes_network(self):
        (self.main / 'behavior_pack/Demo/QuModLibs').mkdir(parents=True)
        with patch('mcpywrap.project_dependencies.git_projects.prepare_graph') as network:
            with self.assertRaisesRegex(DependencyError, '手工'):
                add_qumod(self.main, 'Demo')
            network.assert_not_called()

    def test_library_status_remove_and_existing_commit_preserved(self):
        add_qumod(self.main, 'Demo')
        entry = self.service.list()[0]
        self.assertEqual(entry.kind, 'git')
        self.assertEqual(self.service.inspect(entry).state, 'git_project')
        # 默认添加不能把用户钉住的旧提交自动升级。
        with patch.dict(FRAMEWORK_PRESETS['qumod'], {'rev': 'f' * 40}):
            self.assertEqual(qumod_preview(self.main, 'Demo')['rev'], self.rev)
        result = self.call('remove', '--git', entry.value)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.service.list(), [])
        self.assertEqual(json.loads((self.main / LOCK_FILE).read_text())['nodes'], [])
        self.assertTrue((self.main / 'behavior_pack/Demo/modMain.py').exists())
        self.assertTrue((self.main / '.mcpy/git-projects').exists())

    def test_mod_command_and_invalid_flags(self):
        result = self.call('mod', '--framework', 'qumod', '--name', 'Demo', '--script-dir', 'Demo')
        self.assertEqual(result.exit_code, 0, result.output)
        result = self.call('mod', '--framework', 'qumod', '--name', 'Demo', '--script-dir', 'Demo')
        self.assertNotEqual(result.exit_code, 0)
        for args in [('add', 'click', '--qumod'), ('add', '--script-dir', 'Demo'),
                     ('remove', '--library', 'qumod-demo', '--uninstall'), ('add', '--qumod', '--script-dir', '../bad')]:
            self.assertNotEqual(self.call(*args).exit_code, 0)


@unittest.skipUnless(os.name == 'nt', 'Qt is Windows-only')
class QuModGUI(QuModFixture):
    def test_shortcut_cancel_does_not_register_dependency(self):
        from PyQt5.QtWidgets import QApplication
        from mcpywrap.ui import project_ui as ui
        app = QApplication.instance() or QApplication([])
        for name in ('A', 'B'):
            folder = self.main / 'behavior_pack' / name
            folder.mkdir()
            (folder / 'modMain.py').write_text('')
        window = ui.GameInstanceManager(str(self.main))
        before = (self.main / 'pyproject.toml').read_bytes()
        try:
            window.dependency_kind.setCurrentIndex(2)
            with patch.object(ui.QInputDialog, 'getItem', return_value=('', False)):
                window.git_shortcuts['qumod'].click()
            self.assertFalse(window.dependency_busy)
            self.assertEqual((self.main / 'pyproject.toml').read_bytes(), before)
            self.assertEqual(self.service.list(), [])
        finally:
            window.close()
            app.processEvents()

    def test_background_add_list_sync_and_remove(self):
        from PyQt5.QtWidgets import QApplication, QMessageBox
        from mcpywrap.ui import project_ui as ui
        app = QApplication.instance() or QApplication([])
        with patch.object(ui, 'find_all_mcpywrap_packages', return_value=[]):
            window = ui.GameInstanceManager(str(self.main))
        def wait():
            deadline = time.monotonic() + 25
            while window.dependency_busy and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            self.assertFalse(window.dependency_busy, window.log_output.toPlainText())
        try:
            window.dependency_kind.setCurrentIndex(2)
            window.add_preset_dependency('qumod', script_dir='Demo')
            self.assertEqual(window.git_fields['target'].text(), 'Demo/QuModLibs')
            self.assertTrue(window.dependency_busy)
            self.assertFalse(window.sync_dependencies_btn.isEnabled())
            wait()
            self.assertEqual(window.dependency_list.count(), 1, window.log_output.toPlainText())
            self.assertIn('已同步', window.dependency_list.item(0).text())
            window.sync_dependencies()
            wait()
            window.dependency_list.setCurrentRow(0)
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                window.remove_selected_dependency()
            self.assertEqual(window.dependency_list.count(), 0)
        finally:
            window.close()
            app.processEvents()

    def test_worker_failure_reports_error_and_keeps_files(self):
        from mcpywrap.ui.project_ui import DependencyTaskThread
        before = (self.main / 'pyproject.toml').read_bytes()
        worker = DependencyTaskThread(str(self.main), 'framework', 'Demo', preset='qumod')
        messages = []
        worker.result.connect(lambda ok, text: messages.append((ok, text)))
        with patch('mcpywrap.project_dependencies.git_projects.prepare_graph', side_effect=DependencyError('offline')):
            worker.run()
        self.assertFalse(messages[0][0])
        self.assertIn('offline', messages[0][1])
        self.assertEqual(before, (self.main / 'pyproject.toml').read_bytes())

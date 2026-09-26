"""使用真实临时 Addon 目录验证依赖、构建及交互，不启动游戏。"""
import importlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch, Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from click.testing import CliRunner
from watchdog.events import FileModifiedEvent, FileDeletedEvent, FileCreatedEvent
from mcpywrap.cli import cli
from mcpywrap.dependencies import (DependencyService, DependencyDeclaration, DependencyError,
                                  read_project, write_project, path_for_storage)
from mcpywrap.builders.dependency_manager import DependencyManager
from mcpywrap.builders.project_builder import AddonProjectBuilder, MapProjectBuilder
from mcpywrap.builders.watcher import ProjectWatcher
from mcpywrap.commands.run_cmd import _setup_dependencies


def addon(root, name, configured=False, local=(), packages=(), resource=True):
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    for folder, kind in [('behavior_pack', 'data')] + ([('resource_pack', 'resources')] if resource else []):
        pack = path / folder
        pack.mkdir(exist_ok=True)
        (pack / 'manifest.json').write_text(json.dumps({
            'format_version': 1,
            'header': {'name': name, 'description': 'local dependency test', 'uuid': str(uuid.uuid4()), 'version': [1, 0, 0]},
            'modules': [{'type': kind, 'uuid': str(uuid.uuid4()), 'version': [1, 0, 0]}],
        }), encoding='utf-8')
    (path / 'behavior_pack' / 'marker.py').write_text('VALUE = ' + repr(name) + '\n', encoding='utf-8')
    if configured:
        write_project(path, {'project': {'name': name, 'version': '0.1.0', 'dependencies': list(packages)},
                             'tool': {'mcpywrap': {'project_type': 'addon', 'target_dir': './build', 'local_dependencies': list(local)}}})
    return path


@contextmanager
def cwd(path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class FakeDist:
    def __init__(self, path=None, version='1.2.0'):
        self.path, self.version = path, version

    def read_text(self, name):
        return json.dumps({'url': self.path.as_uri(), 'dir_info': {'editable': True}}) if self.path else None


class ProjectFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mcpy-test-')
        self.root = Path(self.temp.name).resolve()
        self.main = addon(self.root, 'main', configured=True)
        self.dep = addon(self.root, '中文 shared')
        self.service = DependencyService(self.main)

    def tearDown(self):
        self.temp.cleanup()

    def add(self):
        return self.service.add_local('../中文 shared')


class Projects(ProjectFixture):
    def test_plain_addon_readonly_relative_absolute_duplicate(self):
        before = {p.relative_to(self.dep): p.read_bytes() for p in self.dep.rglob('*') if p.is_file()}
        initial_cwd = os.getcwd()
        self.assertTrue(self.add()[0])
        self.assertFalse(self.service.add_local(str(self.dep))[0])
        self.assertEqual(len(self.service.resolve().dependency_map), 1)
        self.assertEqual(os.getcwd(), initial_cwd)
        self.assertEqual(before, {p.relative_to(self.dep): p.read_bytes() for p in self.dep.rglob('*') if p.is_file()})

    def test_nested_relative_diamond_order_and_same_names(self):
        a = addon(self.root, 'a/common', configured=True, local=['../../中文 shared'])
        b = addon(self.root, 'b/common', configured=True, local=['../../中文 shared'])
        self.service.add_local('../a/common')
        self.service.add_local('../b/common')
        manager = self.service.resolve()
        packs = list(manager.dependency_map.values())
        self.assertEqual([Path(p.path) for p in packs], [self.dep, a, b])
        self.assertNotEqual(packs[1].pkg_name, packs[2].pkg_name)
        self.assertIs(manager.root_node.children[0].children[0], manager.root_node.children[1].children[0])

    def test_cycle_fails_without_writing(self):
        child = addon(self.root, 'cycle', configured=True, local=['../main'])
        before = (self.main / 'pyproject.toml').read_bytes()
        with self.assertRaisesRegex(DependencyError, '循环依赖'):
            self.service.add_local(str(child))
        self.assertEqual(before, (self.main / 'pyproject.toml').read_bytes())

    def test_invalid_shapes_and_missing_paths(self):
        empty = self.root / 'empty'
        empty.mkdir()
        multi = addon(self.root, 'multi')
        shutil.copytree(multi / 'behavior_pack', multi / 'behavior_pack_2')
        world = self.root / 'world'
        world.mkdir()
        (world / 'level.dat').touch()
        for invalid in [empty, multi, world, self.dep / 'behavior_pack', self.root / 'missing']:
            with self.subTest(path=invalid), self.assertRaises(DependencyError):
                self.service.add_local(str(invalid))
        self.assertEqual(self.service.list(), [])

    def test_invalid_manifest_rejected_without_saving(self):
        manifest = self.dep / 'behavior_pack/manifest.json'
        data = json.loads(manifest.read_text())
        for replacement in ('not-json', '{"header":{"uuid":"invalid"}}', json.dumps(dict(data, modules=[]))):
            manifest.write_text(replacement)
            with self.assertRaisesRegex(DependencyError, '无效 manifest'):
                self.add()
            self.assertEqual(self.service.list(), [])

    def test_resource_only_dependency(self):
        shutil.rmtree(self.dep / 'behavior_pack')
        self.add()
        self.assertTrue(AddonProjectBuilder(self.main, self.main / 'build').build()[0])
        self.assertIsNone(next(iter(self.service.resolve().dependency_map.values())).behavior_pack_dir)

    def test_missing_package_warns_then_blocks(self):
        child = addon(self.root, 'needs-package', configured=True, packages=['mcpy-no-such-dependency-999>=1'])
        changed, warnings = self.service.add_local(str(child))
        self.assertTrue(changed)
        self.assertIn('mcpy add', warnings[0])
        with self.assertRaises(DependencyError):
            self.service.resolve()

    def test_package_specifier_marker_and_mixed_sources(self):
        config = read_project(self.main)
        config['project']['dependencies'] = ['Shared_Pack>=1', 'not-installed; python_version < "2"']
        write_project(self.main, config)
        with patch('mcpywrap.builders.dependency_manager.metadata.distribution', return_value=FakeDist(self.dep)):
            self.add()
            self.assertEqual(len(self.service.resolve().dependency_map), 1)
        with patch('mcpywrap.builders.dependency_manager.metadata.distribution', return_value=FakeDist(self.dep, '0.1')):
            with self.assertRaisesRegex(DependencyError, '版本约束'):
                self.service.resolve()

    def test_ordinary_python_package_not_loaded_as_addon(self):
        config = read_project(self.main)
        config['project']['dependencies'] = ['click>=8']
        write_project(self.main, config)
        self.assertEqual(len(self.service.resolve().dependency_map), 0)

    def test_remove_missing_source_and_gui_path_default(self):
        self.add()
        shutil.rmtree(self.dep)
        self.service.remove(DependencyDeclaration('local', '../中文 shared'))
        self.assertEqual(self.service.list(), [])
        self.assertEqual(path_for_storage(self.main, self.dep), '../中文 shared')
        self.assertEqual(path_for_storage(self.main, self.dep, True), self.dep.as_posix())
        with patch('mcpywrap.dependencies.os.path.relpath', side_effect=ValueError):
            self.assertEqual(path_for_storage(self.main, self.dep), self.dep.as_posix())

    def test_symlink_identity(self):
        link = self.root / 'alias'
        try:
            from mcpywrap.mcstudio.symlinks import _create_directory_link
            _create_directory_link(str(self.dep), str(link))
        except OSError:
            self.skipTest('系统未授权目录符号链接')
        self.add()
        self.assertFalse(self.service.add_local(str(link))[0])
        if os.name == 'nt':
            self.assertFalse(self.service.add_local(str(self.dep).upper())[0])

    def test_root_manifest_does_not_mix_formats(self):
        (self.dep / 'behavior_pack/manifest.json').rename(self.dep / 'behavior_pack/pack_manifest.json')
        self.add()
        out = self.main / 'build'
        self.assertTrue(AddonProjectBuilder(self.main, out).build()[0])
        self.assertFalse((out / 'behavior_pack/pack_manifest.json').exists())

    def test_invalid_schema_rejected_before_install(self):
        (self.main / 'pyproject.toml').write_text('project = "invalid"', encoding='utf-8')
        with patch('mcpywrap.dependencies.subprocess.run') as pip:
            with self.assertRaises(DependencyError):
                self.service.add_package('click')
            pip.assert_not_called()

    def test_deleted_editable_source_blocks_resolution(self):
        config = read_project(self.main)
        config['project']['dependencies'] = ['missing-source>=1']
        write_project(self.main, config)
        with patch('mcpywrap.builders.dependency_manager.metadata.distribution', return_value=FakeDist(self.root / 'removed')):
            with self.assertRaisesRegex(DependencyError, '安装来源目录不存在'):
                self.service.resolve()

    def test_resource_only_main_can_build_behavior_dependency(self):
        shutil.rmtree(self.main / 'behavior_pack')
        self.add()
        output = self.main / 'build'
        self.assertTrue(AddonProjectBuilder(self.main, output).build()[0])
        self.assertEqual((output / 'behavior_pack/manifest.json').read_bytes(), (self.dep / 'behavior_pack/manifest.json').read_bytes())
        self.assertEqual((output / 'resource_pack/manifest.json').read_bytes(), (self.main / 'resource_pack/manifest.json').read_bytes())

    def test_run_revalidates_before_linking(self):
        run = importlib.import_module('mcpywrap.commands.run_cmd')
        self.add()
        packs = _setup_dependencies('main', str(self.main))
        shutil.rmtree(self.dep)
        with patch.object(run, 'setup_global_addons_symlinks') as link, patch.object(run, 'open_game') as game:
            self.assertEqual(run._run_game_with_instance(str(self.main / '.runtime/test.cppconfig'), 'test', packs, False), (False, None))
            link.assert_not_called()
            game.assert_not_called()

    def test_global_links_preserve_unrelated_and_reuse(self):
        from mcpywrap.mcstudio.symlinks import create_symlinks, _create_directory_link
        self.add()
        packs = _setup_dependencies('main', str(self.main))
        global_dir = self.root / 'engine'
        unrelated = global_dir / 'behavior_packs/unrelated'
        unrelated.parent.mkdir(parents=True)
        _create_directory_link(str(self.dep), str(unrelated))
        first = create_symlinks(str(global_dir), packs)
        self.assertTrue(first[0])
        self.assertTrue(unrelated.exists())
        self.assertEqual(first, create_symlinks(str(global_dir), packs))
        collision = global_dir / 'behavior_packs' / first[1][0]
        collision.unlink() if collision.is_symlink() else os.rmdir(collision)
        collision.mkdir()
        self.assertFalse(create_symlinks(str(global_dir), packs)[0])
        self.assertTrue(collision.is_dir())

    def test_game_uses_argument_list_and_own_process(self):
        game = importlib.import_module('mcpywrap.mcstudio.game')
        from mcpywrap.mcstudio.discovery import Engine
        config = self.root / 'space config.cppconfig'
        config.write_text('{"version":"3.10"}')
        proc = Mock()
        engine = Engine('D:/test engine/Minecraft.Windows.exe', '3.10', 'D:/test engine', None, 'explicit')
        with patch.object(game, 'is_windows', return_value=True), patch.object(game.os.path, 'isfile', return_value=True), patch.object(game.subprocess, 'Popen', return_value=proc) as start:
            self.assertIs(game.open_game(str(config), use_system_color=False, engine=engine), proc)
            self.assertEqual(start.call_args.args[0][1], 'config=' + str(config))
            self.assertIn('cwd', start.call_args.kwargs)
            self.assertNotIn('shell', start.call_args.kwargs)

    def test_instances_use_explicit_project_root(self):
        from mcpywrap.commands.run_cmd import _get_all_instances
        runtime = self.main / '.runtime'
        runtime.mkdir()
        (runtime / 'test.cppconfig').write_text('{"world_info":{"level_id":"test"}}')
        with cwd(self.dep):
            self.assertEqual(_get_all_instances(str(self.main))[0]['level_id'], 'test')
            self.assertEqual(_get_all_instances(), [])

    def test_build_primary_priority_and_incremental_fallback(self):
        self.add()
        for path, value in [(self.dep, 'dependency'), (self.main, 'main')]:
            (path / 'resource_pack' / 'blocks.json').write_text(json.dumps({value: {}, 'common': value}), encoding='utf-8')
            (path / 'resource_pack' / 'test.lang').write_text('key=' + value, encoding='utf-8')
        out = self.main / 'build'
        success, error = AddonProjectBuilder(self.main, out).build()
        self.assertTrue(success, error)
        self.assertIn("'main'", (out / 'behavior_pack' / 'marker.py').read_text())
        merged = json.loads((out / 'resource_pack' / 'blocks.json').read_text())
        self.assertEqual(merged, {'dependency': {}, 'main': {}, 'common': 'main'})
        self.assertEqual((out / 'behavior_pack' / 'manifest.json').read_bytes(), (self.main / 'behavior_pack' / 'manifest.json').read_bytes())
        watcher = ProjectWatcher(str(self.main), str(out))
        watcher.setup_from_config('main')
        handler = watcher.multi_watcher.watchers[-1].handler
        own = self.main / 'behavior_pack' / 'marker.py'
        own.unlink()
        handler.on_deleted(FileDeletedEvent(str(own)))
        self.assertIn('中文 shared', (out / 'behavior_pack' / 'marker.py').read_text(encoding='utf-8'))
        fresh = self.main / 'fresh'
        self.assertTrue(AddonProjectBuilder(self.main, fresh).build()[0])
        self.assertEqual({p.relative_to(out): p.read_bytes() for p in out.rglob('*') if p.is_file()},
                         {p.relative_to(fresh): p.read_bytes() for p in fresh.rglob('*') if p.is_file()})

    def test_incremental_events_through_directory_alias(self):
        from mcpywrap.mcstudio.symlinks import _create_directory_link
        self.add()
        out = self.main / 'build'
        self.assertTrue(AddonProjectBuilder(self.main, out).build()[0])
        alias = self.root / 'main-alias'
        _create_directory_link(str(self.main), str(alias))
        watcher = ProjectWatcher(str(alias), str(out))
        watcher.setup_from_config('main')
        handler = watcher.multi_watcher.watchers[-1].handler
        (self.main / 'behavior_pack/marker.py').unlink()
        handler.on_deleted(FileDeletedEvent(str(alias / 'behavior_pack/marker.py')))
        self.assertIn('中文 shared', (out / 'behavior_pack/marker.py').read_text(encoding='utf-8'))
        (self.main / 'behavior_pack/CamelCase.py').write_text('VALUE = 1')
        handler.on_created(FileCreatedEvent(str(alias / 'behavior_pack/CamelCase.py')))
        self.assertIn('CamelCase.py', [p.name for p in (out / 'behavior_pack').iterdir()])

    def test_invalid_dependencies_preserve_output(self):
        out = self.main / 'build'
        out.mkdir()
        sentinel = out / 'keep.txt'
        sentinel.write_text('keep')
        config = read_project(self.main)
        config['tool']['mcpywrap']['local_dependencies'] = ['../missing']
        write_project(self.main, config)
        self.assertFalse(AddonProjectBuilder(self.main, out).build()[0])
        self.assertEqual(sentinel.read_text(), 'keep')

    def test_output_cannot_cover_dependency_or_root(self):
        self.add()
        for output in [self.main, self.root, self.dep, self.dep / 'build', self.main / 'behavior_pack' / 'out']:
            with self.subTest(output=output):
                self.assertFalse(AddonProjectBuilder(self.main, output).build()[0])
        self.assertTrue((self.dep / 'behavior_pack' / 'marker.py').exists())

    def test_map_build_with_local_dependency(self):
        world = self.root / 'map'
        world.mkdir()
        (world / 'level.dat').write_bytes(b'test')
        (world / 'db').mkdir()
        write_project(world, {'project': {'name': 'map'}, 'tool': {'mcpywrap': {'project_type': 'map', 'local_dependencies': ['../中文 shared']}}})
        for merge in [False, True]:
            result, error = MapProjectBuilder(world, world / 'build', merge).build()
            self.assertTrue(result, error)
            self.assertTrue((world / 'build' / 'world_behavior_packs.json').exists())

    def test_run_and_editor_receive_local_packs(self):
        self.add()
        self.assertEqual([Path(p.path) for p in _setup_dependencies('main', str(self.main))], [self.dep, self.main])
        edit = importlib.import_module('mcpywrap.commands.edit_cmd')
        with patch.object(edit, 'discover_engines'), patch.object(edit, 'require_resources'), patch.object(edit, 'studio_installation', return_value=('test-studio', [])), patch.object(edit, 'create_editor_config', return_value={}) as config, patch.object(edit, 'open_editor'):
            edit.open_edit(str(self.main))
            self.assertEqual(config.call_args.kwargs['addon_paths'], [str(self.dep), str(self.main)])

    def test_cli_add_remove_and_noninteractive(self):
        runner = CliRunner()
        with cwd(self.main), patch('mcpywrap.dependencies.subprocess.run') as install:
            result = runner.invoke(cli, ['add', '--path', '../中文 shared'])
            self.assertEqual(result.exit_code, 0, result.output)
            install.assert_not_called()
            self.assertNotEqual(runner.invoke(cli, ['add']).exit_code, 0)
            self.assertNotEqual(runner.invoke(cli, ['add', 'thing', '--path', '../中文 shared']).exit_code, 0)
            self.assertNotEqual(runner.invoke(cli, ['remove', '--path', '../中文 shared', '--uninstall']).exit_code, 0)
            result = runner.invoke(cli, ['remove', '--path', '../中文 shared'])
            self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(self.dep.exists())

    def test_cli_interactive_add_and_remove(self):
        with cwd(self.main), patch('mcpywrap.commands.dependency_prompt.sys.stdin.isatty', return_value=True):
            runner = CliRunner()
            # CliRunner 替换 stdin，使用共用交互入口的检查替身。
            with patch('mcpywrap.commands.add_cmd.require_interactive'), patch('mcpywrap.commands.remove_cmd.require_interactive'):
                result = runner.invoke(cli, ['add'], input='2\n../中文 shared\n')
                self.assertEqual(result.exit_code, 0, result.output)
                result = runner.invoke(cli, ['remove'], input='1\n')
                self.assertEqual(result.exit_code, 0, result.output)

    def test_failed_package_install_does_not_save(self):
        before = (self.main / 'pyproject.toml').read_bytes()
        with cwd(self.main), patch('mcpywrap.dependencies.subprocess.run', return_value=Mock(returncode=1, stderr='failed', stdout='')):
            result = CliRunner().invoke(cli, ['add', 'example>=1'])
            self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(before, (self.main / 'pyproject.toml').read_bytes())
        with patch('mcpywrap.dependencies.subprocess.run', return_value=Mock(returncode=0)):
            self.service.add_package('example>=1')
        self.assertIn(DependencyDeclaration('package', 'example>=1'), self.service.list())

    def test_init_wizard_accepts_local_dependency(self):
        (self.main / 'pyproject.toml').unlink()
        init = importlib.import_module('mcpywrap.commands.init_cmd')
        with cwd(self.main), patch.object(init.time, 'sleep'), patch.object(init, 'install_project_dev_mode', return_value=True):
            result = CliRunner().invoke(cli, ['init'], input='main\n0.1.0\n\nauthor\nn\ny\n2\n../中文 shared\nn\n./build\nn\n')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(read_project(self.main)['tool']['mcpywrap']['local_dependencies'], ['../中文 shared'])


class GuiProjects(ProjectFixture):
    # GUI 测试只复用临时目录准备，不重复运行父类用例。
    def test_gui_local_add_preview_remove_and_refresh(self):
        from PyQt5.QtWidgets import QApplication, QMessageBox
        from PyQt5.QtCore import Qt
        from mcpywrap.ui import project_ui as ui
        app = QApplication.instance() or QApplication([])
        with patch.object(ui, 'find_all_mcpywrap_packages', return_value=[]), patch.object(ui, '_get_all_instances', return_value=[]):
            window = ui.GameInstanceManager(str(self.main))
        try:
            window.dependency_kind.setCurrentIndex(1)
            window.local_path_input.setText(str(self.dep))
            self.assertIn('../中文 shared', window.path_preview.toPlainText())
            with patch('mcpywrap.dependencies.subprocess.run') as install:
                window.add_dependency()
                install.assert_not_called()
            self.assertEqual(window.dependency_list.count(), 1)
            self.assertEqual(len(window.all_packs), 2)
            self.assertEqual(window.dependency_list.item(0).data(Qt.UserRole).kind, 'local')
            window.local_path_input.setText('../missing')
            window.add_dependency()
            self.assertEqual(window.local_path_input.text(), '../missing')
            window.dependency_list.setCurrentRow(0)
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                window.remove_selected_dependency()
            self.assertEqual(window.dependency_list.count(), 0)
            self.assertEqual(len(window.all_packs), 1)
        finally:
            window.close()
            app.processEvents()

    def test_gui_worker_failure_and_success(self):
        from mcpywrap.ui.project_ui import DependencyInstallThread
        thread = DependencyInstallThread('example>=1', str(self.main))
        outcomes = []
        thread.result.connect(lambda success, message: outcomes.append(success))
        with patch('mcpywrap.dependencies.subprocess.run', return_value=Mock(returncode=1, stderr='failed', stdout='')):
            thread.run()
        self.assertEqual(self.service.list(), [])
        with patch('mcpywrap.dependencies.subprocess.run', return_value=Mock(returncode=0)):
            thread.run()
        self.assertEqual(outcomes, [False, True])

    def test_gui_browse_cancel_absolute_and_invalid_removal(self):
        from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox
        from mcpywrap.ui import project_ui as ui
        app = QApplication.instance() or QApplication([])
        window = ui.GameInstanceManager(str(self.main))
        try:
            window.dependency_kind.setCurrentIndex(1)
            with patch.object(QFileDialog, 'getExistingDirectory', return_value=str(self.dep)):
                window.browse_dependency()
            self.assertEqual(self.service.list(), [])
            with patch.object(QFileDialog, 'getExistingDirectory', return_value=''):
                window.browse_dependency()
            self.assertEqual(window.local_path_input.text(), str(self.dep))
            window.absolute_path_check.setChecked(True)
            window.add_dependency()
            self.assertEqual(self.service.list()[0].value, self.dep.as_posix())
            shutil.rmtree(self.dep)
            window.refresh_dependencies()
            self.assertFalse(window.reload_runtime_dependencies())
            self.assertIn('不可用', window.dependency_list.item(0).text())
            self.assertIn('目录不存在', window.log_output.toPlainText())
            self.assertFalse(window.new_btn.isEnabled())
            window.dependency_list.setCurrentRow(0)
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                window.remove_selected_dependency()
            self.assertEqual(self.service.list(), [])
            self.assertTrue(window.new_btn.isEnabled())
        finally:
            window.close()
            app.processEvents()

    def test_gui_background_install_busy_failure_and_success(self):
        import time
        import threading
        from PyQt5.QtWidgets import QApplication
        from mcpywrap.ui import project_ui as ui
        app = QApplication.instance() or QApplication([])
        window = ui.GameInstanceManager(str(self.main))
        try:
            for succeeds in (False, True):
                released = threading.Event()
                def install(*args, **kwargs):
                    released.wait(5)
                    return Mock(returncode=0 if succeeds else 1, stderr='install failed', stdout='')
                with patch('mcpywrap.dependencies.subprocess.run', side_effect=install):
                    window.new_dep_input.setCurrentText('click>=8')
                    window.add_dependency()
                    self.assertTrue(window.dependency_busy)
                    self.assertFalse(window.add_dep_btn.isEnabled())
                    self.assertFalse(window.new_btn.isEnabled())
                    released.set()
                    deadline = time.monotonic() + 5
                    while window.dependency_busy and time.monotonic() < deadline:
                        app.processEvents()
                        time.sleep(0.01)
                    self.assertFalse(window.dependency_busy)
                    self.assertEqual(bool(self.service.list()), succeeds)
                    self.assertEqual(window.new_dep_input.currentText(), '' if succeeds else 'click>=8')
        finally:
            window.close()
            app.processEvents()


if __name__ == '__main__':
    unittest.main()

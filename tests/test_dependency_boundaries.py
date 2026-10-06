"""工具环境与游戏包的边界：真实目录、产物及 CLI/Qt，安装和启动使用替身。"""
import importlib
import inspect
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from watchdog.events import FileCreatedEvent, FileDeletedEvent, FileModifiedEvent, FileMovedEvent

from mcpywrap.cli import cli
from mcpywrap.dependencies import DependencyError, DependencyService, read_project, write_project
from mcpywrap.builders.project_builder import AddonProjectBuilder, MapProjectBuilder
from mcpywrap.builders.watcher import ProjectWatcher
from mcpywrap.mcstudio.network import prepare_project
from test_local_dependencies import ProjectFixture, FakeDist, addon


DIST = 'mcpywrap.builders.dependency_manager.metadata.distribution'


class Boundaries(ProjectFixture):
    def setUp(self):
        super().setUp()
        host = patch('mcpywrap.engines.backend.describe', return_value={'backend': 'windows'})
        host.start()
        self.addCleanup(host.stop)

    def call(self, *args):
        options = {'mix_stderr': False} if 'mix_stderr' in inspect.signature(CliRunner).parameters else {}
        return CliRunner(**options).invoke(cli, ['--local', '--project', str(self.main), '--non-interactive', *args, '--json'])

    def packages(self, *values):
        config = read_project(self.main)
        config['project']['dependencies'] = list(values)
        write_project(self.main, config)

    def test_host_packages_warn_without_entering_artifact(self):
        self.packages('pure-package>=1', 'native-package>=1')
        self.add()
        with patch(DIST, return_value=FakeDist()):
            result = self.call('package')
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.stdout)
        self.assertEqual(len(data['warnings']), 2)
        self.assertTrue(all(str(self.main) in w and '仅安装于工具环境' in w for w in data['warnings']))
        with zipfile.ZipFile(data['artifact']) as archive:
            self.assertIn('main_bp/marker.py', archive.namelist())
            self.assertFalse(any('site-packages' in n or 'native-package' in n for n in archive.namelist()))

    def test_add_json_classification_duplicate_and_marker(self):
        with patch.object(DependencyService, 'install_package'), patch(DIST, return_value=FakeDist()):
            first = self.call('add', 'example>=1')
            again = self.call('add', 'example>=1')
            inactive = self.call('add', 'unused; python_version < "2"')
        for result in (first, again, inactive):
            self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(first.stdout)['classification'], 'development_only')
        self.assertIn('未识别到可组装内容', json.loads(first.stdout)['warnings'][0])
        self.assertFalse(json.loads(again.stdout)['changed'])
        self.assertEqual(json.loads(inactive.stdout)['classification'], 'inactive')

    def test_init_package_wizard_reports_development_scope(self):
        (self.main / 'pyproject.toml').unlink()
        with patch('mcpywrap.commands.init_cmd.non_interactive', return_value=False), patch(
                'mcpywrap.dependencies.DependencyService.install_package'), patch(DIST, return_value=FakeDist()):
            result = CliRunner().invoke(cli, ['--local', '--project', str(self.main), 'init'],
                                        input='main\n0.1.0\naddon\n./build\ny\n1\nexample>=1\nn\n')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('仅安装于工具环境', result.output)
        self.assertEqual(read_project(self.main)['project']['dependencies'], ['example>=1'])

    def test_add_local_duplicate_using_absolute_path(self):
        self.add()
        result = self.call('add', '--path', str(self.dep))
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(json.loads(result.stdout)['changed'])
        self.assertEqual(json.loads(result.stdout)['classification'], 'addon')

    def test_gui_worker_emits_development_warning(self):
        from mcpywrap.ui.project_ui import DependencyInstallThread
        worker = DependencyInstallThread('example>=1', str(self.main))
        messages, outcomes = [], []
        worker.log_message.connect(lambda message, level: messages.append((message, level)))
        worker.result.connect(lambda success, message: outcomes.append(success))
        with patch.object(DependencyService, 'install_package'), patch(DIST, return_value=FakeDist()):
            worker.run()
        self.assertEqual(outcomes, [True])
        self.assertTrue(any('仅安装于工具环境' in message and level == 'warning' for message, level in messages))

    def test_package_addon_recognized_and_invalid_install_not_saved(self):
        with patch.object(DependencyService, 'install_package'), patch(DIST, return_value=FakeDist(self.dep)):
            result = self.call('add', 'shared>=1')
            self.assertEqual(json.loads(result.stdout)['classification'], 'addon')
            before = (self.main / 'pyproject.toml').read_bytes()
            native = self.dep / 'behavior_pack/extension.PYD'
            native.touch()
            result = self.call('add', 'another>=1')
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn(str(native), json.loads(result.stdout)['error'])
        self.assertIn('工具环境完成安装', json.loads(result.stdout)['error'])
        self.assertEqual((self.main / 'pyproject.toml').read_bytes(), before)

    def test_native_sources_fail_before_output_changes(self):
        self.add()
        output = self.main / 'build'
        self.assertTrue(AddonProjectBuilder(self.main, output).build()[0])
        snapshot = {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()}
        for source in (self.main, self.dep):
            for name in ('a.PyD', 'a.DLL', 'a.So', 'a.so.1.20', 'a.DyLiB'):
                with self.subTest(source=source, name=name):
                    native = source / 'resource_pack' / name
                    native.touch()
                    try:
                        ok, error = AddonProjectBuilder(self.main, output).build()
                        self.assertFalse(ok)
                        self.assertIn(str(native), error)
                        self.assertEqual(snapshot, {p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()})
                    finally:
                        native.unlink()

    def test_nested_local_native_add_does_not_save(self):
        nested = addon(self.root, 'nested', configured=True, local=['../中文 shared'])
        native = self.dep / 'behavior_pack/a.dll'
        native.touch()
        before = (self.main / 'pyproject.toml').read_bytes()
        with self.assertRaisesRegex(DependencyError, '原生二进制') as error:
            self.service.add_local(str(nested))
        self.assertIn('../中文 shared', str(error.exception))
        self.assertEqual(before, (self.main / 'pyproject.toml').read_bytes())

    def test_map_own_native_and_tool_files_outside_packs(self):
        (self.main / 'developer-tool.dll').touch()
        self.assertTrue(AddonProjectBuilder(self.main, self.main / 'build').build()[0])
        world = self.root / 'world'
        (world / 'behavior_packs/first').mkdir(parents=True)
        (world / 'behavior_packs/second').mkdir()
        write_project(world, {'tool': {'mcpywrap': {'project_type': 'map'}}})
        (world / 'behavior_packs/second/a.so.2').touch()
        for merge in (False, True):
            success, error = MapProjectBuilder(world, world / 'build', merge).build()
            self.assertFalse(success)
            self.assertIn('second', error)
            self.assertFalse((world / 'build').exists())

    def test_existing_zip_survives_and_json_carries_error(self):
        first = self.call('package')
        archive = Path(json.loads(first.stdout)['artifact'])
        before = archive.read_bytes()
        (self.main / 'behavior_pack/a.dll').touch()
        for command in ('package', 'build'):
            result = self.call(command)
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn('原生二进制', json.loads(result.stdout)['error'])
        self.assertEqual(archive.read_bytes(), before)

    def test_run_edit_and_network_validate_before_start(self):
        run = importlib.import_module('mcpywrap.commands.run_cmd')
        edit = importlib.import_module('mcpywrap.commands.edit_cmd')
        (self.main / 'behavior_pack/a.dll').touch()
        with patch.object(run, 'setup_global_addons_symlinks') as links, patch('mcpywrap.mcstudio.sessions.start') as start:
            result = self.call('run', '--detach', '--no-gui')
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn('原生二进制', json.loads(result.stdout)['error'])
            links.assert_not_called()
            start.assert_not_called()
        with patch.object(edit, 'open_editor') as launch, self.assertRaises(DependencyError):
            edit.open_edit(self.main, raise_errors=True)
        launch.assert_not_called()
        with self.assertRaises(DependencyError):
            prepare_project(self.main)

    def test_run_json_warns_for_host_dependency(self):
        self.packages('example>=1')
        with patch(DIST, return_value=FakeDist()), patch('mcpywrap.mcstudio.sessions.start', return_value={}), patch(
                'mcpywrap.mcstudio.sessions.handoff', return_value={'session': 'test'}):
            result = self.call('run', '--detach', '--no-gui')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('仅安装于工具环境', json.loads(result.stdout)['warnings'][0])

    def test_incremental_native_create_move_delete_and_recovery(self):
        self.add()
        output = self.main / 'build'
        self.assertTrue(AddonProjectBuilder(self.main, output).build()[0])
        events = []
        watcher = ProjectWatcher(str(self.main), str(output), lambda *args: events.append(args))
        watcher.setup_from_config('main')
        handler = watcher.multi_watcher.watchers[0].handler
        marker = self.dep / 'behavior_pack/new.py'
        native = self.dep / 'behavior_pack/a.dll'
        native.touch()
        handler.on_created(FileCreatedEvent(str(native)))
        self.assertFalse(events[-1][2])
        marker.write_text('VALUE = 1\n')
        handler.on_modified(FileModifiedEvent(str(marker)))
        self.assertFalse(events[-1][2])
        self.assertFalse((output / 'behavior_pack/new.py').exists())
        native.unlink()
        handler.on_deleted(FileDeletedEvent(str(native)))
        handler.on_modified(FileModifiedEvent(str(marker)))
        self.assertTrue(events[-1][2])
        self.assertTrue((output / 'behavior_pack/new.py').exists())
        external = self.root / 'a.dll'
        external.touch()
        external.rename(native)
        handler.on_moved(FileMovedEvent(str(external), str(native)))
        self.assertFalse(events[-1][2])
        native.unlink()
        handler.on_deleted(FileDeletedEvent(str(native)))
        full = self.main / 'full-build'
        self.assertTrue(AddonProjectBuilder(self.main, full).build()[0])
        self.assertEqual({p.relative_to(output): p.read_bytes() for p in output.rglob('*') if p.is_file()},
                         {p.relative_to(full): p.read_bytes() for p in full.rglob('*') if p.is_file()})

    def test_gui_development_warning_does_not_block_and_native_does(self):
        from PySide6.QtWidgets import QApplication
        from mcpywrap.ui import project_ui as ui
        self.packages('click>=8')
        app = QApplication.instance() or QApplication([])
        with patch.object(ui, 'find_all_mcpywrap_packages', return_value=[]), patch('mcpywrap.engines.macos.MacOSBackend.instances', return_value=[]):
            window = ui.GameInstanceManager(str(self.main))
        try:
            self.assertIn('仅开发环境', window.dependency_list.item(0).text())
            self.assertTrue(window.new_btn.isEnabled())
            (self.main / 'behavior_pack/a.dll').touch()
            self.assertFalse(window.reload_runtime_dependencies())
            self.assertFalse(window.new_btn.isEnabled())
            window.dependency_list.setCurrentRow(0)
            window.dependency_list.itemClicked.emit(window.dependency_list.item(0))
            self.assertTrue(window.remove_dep_btn.isEnabled())
        finally:
            window.close()
            app.processEvents()

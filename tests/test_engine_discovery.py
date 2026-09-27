"""隔离文件系统与 Windows 来源，不触碰真实安装或启动游戏。"""
import importlib
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from click.testing import CliRunner

from mcpywrap.cli import cli
from mcpywrap.mcstudio import discovery as d


class EngineDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.project = self.root / '中文 project'
        self.project.mkdir()
        self.registry = self.stack.enter_context(patch.object(d, 'registry_values', return_value=[]))
        self.drives = self.stack.enter_context(patch.object(d, 'fixed_drives', return_value=[]))
        self.stack.enter_context(patch.dict(os.environ, {key: value for key, value in os.environ.items() if key in ('PATH', 'SystemRoot', 'SYSTEMROOT', 'TEMP', 'TMP')}, clear=True))
        os.environ['APPDATA'] = str(self.root / 'appdata')
        (self.root / 'appdata/MinecraftPE_Netease/games/com.netease').mkdir(parents=True)

    def engine(self, download, version, complete=True):
        path = download / 'game/MinecraftPE_Netease' / version / d.EXE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        if complete:
            path.write_bytes(b'fake-executable')
        return path

    def resources(self, download):
        skin = download / 'componentcache/support/steve/steve.png'
        skin.parent.mkdir(parents=True)
        skin.write_bytes(b'fake-skin')

    def configured(self, content):
        (self.project / 'pyproject.toml').write_text('[tool.mcpywrap]\n' + content, encoding='utf-8')

    def discover(self, **kwargs):
        return d.discover_engines(self.project, **kwargs)

    def test_semantic_versions_skip_junk_and_incomplete(self):
        root = self.root / 'registered'
        for version in ('3.9.0.1', '3.10.0.1', 'temp', '3.10-backup', 'PCLauncher99'):
            self.engine(root, version)
        self.engine(root, '3.11.0.1', complete=False)
        self.registry.return_value = [(str(root), 'registry64')]
        result = self.discover()
        self.assertEqual([e.version for e in result.candidates], ['3.10.0.1', '3.9.0.1'])
        self.assertEqual(result.selected.version, '3.10.0.1')
        self.assertEqual(len(result.diagnostics), 4)
        self.drives.assert_not_called()

    def test_registry_priority_and_deduplication(self):
        root = self.root / 'registered'
        self.engine(root, '3.9')
        self.engine(self.root / 'drive/MCStudioDownload', '3.10')
        self.registry.return_value = [(str(root), 'registry64'), (str(root / '.'), 'registry32')]
        self.drives.return_value = [str(self.root / 'drive')]
        result = self.discover()
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.selected.source, 'registry64')
        self.drives.assert_not_called()

    def test_fallback_scans_all_disks_with_stable_tie(self):
        a = self.root / 'a/MCStudioDownload'
        b = self.root / 'b/MCStudioDownload'
        self.engine(a, '3.9')
        self.engine(a, '3.10')
        self.engine(b, '3.10')
        self.registry.return_value = [(str(self.root / 'removed'), 'registry64')]
        self.drives.return_value = [str(b.parent), str(a.parent)]
        result = self.discover()
        self.assertEqual(result.selected.download_dir, str(a))
        self.assertEqual(result.selected.source, 'disk')
        self.assertTrue(result.diagnostics)

    def test_pin_searches_fallback_even_when_registry_has_other_version(self):
        registered = self.root / 'registered'
        fallback = self.root / 'drive/MCStudioDownload'
        self.engine(registered, '3.10')
        self.engine(fallback, '3.9')
        self.registry.return_value = [(str(registered), 'registry64')]
        self.drives.return_value = [str(fallback.parent)]
        result = self.discover(instance_version='3.9')
        self.assertEqual(result.selected.download_dir, str(fallback))

    def test_missing_pin_lists_versions_without_switching(self):
        root = self.root / 'registered'
        self.engine(root, '3.10')
        self.registry.return_value = [(str(root), 'registry64')]
        result = self.discover(overrides={'engine_version': '3.8'})
        self.assertIsNone(result.selected)
        self.assertIn('可用版本: 3.10', result.error)

    def test_explicit_root_never_falls_back(self):
        root = self.root / 'registered'
        self.engine(root, '3.10')
        self.registry.return_value = [(str(root), 'registry64')]
        for path in [self.root / 'missing', self.project]:
            with self.subTest(path=path):
                result = self.discover(overrides={'mcs_download_path': str(path)})
                self.assertIsNone(result.selected)
                self.assertTrue(result.error)
        self.registry.assert_not_called()
        self.drives.assert_not_called()

    def test_unreadable_root_does_not_block_fallback(self):
        blocked = self.root / 'blocked'
        self.engine(blocked, '3.10')
        fallback = self.root / 'drive/MCStudioDownload'
        self.engine(fallback, '3.9')
        self.registry.return_value = [(str(blocked), 'registry64')]
        self.drives.return_value = [str(fallback.parent)]
        original = Path.iterdir

        def iterdir(path):
            if path == blocked / 'game/MinecraftPE_Netease':
                raise PermissionError('permission denied')
            return original(path)

        with patch.object(Path, 'iterdir', iterdir):
            result = self.discover()
        self.assertEqual(result.selected.version, '3.9')
        self.assertIn('permission denied', result.diagnostics[0]['message'])

    def test_no_cross_call_cache(self):
        root = self.root / 'registered'
        self.engine(root, '3.9')
        self.registry.return_value = [(str(root), 'registry64')]
        self.assertEqual(self.discover().selected.version, '3.9')
        newer = self.engine(root, '3.10')
        self.assertEqual(self.discover().selected.version, '3.10')
        newer.unlink()
        self.assertEqual(self.discover().selected.version, '3.9')

    def test_overrides_and_relative_path_bases(self):
        self.configured("game_executable_path = 'project.exe'\nmcs_download_path = 'downloads'\nengine_version = '3.8'\n")
        env = {'MCPY_GAME_EXECUTABLE': 'env.exe', 'MCPY_ENGINE_VERSION': '3.9'}
        options = d.discovery_options(self.project, {'engine_version': '3.10'}, env, self.root)
        self.assertEqual(options, {'game_executable_path': str(self.root / 'env.exe'),
                                  'mcs_download_path': str(self.project / 'downloads'),
                                  'engine_version': '3.10'})
        options = d.discovery_options(self.project, {'game_executable_path': 'cli.exe'}, env, self.root)
        self.assertEqual(options['game_executable_path'], str(self.root / 'cli.exe'))
        self.assertEqual(options['engine_version'], '3.9')

    def test_bad_configuration_is_reported(self):
        for config in ['engine_version = 3', 'engine_version = "nonsense"', 'game_executable_path = ""', '[bad']:
            with self.subTest(config=config):
                self.configured(config)
                self.assertTrue(self.discover().error)

    def test_explicit_exe_infers_root_and_rejects_conflicts(self):
        root = self.root / '中文 download'
        exe = self.engine(root, '3.10')
        result = self.discover(overrides={'game_executable_path': str(exe)})
        self.assertEqual(result.selected.download_dir, str(root))
        for options in [
            {'engine_version': '3.9'},
            {'mcs_download_path': str(self.project)},
        ]:
            result = self.discover(overrides=dict(options, game_executable_path=str(exe)))
            self.assertIn('冲突', result.error)
        self.registry.assert_not_called()

    def test_invalid_exe_never_falls_back(self):
        result = self.discover(overrides={'game_executable_path': str(self.root / d.EXE_NAME)})
        self.assertTrue(result.error)
        self.registry.assert_not_called()
        self.drives.assert_not_called()

    def test_nonstandard_exe_requires_explicit_version_and_reports_resources(self):
        exe = self.project / d.EXE_NAME
        exe.write_bytes(b'fake')
        options = {'game_executable_path': str(exe)}
        self.assertIn('engine_version', self.discover(overrides=options, instance_version='3.10').error)
        options['engine_version'] = '3.10'
        result = self.discover(overrides=options)
        self.assertIsNotNone(result.selected)
        self.assertIsNone(result.selected.download_dir)
        self.assertIn('mcs_download_path', d.resource_issues(result.selected)[0])
        options['mcs_download_path'] = str(self.project)
        result = self.discover(overrides=options)
        self.assertIn('steve.png', '\n'.join(d.resource_issues(result.selected)))

    def test_nonstandard_exe_uses_registry_for_resources(self):
        exe = self.project / d.EXE_NAME
        exe.write_bytes(b'fake')
        download = self.root / 'registered'
        self.resources(download)
        self.registry.return_value = [(str(download), 'registry64')]
        engine = self.discover(overrides={'game_executable_path': str(exe), 'engine_version': '3.10'}).require_engine()
        self.assertEqual(d.resource_issues(engine), [])

    def test_project_pin_overrides_instance(self):
        root = self.root / 'registered'
        self.engine(root, '3.9')
        self.engine(root, '3.10')
        self.registry.return_value = [(str(root), 'registry64')]
        self.assertEqual(self.discover(instance_version='3.9').selected.version, '3.9')
        self.configured("engine_version = '3.10'\n")
        self.assertEqual(self.discover(instance_version='3.9').selected.version, '3.10')

    def test_doctor_is_readonly_without_project_and_json_on_failure(self):
        doctor = importlib.import_module('mcpywrap.commands.doctor_cmd')
        root = self.root / 'registered'
        self.engine(root, '3.10')
        self.resources(root)
        self.registry.return_value = [(str(root), 'registry64')]
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=self.root):
            before = set(Path.cwd().rglob('*'))
            with patch.object(doctor, 'studio_installation', return_value=(None, ['未安装编辑器'])), patch('subprocess.Popen') as start:
                result = runner.invoke(cli, ['doctor', '--json'])
                self.assertEqual(result.exit_code, 0, result.output)
                data = json.loads(result.output)
                self.assertTrue(data['ok'])
                self.assertEqual(data['selected']['source'], 'registry64')
                self.assertTrue(data['resources']['editor'])
                result = runner.invoke(cli, ['doctor', '--json', '--engine-version', '9.9'])
                self.assertEqual(result.exit_code, 1)
                self.assertIn('9.9', json.loads(result.output)['error'])
                start.assert_not_called()
            self.assertEqual(set(Path.cwd().rglob('*')), before)

    def test_legacy_wrappers_only_return_selected_root(self):
        from mcpywrap.mcstudio import mcs
        first = self.root / 'a'
        second = self.root / 'b'
        self.engine(first, '3.9')
        self.engine(second, '3.10')
        self.registry.return_value = [(str(first), 'registry64'), (str(second), 'registry32')]
        with patch.object(d, 'discovery_options', return_value={}):
            self.assertEqual(mcs.get_mcs_download_path(), str(second))
            self.assertEqual(mcs.get_mcs_game_engine_dirs(), ['3.10'])

    def test_open_game_reuses_engine_and_rejects_mismatch(self):
        game = importlib.import_module('mcpywrap.mcstudio.game')
        exe = self.engine(self.root / 'download', '3.10')
        engine = d.Engine(str(exe), '3.10', str(exe.parent), str(self.root / 'download'), 'explicit')
        config = self.project / 'space config.cppconfig'
        config.write_text('{"version": "3.10"}')
        process = Mock()
        with patch.object(game, 'is_windows', return_value=True), patch.object(game, 'discover_engines') as scan, patch.object(game.subprocess, 'Popen', return_value=process) as start:
            self.assertIs(game.open_game(str(config), engine=engine, use_system_color=False), process)
            scan.assert_not_called()
            self.assertEqual(start.call_args.args[0][0], str(exe))
            self.assertEqual(start.call_args.kwargs['cwd'], str(exe.parent))
            config.write_text('{"version": "3.9"}')
            start.reset_mock()
            self.assertFalse(game.open_game(str(config), engine=engine, use_system_color=False))
            start.assert_not_called()

    def test_run_preserves_instance_version_and_passes_same_engine(self):
        run = importlib.import_module('mcpywrap.commands.run_cmd')
        root = self.root / 'registered'
        self.engine(root, '3.9')
        self.engine(root, '3.10')
        self.resources(root)
        self.registry.return_value = [(str(root), 'registry64')]
        path = self.project / '.runtime/test.cppconfig'
        path.parent.mkdir()
        path.write_text('{"version":"3.9"}')
        captured = []

        def launch(config_path, **kwargs):
            captured.append(kwargs['engine'])
            self.assertEqual(json.loads(Path(config_path).read_text(encoding='utf-8'))['version'], kwargs['engine'].version)
            return Mock()

        with patch.object(run, '_setup_dependencies', return_value=[]), patch.object(run, 'setup_global_addons_symlinks', return_value=(True, [], [])), patch.object(run, 'open_game', side_effect=launch), patch.object(run, 'is_windows', return_value=False), patch.object(run, 'open_safaia'), patch.object(run, '_gen_random_port', return_value=10000):
            self.assertTrue(run._run_game_with_instance(str(path), 'test', [], wait=False)[0])
            self.assertEqual(captured[-1].version, '3.9')
            self.assertTrue(run._run_game_with_instance(str(path), 'test', [], wait=False, engine_overrides={'engine_version': '3.10'})[0])
            self.assertEqual(captured[-1].version, '3.10')

    def test_run_failure_does_not_link_write_or_launch(self):
        run = importlib.import_module('mcpywrap.commands.run_cmd')
        path = self.project / '.runtime/test.cppconfig'
        with patch.object(run, '_setup_dependencies', return_value=[]), patch.object(run, 'setup_global_addons_symlinks') as links, patch.object(run, 'open_game') as launch, patch.object(run, 'open_safaia') as logs:
            self.assertEqual(run._run_game_with_instance(str(path), 'test', [], wait=False), (False, None))
            links.assert_not_called()
            launch.assert_not_called()
            logs.assert_not_called()
            self.assertFalse(path.exists())

    def test_missing_resources_preserve_existing_instance(self):
        run = importlib.import_module('mcpywrap.commands.run_cmd')
        root = self.root / 'registered'
        self.engine(root, '3.10')
        self.registry.return_value = [(str(root), 'registry64')]
        path = self.project / '.runtime/test.cppconfig'
        path.parent.mkdir()
        path.write_text('{"version":"3.10"}')
        before = path.read_bytes()
        with patch.object(run, '_setup_dependencies', return_value=[]), patch.object(run, 'setup_global_addons_symlinks') as links, patch.object(run, 'open_game') as launch:
            self.assertFalse(run._run_game_with_instance(str(path), 'test', [], wait=False)[0])
            links.assert_not_called()
            launch.assert_not_called()
            self.assertEqual(path.read_bytes(), before)

    def test_failed_launch_does_not_start_logging_or_report_success(self):
        run = importlib.import_module('mcpywrap.commands.run_cmd')
        root = self.root / 'registered'
        self.engine(root, '3.10')
        self.resources(root)
        self.registry.return_value = [(str(root), 'registry64')]
        path = self.project / '.runtime/test.cppconfig'
        messages = []
        with patch.object(run, '_setup_dependencies', return_value=[]), patch.object(run, 'setup_global_addons_symlinks', return_value=(True, [], [])), patch.object(run, 'open_game', return_value=False), patch.object(run, 'open_safaia') as safaia, patch('mcpywrap.mcstudio.studio_server_ui.run_studio_server_ui_subprocess') as logs, patch.object(run, '_gen_random_port', return_value=10000):
            self.assertFalse(run._run_game_with_instance(str(path), 'test', [], wait=False, log_callback=lambda message, level: messages.append(message))[0])
            safaia.assert_not_called()
            logs.assert_not_called()
            self.assertFalse(any('游戏已启动' in message for message in messages))

    def test_cli_run_forwards_overrides(self):
        run = importlib.import_module('mcpywrap.commands.run_cmd')
        from mcpywrap.mcstudio import sessions
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=self.root):
            Path('pyproject.toml').write_text('[project]\nname="sample"\n')
            record = {'project': str(Path.cwd()), 'session': 'test', 'state': 'running',
                      'game': {'pid': 123}, 'log_path': 'test.log'}
            with patch.object(run, '_setup_dependencies', return_value=[]), patch.object(sessions, 'start', return_value=record) as start:
                result = runner.invoke(cli, ['run', '--new', '--detach', '--engine-version', '3.10', '--mcs-download-path', 'custom'])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(start.call_args.args[3]['engine_version'], '3.10')
                self.assertEqual(start.call_args.args[3]['mcs_download_path'], 'custom')

    def test_nonstandard_exe_not_returned_as_legacy_version_directory(self):
        from mcpywrap.mcstudio import mcs
        root = self.root / 'registered'
        self.engine(root, '3.9')
        exe = self.project / d.EXE_NAME
        exe.write_bytes(b'fake')
        options = {'game_executable_path': str(exe), 'engine_version': '3.10', 'mcs_download_path': str(root)}
        with patch.object(d, 'discovery_options', return_value=options):
            self.assertEqual(mcs.get_mcs_game_engine_dirs(), ['3.9'])

    def test_editor_uses_one_selection_for_configuration_and_launch(self):
        edit = importlib.import_module('mcpywrap.commands.edit_cmd')
        root = self.root / 'registered'
        self.engine(root, '3.10')
        self.registry.return_value = [(str(root), 'registry64')]
        editor_exe = root / 'MCX64Editor/MC_Editor.exe'
        editor_exe.parent.mkdir()
        editor_exe.write_bytes(b'fake')
        (root / 'EngineAssert').mkdir()
        install = self.root / 'studio'
        (install / 'data/inner_res').mkdir(parents=True)
        with patch('mcpywrap.commands.run_cmd._setup_dependencies', return_value=[]), patch.object(edit, 'studio_installation', return_value=(str(install), [])), patch.object(edit, 'open_editor', return_value=Mock(pid=os.getpid())) as launch, patch.object(edit, 'discover_engines', wraps=d.discover_engines) as scan:
            edit.open_edit(str(self.project))
            self.assertEqual(scan.call_count, 1)
            engine = launch.call_args.kwargs['engine']
            config = json.loads((self.project / 'studio.json').read_text(encoding='utf-8'))
            self.assertEqual(config['EditVersion'], engine.version)
            self.assertEqual(config['AssertCacheDir'], str(root / 'EngineAssert'))


@unittest.skipUnless(os.name == 'nt', 'Windows 注册表与磁盘 API')
class WindowsSourcesTests(unittest.TestCase):
    def test_registry_views_deduplicate_and_continue_after_denial(self):
        import winreg
        context = Mock()
        context.__enter__ = Mock(return_value=object())
        context.__exit__ = Mock(return_value=False)
        with patch.object(winreg, 'OpenKey', return_value=context) as opened, patch.object(winreg, 'QueryValueEx', return_value=('D:\\MCStudioDownload', winreg.REG_SZ)):
            self.assertEqual(len(d.registry_values('DownloadPath')), 1)
            self.assertEqual({call.args[3] for call in opened.call_args_list},
                             {winreg.KEY_READ | winreg.KEY_WOW64_64KEY, winreg.KEY_READ | winreg.KEY_WOW64_32KEY})
        diagnostics = []
        with patch.object(winreg, 'OpenKey', side_effect=[PermissionError('denied'), context]), patch.object(winreg, 'QueryValueEx', return_value=('D:\\MCStudioDownload', winreg.REG_SZ)):
            values = d.registry_values('DownloadPath', diagnostics)
            self.assertEqual(values[0][1], 'registry32')
            self.assertIn('denied', diagnostics[0]['message'])

    def test_disks_exclude_network_and_removable(self):
        kernel = Mock()
        kernel.GetLogicalDrives.return_value = (1 << 2) | (1 << 3) | (1 << 4)
        kernel.GetDriveTypeW.side_effect = [3, 4, 2]
        with patch.object(d.ctypes, 'windll', Mock(kernel32=kernel)):
            self.assertEqual(d.fixed_drives(), ['C:\\'])


if __name__ == '__main__':
    unittest.main()

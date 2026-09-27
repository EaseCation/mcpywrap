"""未认证网络调度：不需要 MCS、认证服务或真实游戏。"""
import importlib
import inspect
import json
import socket
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from click.testing import CliRunner

from mcpywrap.cli import cli
from mcpywrap.dependencies import DependencyError
from mcpywrap.mcstudio import network as n
from mcpywrap.mcstudio.discovery import Engine, discovery_options


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / '中文 项目'
        self.project.mkdir()
        options = {'mix_stderr': False} if 'mix_stderr' in inspect.signature(CliRunner).parameters else {}
        self.runner = CliRunner(**options)

    def config(self, text='[tool.mcpywrap.server]\nhost="127.0.0.1"\n'):
        (self.project / 'pyproject.toml').write_text(text, encoding='utf-8')

    def call(self, *args):
        return self.runner.invoke(cli, ['--project', str(self.project), '--non-interactive', *args, '--json'])

    def addon(self, root):
        pack = root / 'behavior_pack_demo'
        pack.mkdir(parents=True)
        (pack / 'manifest.json').write_text(json.dumps({
            'header': {'uuid': str(uuid.uuid4()), 'name': 'test', 'version': [1, 0, 0]},
            'modules': [{'uuid': str(uuid.uuid4()), 'type': 'data', 'version': [1, 0, 0]}]}))

    def test_target_validation(self):
        for host in ('127.0.0.1', '::1', 'example.com', '中文.example'):
            self.assertEqual(n.ServerTarget(host).port, 19132)
        for host in ('', None, ' x', 'a:123', 'http://host', 'a/b', 'a\n', '-host'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                n.ServerTarget(host)
        for port in (True, '19132', 0, 65536, 1.5):
            with self.assertRaises(ValueError):
                n.ServerTarget('localhost', port)
        for value in ({}, None, 'host', {'host': 'a', 'prot': 10}):
            with self.assertRaises(ValueError):
                n.configured_target({'tool': {'mcpywrap': {'server': value}}})
        self.assertIsNone(n.configured_target({}))

    def test_empty_project_and_dependency_only_and_root(self):
        self.config()
        self.assertEqual(n.prepare_project(self.project), [])
        dep = self.root / '共享 addon'
        self.addon(dep)
        self.config('[tool.mcpywrap]\nlocal_dependencies=["../共享 addon"]\n'
                    '[tool.mcpywrap.server]\nhost="localhost"\n')
        packs = n.prepare_project(self.project)
        self.assertEqual(len(packs), 1)
        self.assertTrue(Path(packs[0].path).samefile(dep))
        self.addon(self.project)
        self.assertEqual(len(n.prepare_project(self.project)), 2)
        self.assertFalse((dep / 'pyproject.toml').exists())

    def test_bad_structure_is_not_treated_as_empty(self):
        for marker in ('behavior_pack', 'resource_pack', 'level.dat', 'manifest.json'):
            path = self.project / marker
            path.touch()
            with self.subTest(marker=marker), self.assertRaises(DependencyError):
                n.prepare_project(self.project)
            path.unlink()
        self.config('[tool.mcpywrap]\nlocal_dependencies=["../missing"]\n')
        with self.assertRaises(DependencyError):
            n.prepare_project(self.project)
        self.config('[tool.mcpywrap]\nproject_type="map"\n')
        with self.assertRaises(ValueError):
            n.prepare_project(self.project)
        self.config('[project]\ndependencies=["mcpy-nonexistent-test-package>=9"]\n')
        with self.assertRaises(DependencyError):
            n.prepare_project(self.project)

    def test_cli_run_routes_before_local_side_effects(self):
        self.config()
        before = (self.project / 'pyproject.toml').read_bytes()
        with patch.object(n, 'run_network', return_value={'authenticated': False}) as launch:
            result = self.call('run')
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(launch.call_args.args[0], n.ServerTarget('127.0.0.1'))
            self.assertEqual(launch.call_args.kwargs['packs'], [])
            self.assertFalse((self.project / '.runtime').exists())
        self.assertEqual(before, (self.project / 'pyproject.toml').read_bytes())

    def test_cli_connect_ignores_project_and_requires_host(self):
        self.config('invalid = [')
        with patch('mcpywrap.commands.connect_cmd.run_network', return_value={}) as launch:
            result = self.call('connect', 'localhost', '--port', '20000')
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(launch.call_args.args[0], n.ServerTarget('localhost', 20000))
            self.assertNotIn('project_dir', launch.call_args.kwargs)
        self.assertEqual(self.call('connect').exit_code, 2)
        self.assertEqual(self.call('connect', 'localhost', '--port', '0').exit_code, 2)
        self.assertFalse((self.project / '.runtime').exists())
        self.assertEqual(discovery_options(self.project, environ={}, read_project_config=False), {})

    def test_network_options_and_invalid_config_never_start_world(self):
        run = importlib.import_module('mcpywrap.commands.run_cmd')
        self.config()
        with patch.object(run, '_run_game_with_instance') as local, patch.object(n, 'run_network') as launch:
            for args in (('run', '--new'), ('run', '1234'), ('run', '--detach')):
                self.assertEqual(self.call(*args).exit_code, 2)
            self.config('[tool.mcpywrap.server]\nport=123\n')
            self.assertEqual(self.call('run').exit_code, 1)
            self.config('broken = [')
            self.assertEqual(self.call('run').exit_code, 1)
            local.assert_not_called()
            launch.assert_not_called()
        self.assertFalse((self.project / '.runtime').exists())

    def test_gui_and_stale_worker_guard(self):
        self.config()
        ui = importlib.import_module('mcpywrap.commands.ui_cmd')
        with patch.object(ui, 'non_interactive', return_value=False):
            result = self.runner.invoke(cli, ['--project', str(self.project), 'ui'])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn('mcpy run', result.output)
        run = importlib.import_module('mcpywrap.commands.run_cmd')
        with self.assertRaisesRegex(ValueError, '服务器目标'):
            run._run_game_with_instance(str(self.project / '.runtime/old.cppconfig'), 'old', [])

    def test_anonymous_config_does_not_inherit_identity(self):
        engine = Engine('game', '3.10.0.420447', 'engine', str(self.root), 'test')
        config = n.unauthenticated_config(engine, n.ServerTarget('localhost'))
        self.assertIsNone(config['world_info'])
        self.assertEqual(config['room_info']['token'], '')
        self.assertEqual(config['misc'], {'multiplayer_game_type': 100})
        self.assertNotIn('player_info', config)
        self.assertEqual(config['LocalComponentPathsDict'], {})

    def execute_fake(self, *, exit_code=0, interrupt=False, failed_start=False):
        directory = self.root / 'run output'
        directory.mkdir()
        process = Mock(pid=12345)
        process.poll.return_value = 0
        process.wait.return_value = exit_code
        if interrupt:
            process.poll.return_value = None
            process.wait.side_effect = [KeyboardInterrupt(), None]
        engine = Engine('game', '3.10.0.420447', 'engine', str(self.root), 'test')

        def launch(path, **kwargs):
            config = json.loads(Path(path).read_text(encoding='utf-8'))
            self.assertIsNone(config['world_info'])
            self.assertEqual(kwargs['logging_ip'], '127.0.0.1')
            Path(kwargs['output_path']).write_text('native engine output\n', encoding='utf-8')
            with socket.create_connection(('127.0.0.1', kwargs['logging_port']), timeout=2) as client:
                client.sendall('网络日志\n'.encode('utf-8'))
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not (directory / 'game.log').read_text(encoding='utf-8'):
                time.sleep(0.01)
            return False if failed_start else process

        with patch.object(n, 'is_windows', return_value=True), \
                patch.object(n, 'discover_engines', return_value=Mock(require_engine=lambda: engine)) as discover, \
                patch.object(n, 'require_resources'), \
                patch.object(n.tempfile, 'mkdtemp', return_value=str(directory)), \
                patch.object(n, 'open_game', side_effect=launch):
            try:
                result = n.run_network(n.ServerTarget('localhost'))
                self.assertFalse(result['connection_verified'])
                self.assertFalse(result['authenticated'])
            finally:
                self.assertFalse((directory / 'runtime.cppconfig').exists())
                self.assertEqual((directory / 'game.log').read_text(encoding='utf-8'), '网络日志\n')
                self.assertEqual((directory / 'engine.log').read_text(encoding='utf-8'), 'native engine output\n')
                self.assertFalse(discover.call_args.kwargs['read_project_config'])
                if interrupt:
                    process.terminate.assert_called_once()

    def test_listener_ready_and_cleanup(self):
        with patch.object(n.click, 'echo') as output:
            self.execute_fake()
        self.assertTrue(any('native engine output' in str(c) for c in output.call_args_list))
        self.assertTrue(any('网络日志' in str(c) for c in output.call_args_list))

    def test_cli_nonzero_exit_and_structured_result(self):
        import click
        failure = click.ClickException('game exited 7')
        failure.exit_code = 7
        with patch('mcpywrap.commands.connect_cmd.run_network', side_effect=failure):
            result = self.call('connect', 'localhost')
        self.assertEqual(result.exit_code, 7)
        self.assertFalse(json.loads(result.stdout)['ok'])

    def test_interrupt_stops_only_owned_process(self):
        with self.assertRaises(KeyboardInterrupt):
            self.execute_fake(interrupt=True)

    def test_nonzero_and_failed_start(self):
        import click
        with self.assertRaises(click.ClickException) as raised:
            self.execute_fake(exit_code=7)
        self.assertEqual(raised.exception.exit_code, 7)

    def test_failed_start_cleanup(self):
        import click
        with self.assertRaises(click.ClickException):
            self.execute_fake(failed_start=True)

    def test_engine_validation_precedes_writes(self):
        with patch.object(n, 'is_windows', return_value=True), \
                patch.object(n, 'discover_engines', side_effect=ValueError('missing engine')), \
                patch.object(n.tempfile, 'mkdtemp') as create, patch.object(n, 'open_game') as launch:
            with self.assertRaises(ValueError):
                n.run_network(n.ServerTarget('localhost'))
            create.assert_not_called()
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()

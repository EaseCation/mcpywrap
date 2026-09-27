"""Network sessions use the same public process identity and lifecycle as local worlds."""
from dataclasses import asdict
import importlib.util
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from click.testing import CliRunner
from mcpywrap.cli import cli
from mcpywrap.command_context import project_scope
from mcpywrap.mcstudio import network, sessions
from mcpywrap.mcstudio.discovery import Engine


class NetworkSessions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()/'中文 项目'
        self.root.mkdir()
        self.engine = Engine('Minecraft.Windows.exe', '3.10', 'engine', str(self.root), 'test')
        self.data = {'session': 'a'*32, 'project': str(self.root), 'mode': 'network',
                     'state': 'running', 'mcs_auth': False,
                     'game': {'pid': 123, 'created_at': 100, 'executable': 'Minecraft.Windows.exe'},
                     'log_path': str(self.root/'game.log'), 'engine_log_path': str(self.root/'engine.log'),
                     'network': {'target': asdict(network.ServerTarget('localhost')), 'engine': asdict(self.engine)}}
        options = {'mix_stderr': False} if 'mix_stderr' in inspect.signature(CliRunner).parameters else {}
        self.runner = CliRunner(**options)
        self.discovery = patch.object(network, 'discover_engines', return_value=Mock(require_engine=lambda: self.engine)).start()
        patch.object(network, 'is_windows', return_value=True).start()
        patch.object(network, 'require_resources').start()
        self.start = patch.object(sessions, 'start', return_value=self.data).start()
        self.addCleanup(patch.stopall)

    def call(self, *args):
        return self.runner.invoke(cli, ['--project', str(self.root), '--non-interactive', *args, '--json'])

    def test_detached_connect_ignores_config_and_returns_window_identity(self):
        (self.root/'pyproject.toml').write_text('broken = [')
        result = self.call('connect', 'localhost', '--detach')
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.stdout)
        for key in ('session', 'project', 'log_path', 'engine_log_path'):
            self.assertEqual(data[key], self.data[key])
        for key, value in self.data['game'].items():
            self.assertEqual(data[key], value)
        self.assertFalse(data['connection_verified'])
        self.assertEqual(self.start.call_args.args[0], self.root)
        self.assertFalse(self.discovery.call_args.kwargs['read_project_config'])
        self.assertFalse((self.root/'.runtime').exists())  # mocked worker, no world side effects
        # Existing screenshot/input script accepts network status without an arbitrary PID bypass.
        path = Path(__file__).resolve().parents[1]/'skills/mcpywrap/scripts/game_window.py'
        spec = importlib.util.spec_from_file_location('network_window_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.object(module.subprocess, 'run', return_value=Mock(returncode=0, stdout=json.dumps({'ok': True, **self.data}))):
            self.assertEqual(module.load_session('mcpy', self.root, data['session']), self.data['game'])

    def test_configured_network_uses_same_session(self):
        (self.root/'pyproject.toml').write_text('[tool.mcpywrap.server]\nhost="localhost"\n')
        result = self.call('run', '--detach')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.stdout)['mode'], 'network')
        self.assertTrue(self.discovery.call_args.kwargs['read_project_config'])
        self.assertEqual(self.start.call_args.kwargs['network']['engine'], asdict(self.engine))

    def test_json_without_detach_fails_before_discovery_or_identity(self):
        with patch('mcpywrap.mcstudio.mcs_auth.acquire_identity') as acquire:
            result = self.call('connect', 'localhost', '--mcs-auth')
        self.assertEqual(result.exit_code, 2)
        self.assertFalse(json.loads(result.stdout)['ok'])
        self.start.assert_not_called()
        self.discovery.assert_not_called()
        acquire.assert_not_called()

    def test_frontend_interrupt_stops_only_owned_session(self):
        with project_scope(self.root), patch.object(sessions, 'read', side_effect=KeyboardInterrupt), \
                patch.object(sessions, 'stop') as stop:
            with self.assertRaises(KeyboardInterrupt):
                network.run_network(network.ServerTarget('localhost'))
            stop.assert_called_once_with(self.root, self.data['session'])

    def test_frontend_nonzero_exit_is_execution_failure(self):
        import click
        with project_scope(self.root), patch.object(sessions, 'read', return_value={'state': 'exited', 'exit_code': 7}):
            with self.assertRaises(click.ClickException) as error:
                network.run_network(network.ServerTarget('localhost'))
        self.assertEqual(error.exception.exit_code, 1)

    def test_start_failure_does_not_return_handoff(self):
        self.start.side_effect = ValueError('启动等待超时')
        result = self.call('connect', 'localhost', '--detach')
        self.assertEqual(result.exit_code, 1)
        self.assertNotIn('pid', json.loads(result.stdout))


if __name__ == '__main__':
    unittest.main()

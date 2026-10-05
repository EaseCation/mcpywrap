"""Backend contracts, setup behavior and platform selection without a real game."""
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from click.testing import CliRunner

from mcpywrap.cli import cli
from mcpywrap.engines.backend import GameBackend, LaunchedGame, get_backend
from mcpywrap.engines.host import EngineError, describe
from mcpywrap.engines.macos import MacOSBackend
from mcpywrap.engines.windows import WindowsBackend


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root/'pyproject.toml').write_text('[project]\nname="test"\nversion="0.0.0"\n[tool.mcpywrap]\nproject_type="addon"\n')
        self.env = patch.dict(os.environ, {'MCPY_ENGINE_HOME': str(self.root/'engine'), 'MCPY_RUNTIME_CATALOG': ''})
        self.env.start(); self.addCleanup(self.env.stop)
        self.runner = CliRunner()

    def call(self, *args):
        return self.runner.invoke(cli, ['--project', str(self.root), '--local', '--non-interactive', *args, '--json'])

    def test_single_selection_point_and_explicit_resume(self):
        for selected, expected in [('windows', WindowsBackend), ('macos-arm64', MacOSBackend), (None, GameBackend)]:
            with patch('mcpywrap.engines.backend.describe', return_value={'backend': selected}):
                self.assertIsInstance(get_backend(), expected)
                self.assertIsInstance(get_backend('windows'), WindowsBackend)
        with self.assertRaises(EngineError): get_backend('bogus')

    def test_rosetta_uses_native_backend_and_intel_does_not(self):
        with patch('mcpywrap.engines.host.sys.platform', 'darwin'), patch('platform.machine', return_value='x86_64'), \
                patch('subprocess.check_output', return_value='1\n'):
            self.assertEqual(describe()['backend'], 'macos-arm64')
            self.assertTrue(describe()['translated_python'])
        with patch('mcpywrap.engines.host.sys.platform', 'darwin'), patch('platform.machine', return_value='x86_64'), \
                patch('subprocess.check_output', return_value='0\n'):
            self.assertIsNone(describe()['backend'])

    def test_cli_run_uses_identical_backend_contract(self):
        for backend in (WindowsBackend(), MacOSBackend()):
            with patch('mcpywrap.engines.backend.get_backend', return_value=backend), \
                    patch.object(backend, 'run', return_value={'session': 'a'*32}) as run:
                result = self.call('run', '--new', '--detach')
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(run.call_args.args, (str(self.root),))
                self.assertTrue(run.call_args.kwargs['new'])
                self.assertTrue(run.call_args.kwargs['detach'])

    def test_setup_missing_is_structured_and_does_not_prompt(self):
        with patch('mcpywrap.engines.backend.get_backend', return_value=MacOSBackend()), \
                patch('mcpywrap.engines.macos.require_macos'), patch('click.prompt', side_effect=AssertionError('prompt')):
            result = self.call('run', '--detach')
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual(json.loads(result.stdout)['code'], 'setup_required')
        self.assertFalse((self.root/'engine').exists())

    def test_engine_doctor_never_routes_remote_or_creates_files(self):
        backend = GameBackend()
        with patch('mcpywrap.engines.backend.get_backend', return_value=backend), \
                patch('mcpywrap.remote.client.routed_command', side_effect=AssertionError('remote')):
            result = self.call('engine', 'doctor')
        self.assertEqual(result.exit_code, 1)
        self.assertFalse((self.root/'engine').exists())

    def test_windows_install_explains_studio_instead_of_downloading_apk(self):
        with patch('mcpywrap.commands.engine_cmd.get_backend', return_value=WindowsBackend()):
            result = self.call('engine', 'install')
        self.assertEqual(result.exit_code, 1)
        self.assertIn('MC Studio', json.loads(result.stdout)['hint'])

    def test_wizard_uses_backend_and_passes_choices(self):
        command = importlib.import_module('mcpywrap.commands.engine_cmd')
        backend = Mock(managed_install=True, setup_description='fixture')
        backend.diagnose.return_value = {'ok': False}
        backend.installation_choice.return_value = 'fixture/3.9'
        with patch.object(command, 'get_backend', return_value=backend), \
                patch.object(command, 'human_interaction', return_value=True), \
                patch('click.prompt', side_effect=['2', '/fixture.apk']), patch('click.confirm', return_value=True):
            command.setup_wizard()
        self.assertEqual(backend.install.call_args.args[:2], (None, '/fixture.apk'))

    def test_startup_failures_are_not_reported_as_ready(self):
        path = self.root/'engine.log'
        path.write_text('')
        path.with_name('commands.json').write_text('[{}]')
        channel = Mock()
        channel._rpc.return_value = {'state': 'failed', 'error': 'unknown request'}
        self.assertFalse(MacOSBackend().refresh({'engine_log_path': str(path)}, channel))
        channel._rpc.return_value = {'state': 'failed', 'error': 'recipe failed', 'request_id': 'startup-0'}
        with self.assertRaisesRegex(EngineError, 'recipe failed'):
            MacOSBackend().refresh({'engine_log_path': str(path)}, channel)

    def test_tui_interrupt_stops_owned_session(self):
        from mcpywrap.engines.tui import watch_session
        from mcpywrap.mcstudio import sessions
        record = {'state': 'exited', 'backend': 'macos-arm64'}
        with patch.object(sessions, 'read', side_effect=[KeyboardInterrupt(), record]), \
                patch.object(sessions, 'stop') as stop:
            result = watch_session(self.root, 'a'*32)
        stop.assert_called_once_with(self.root, 'a'*32)
        self.assertEqual(result['state'], 'exited')


if __name__ == '__main__': unittest.main()

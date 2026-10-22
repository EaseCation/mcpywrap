"""macOS network entry points preserve common sessions and reject unsupported modes."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from click.testing import CliRunner

from mcpywrap_core.cli import cli
from mcpywrap_core.engines.macos import MacOSBackend
from mcpywrap_core.engines.host import EngineError
from mcpywrap_core.mcstudio import sessions
from mcpywrap_core.mcstudio.network import ServerTarget


class MacOSNetworkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.backend = MacOSBackend()
        self.state = {'runtime': str(self.root/'runtime'), 'game': str(self.root/'game'),
                      'profile': {'apk': {'version': '3.10'}}, 'network_connect_protocol': 1,
                      'background_window_protocol': 1}
        for name, value in [('mcpywrap_core.engines.backend.get_backend', self.backend),
                            ('mcpywrap_core.engines.macos.require_macos', {}),
                            ('mcpywrap_core.engines.macos_network.require_macos', {}),
                            ('mcpywrap_core.engines.macos.ensure_runtime', self.state),
                            ('mcpywrap_core.engines.macos.pinned_runtime', self.state),
                            ('mcpywrap_core.engines.install.home', self.root/'resources')]:
            obj = patch(name, return_value=value); obj.start(); self.addCleanup(obj.stop)
        obj = patch.object(sessions, 'start', side_effect=self.start)
        self.start_mock = obj.start(); self.addCleanup(obj.stop)

    def start(self, root, **options):
        return {'session': options['session_id'], 'project': str(root), 'state': 'running',
                'game': {'pid': 123}, 'log_path': 'game.log', 'engine_log_path': 'engine.log',
                'level_id': None, 'mode': 'network', 'mcs_auth': False, **options}

    def call(self, *args):
        return CliRunner().invoke(cli, ['--local', '--project', str(self.root), '--non-interactive', *args, '--json'])

    def test_network_launch_persists_prepared_phase_before_starting_game(self):
        data = {'session': 'a' * 32, 'project': str(self.root), 'mode': 'network',
                'launch': {'data': str(self.root/'data')}}
        path = sessions.session_path(self.root, data['session'])/'session.json'

        def launched(record):
            self.assertEqual(json.loads(path.read_text())['phase'], 'prepared')
            self.assertEqual(record['session'], data['session'])
            return Mock()

        with patch('mcpywrap_core.engines.preferences.NativePreferences'), \
                patch.object(sessions, 'require_launch_requested') as requested, \
                patch('mcpywrap_core.engines.macos.launch_session', side_effect=launched):
            self.backend.launch(data, None)
        requested.assert_called_once_with(data['project'], data['session'])

    def test_connect_does_not_read_project_or_create_world(self):
        (self.root/'pyproject.toml').write_text('broken = [')
        result = self.call('connect', 'localhost', '--port', '29132', '--detach')
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.stdout)
        self.assertEqual((data['mode'], data['host'], data['port']), ('network', 'localhost', 29132))
        self.assertFalse(data['connection_verified'])
        self.assertFalse(data['addons_assembled'])
        self.assertFalse((self.root/'.runtime/macos/instances').exists())
        self.assertIn(data['session'], self.start_mock.call_args.kwargs['launch']['data'])

    def test_old_background_runtime_rejected_but_explicit_foreground_still_works(self):
        self.state.pop('background_window_protocol')
        result = self.call('connect', 'localhost', '--detach')
        self.assertEqual(json.loads(result.stdout)['code'], 'background_window_unavailable')
        self.start_mock.assert_not_called()
        result = self.call('connect', 'localhost', '--detach', '--foreground')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(self.start_mock.call_args.kwargs['background'])

    def test_old_runtime_rejected_before_start(self):
        self.state.pop('network_connect_protocol')
        result = self.call('connect', 'localhost', '--detach')
        self.assertEqual(json.loads(result.stdout)['code'], 'runtime_incompatible')
        self.start_mock.assert_not_called()

    def test_dual_player_identity_requires_runtime_protocol(self):
        player = {'user_id': 1024, 'user_name': 'mcpy_player_one'}
        with self.assertRaises(EngineError) as error:
            self.backend.connect(ServerTarget('localhost'), project_dir=self.root, detach=True, player=player)
        self.assertEqual(error.exception.code, 'runtime_incompatible')
        self.start_mock.assert_not_called()
        self.state['developer_identity_protocol'] = 1
        self.backend.connect(ServerTarget('localhost'), project_dir=self.root, detach=True, player=player)
        self.assertEqual(self.start_mock.call_args.kwargs['network']['player'], player)

    def test_auth_and_version_rejected(self):
        for args, code in [(['--mcs-auth'], 'unsupported_option'), (['--engine-version', 'wrong'], 'engine_version_mismatch')]:
            result = self.call('connect', 'localhost', '--detach', *args)
            self.assertEqual(json.loads(result.stdout)['code'], code)
        self.start_mock.assert_not_called()

    def test_json_requires_detach(self):
        result = self.call('connect', 'localhost')
        self.assertEqual(result.exit_code, 2)
        self.start_mock.assert_not_called()

    def test_configured_run_and_world_flags(self):
        (self.root/'pyproject.toml').write_text('[project]\nname="network-test"\nversion="0.0.0"\n[tool.mcpywrap.server]\nhost="localhost"\nport=29132\n')
        with patch('mcpywrap_core.mcstudio.network.prepare_project', return_value=[]):
            result = self.call('run', '--no-gui', '--detach')
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(json.loads(result.stdout)['mode'], 'network')
            self.start_mock.reset_mock()
            result = self.call('run', '--new', '--detach')
            self.assertEqual(result.exit_code, 2, result.output)
            self.start_mock.assert_not_called()
            result = self.call('run', '--list')
            self.assertEqual(json.loads(result.stdout)['instances'], [])

    def test_connect_installs_missing_resources_once(self):
        with patch('mcpywrap_core.engines.macos.ensure_runtime', side_effect=[EngineError('missing', 'setup_required'), self.state]), \
                patch('mcpywrap_core.commands.engine_cmd.perform_install') as install:
            result = self.call('connect', 'localhost', '--detach')
        self.assertEqual(result.exit_code, 0, result.output)
        install.assert_called_once()

    def test_ready_requires_hud_and_failure_times_out(self):
        log = self.root/'engine.log'; log.write_text('connecting')
        data = {'mode': 'network', 'engine_log_path': str(log), 'created_at': time.time()-91}
        with self.assertRaises(EngineError) as error:
            self.backend.refresh(data, Mock())
        self.assertEqual(error.exception.code, 'connection_timeout')
        self.assertFalse(data.get('connection_verified'))
        self.backend._next_probe = 0
        log.write_text('{"top_screen":"hud_screen"}')
        self.assertTrue(self.backend.refresh(data, Mock()))
        self.assertTrue(data['connection_verified'])

    def test_worker_rejects_server_execution_and_reload(self):
        from mcpywrap_core.mcstudio.runtime_debug import RuntimeControlServer, recv_exact
        import socket, struct
        channel = Mock()
        server = RuntimeControlServer(channel, 'test', mode='network'); server.start()
        try:
            for action, side in [('execute', 'server'), ('reload', 'client')]:
                with socket.create_connection(server.server_address) as client:
                    payload = json.dumps({'token':'test','action':action,'side':side,'code':'1+1'}).encode()
                    client.sendall(struct.pack('!I',len(payload))+payload)
                    size=struct.unpack('!I',recv_exact(client,4))[0]
                    result=json.loads(recv_exact(client,size))
                    self.assertEqual(result['state'],'failed')
            channel.execute.assert_not_called()
        finally: server.close()


if __name__ == '__main__': unittest.main()

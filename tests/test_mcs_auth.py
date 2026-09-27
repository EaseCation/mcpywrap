"""Identity routing and credential-safe logging; no real process injection."""
from contextlib import nullcontext
import inspect
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from click.testing import CliRunner

from mcpywrap.cli import cli
from mcpywrap.mcstudio import mcs_auth as auth, network
from mcpywrap.mcstudio.discovery import Engine
from mcpywrap.mcstudio.private_logs import Redactor, RedactedDecoder, EngineLogCapture


def snapshot():
    return {'schema_version': 1, 'mcs_pid': 123,
            'token': 'ABEiM0RVZneImaq7zN3u/w==',
            'player_info': {'user_id': '456789', 'user_name': '测试昵称', 'urs': 'fixture-account'},
            'auth_server_url': 'https://auth.example.invalid',
            'web_server_url': 'https://web.example.invalid',
            'core_server_url': 'https://core.example.invalid:8443'}


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        options = {'mix_stderr': False} if 'mix_stderr' in inspect.signature(CliRunner).parameters else {}
        self.runner = CliRunner(**options)

    def test_context_validation_and_no_credentials_in_repr_or_errors(self):
        context = auth.AuthContext.parse(snapshot(), 123)
        self.assertNotIn(context.token, repr(context))
        config = {'room_info': {}, 'misc': {}}
        context.apply(config)
        self.assertEqual(config['room_info']['token'], context.token)
        for key, value in (('token', 'PRIVATE-invalid'), ('mcs_pid', 99), ('schema_version', 9),
                           ('player_info', {}), ('auth_server_url', 'https://user:PRIVATE@example.com')):
            with self.subTest(key=key):
                data = snapshot(); data[key] = value
                with self.assertRaises(auth.AuthError) as error:
                    auth.AuthContext.parse(data, 123)
                self.assertNotIn('PRIVATE', str(error.exception))

    def test_redaction_for_every_chunk_boundary(self):
        context = auth.AuthContext.parse(snapshot(), 123)
        text = 'prefix '+context.token+' '+context.player_info['user_name']+' suffix'
        expected = 'prefix <redacted> <redacted> suffix'
        for offset in range(len(text)+1):
            redact = Redactor(context.secrets())
            self.assertEqual(redact.feed(text[:offset])+redact.feed(text[offset:], final=True), expected)
        raw = (text+'\n').encode('utf-8')
        for offset in range(len(raw)+1):
            decoder = RedactedDecoder(context.secrets())
            output = decoder.feed(raw[:offset])+decoder.feed(raw[offset:])+decoder.finish()
            self.assertNotIn(context.token, output)
            self.assertNotIn(context.player_info['user_name'], output)

    def test_engine_capture_redacts_before_persistence(self):
        context = auth.AuthContext.parse(snapshot(), 123)
        path = self.root/'engine.log'
        capture = EngineLogCapture(io.BytesIO(('token='+context.token).encode()), path, context.secrets())
        capture.close()
        self.assertEqual(path.read_text(), 'token=<redacted>')

    def test_explicit_auth_routing(self):
        with patch('mcpywrap.commands.connect_cmd.run_network', return_value={}) as launch:
            result = self.runner.invoke(cli, ['connect', 'localhost', '--mcs-auth'])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(launch.call_args.args[0].auth, 'mcs')
        config = self.root/'pyproject.toml'
        config.write_text('[tool.mcpywrap.server]\nhost="localhost"\nauth="mcs"\n')
        with patch.object(network, 'run_network', return_value={}) as launch:
            result = self.runner.invoke(cli, ['--project', str(self.root), 'run'])
            self.assertEqual(result.exit_code, 1, result.output)
            launch.assert_not_called()
            config.write_text('[tool.mcpywrap.server]\nhost="localhost"\n')
            result = self.runner.invoke(cli, ['--project', str(self.root), 'run', '--mcs-auth'])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(launch.call_args.args[0].auth, 'mcs')
        config.write_text('[tool.mcpywrap]\n')
        # Single-player auth is now supported; validation still precedes identity access.
        with patch.object(auth, 'acquire_identity') as capture:
            result = self.runner.invoke(cli, ['--project', str(self.root), 'run', '--mcs-auth'])
            self.assertEqual(result.exit_code, 1)
            capture.assert_not_called()

    def test_capture_uses_one_shot_request_and_hides_failure_output(self):
        for name in ('Injector.exe', 'Loader.dll', 'McpyMcsAuth.dll'):
            (self.root/name).touch()
        process = Mock(pid=123)
        process.exe.return_value = 'C:/MCStudio/MCStudio.exe'
        process.create_time.return_value = 100
        process.is_running.return_value = True
        def invoke(*args, **kwargs):
            request = json.loads((self.root/'request.json').read_text())
            self.assertTrue(request['pipe'].startswith('mcpy-mcs-auth-'))
            self.assertNotIn('token', request)
            (self.root/'loader-status.txt').write_text('HRESULT=0x00000000; managed_result=0')
            return subprocess.CompletedProcess(args, 0, json.dumps(snapshot()).encode(), b'')
        with patch.dict(os.environ, {'MCPY_MCS_BRIDGE_DIR': str(self.root)}), \
                patch.object(auth, 'running_studio', return_value=process), \
                patch.object(auth, 'bridge_lock', return_value=nullcontext()), \
                patch.object(auth.subprocess, 'run', side_effect=invoke):
            self.assertEqual(auth.capture_identity().mcs_pid, 123)
        self.assertFalse((self.root/'request.json').exists())
        with patch.dict(os.environ, {'MCPY_MCS_BRIDGE_DIR': str(self.root)}), \
                patch.object(auth, 'running_studio', return_value=process), \
                patch.object(auth, 'bridge_lock', return_value=nullcontext()), \
                patch.object(auth.subprocess, 'run', return_value=Mock(returncode=1, stderr=b'PRIVATE')):
            with self.assertRaises(auth.AuthError) as error:
                auth.capture_identity()
        self.assertNotIn('PRIVATE', str(error.exception))
        self.assertFalse((self.root/'request.json').exists())

    def test_auth_failure_does_not_launch_or_write_config(self):
        engine = Engine('game', '3.10', 'engine', str(self.root), 'test')
        with patch.object(network, 'is_windows', return_value=True), \
                patch.object(network, 'discover_engines', return_value=Mock(require_engine=lambda: engine)), \
                patch.object(network, 'require_resources'), \
                patch.object(auth, 'capture_identity', side_effect=auth.AuthError('not logged in')), \
                patch.object(network, 'open_game') as launch, patch.object(network.tempfile, 'mkdtemp') as mkdir:
            with self.assertRaises(auth.AuthError):
                network.run_network(network.ServerTarget('localhost', auth='mcs'))
            launch.assert_not_called(); mkdir.assert_not_called()

    def test_authenticated_launch_uses_own_config_and_sanitized_logs(self):
        context = auth.AuthContext.parse(snapshot(), 123)
        engine = Engine('game', '3.10', 'engine', str(self.root), 'test')
        process = Mock(pid=777)
        process.wait.return_value = process.poll.return_value = 0
        process.stdout = io.BytesIO(('LoginToken: '+context.token).encode())
        def launch(path, **kwargs):
            config = json.loads(Path(path).read_text())
            self.assertIsNone(config['world_info'])
            self.assertEqual(config['room_info']['token'], context.token)
            self.assertEqual(config['room_info']['item_ids'], [config['misc']['game_id']])
            self.assertEqual(config['vip_using_mod'], [])
            self.assertTrue(kwargs['capture_output'])
            self.assertNotIn('output_path', kwargs)
            return process
        with patch.object(network, 'is_windows', return_value=True), \
                patch.object(network, 'discover_engines', return_value=Mock(require_engine=lambda: engine)), \
                patch.object(network, 'require_resources'), patch.object(auth, 'capture_identity', return_value=context), \
                patch.object(network.tempfile, 'mkdtemp', return_value=str(self.root)), \
                patch.object(network, 'open_game', side_effect=launch), patch.object(network.click, 'echo') as output:
            result = network.run_network(network.ServerTarget('localhost', auth='mcs'))
        self.assertTrue(result['identity_provided'])
        self.assertFalse(result['authenticated'])
        self.assertFalse((self.root/'runtime.cppconfig').exists())
        self.assertNotIn(context.token, (self.root/'engine.log').read_text())
        self.assertNotIn(context.token, str(output.call_args_list))


if __name__ == '__main__':
    unittest.main()

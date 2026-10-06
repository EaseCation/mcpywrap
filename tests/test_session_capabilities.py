"""会话契约不启动 GUI、不执行脚本，并与真实的重载限制一致。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner
from mcpywrap.cli import cli
from mcpywrap.mcstudio.session_capabilities import inspect_session


class SessionCapabilitiesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.control = {'token': 'private-token', 'port': 123, 'python_reload_sides': ['client', 'server']}
        self.data = {'state': 'running', 'mode': 'local', 'game': {'pid': 1}, 'worker': {'pid': 2}}

    def inspect(self):
        (self.root/'control.json').write_text(json.dumps(self.control))
        with patch('mcpywrap.mcstudio.sessions.read', return_value=self.data), \
                patch('mcpywrap.mcstudio.sessions.session_path', return_value=self.root), \
                patch('mcpywrap.mcstudio.session_capabilities.checked_process', return_value=True), \
                patch('mcpywrap.mcstudio.runtime_debug.control_request', side_effect=AssertionError('execute')):
            return inspect_session(self.root, 'a'*32)

    def test_both_backends_share_schema_without_exposing_transport_or_token(self):
        results = []
        for backend in ('windows', 'macos-arm64'):
            self.data['backend'] = backend
            self.control['client_python_queue'] = backend == 'macos-arm64'
            results.append(self.inspect())
        self.assertEqual(results[0].keys(), results[1].keys())
        for result in results:
            self.assertEqual(result['python']['sides'], ['client', 'server'])
            self.assertTrue(result['control']['available'])
            self.assertFalse(result['control']['gui_required'])
            self.assertTrue(result['control']['display_required'])
            self.assertNotIn('private-token', json.dumps(result))
        self.assertFalse(results[0]['python']['client_queue'])
        self.assertTrue(results[1]['python']['client_queue'])

    def test_pinned_macos_runtime_controls_ui_support(self):
        self.data.update(backend='macos-arm64', launch={'runtime': str(self.root), 'engine_version': '3.9.100.297020'})
        self.assertEqual(self.inspect()['reload']['ui']['state'], 'unsupported')
        metadata = self.root/'Contents/Resources/runtime.json'
        metadata.parent.mkdir(parents=True)
        metadata.write_text('{"json_ui_reload_protocol":1}')
        result = self.inspect()
        self.assertEqual(result['reload']['ui']['state'], 'available')
        self.assertEqual(result['reload']['material']['state'], 'unsupported')
        self.assertFalse(result['reload']['ui']['effect_verified'])

    def test_windows_shader_restriction_and_closed_worker(self):
        self.data.update(backend='windows', launch={'engine_version': '3.10.0.420447'})
        self.assertEqual(self.inspect()['reload']['shader']['state'], 'unsupported')
        self.data['state'] = 'exited'
        result = self.inspect()
        self.assertFalse(result['control']['available'])
        self.assertEqual(result['python']['sides'], [])
        self.assertEqual(result['reload']['ui']['state'], 'unavailable')

    def test_network_has_no_server_or_reload(self):
        self.data.update(backend='windows', mode='network')
        result = self.inspect()
        self.assertEqual(result['python']['sides'], ['client'])
        self.assertEqual(result['python']['reload_sides'], [])
        self.assertTrue(all(v['state'] == 'unsupported' for v in result['reload'].values()))

    def test_remote_optional_commands_never_fall_back_or_send_code(self):
        for args in (['capabilities'], ['py-result', 'b'*32],
                     ['py', '--code', 'side_effect()', '--no-wait'],
                     ['py', '--code', 'side_effect()', '--wait-until', 'True']):
            with patch('mcpywrap.mcstudio.sessions.read', side_effect=AssertionError('local read')), \
                    patch('mcpywrap.remote.client.Client.request', side_effect=AssertionError('remote send')):
                result = CliRunner().invoke(cli, ['--project', str(self.root), '--remote', 'http://localhost:1',
                    '--non-interactive', 'runtime', *args, '--session', 'a'*32, '--json'])
            self.assertEqual(result.exit_code, 2, result.output)
            self.assertFalse(json.loads(result.stdout)['ok'])


if __name__ == '__main__': unittest.main()

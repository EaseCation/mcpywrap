"""Only the optional runner's host transport/opt-in guards; never launch a game."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent/'manual/runtime_controls'
spec = importlib.util.spec_from_file_location('manual_transport', ROOT/'support.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


def response(data, code=0):
    return subprocess.CompletedProcess([], code, json.dumps(data), '')


class OptionalManualTests(unittest.TestCase):
    def command(self, *operation):
        return [sys.executable, '-m', 'mcpywrap', '--local', '--project', '/fixture',
                'runtime', *operation, '--session', 'a'*32, '--json']

    def test_queued_ui_result_is_queried_without_resending_click(self):
        command = self.command('ui', 'click', '2', '--snapshot', 'snapshot', '--request-id', 'action')
        results = [response({'ok': False, 'runtime_state': 'queued', 'request_id': 'python-request'}, 1),
                   response({'ok': False, 'state': 'running', 'request_id': 'python-request'}, 1),
                   response({'ok': True, 'state': 'completed', 'side': 'client',
                             'value': {'ok': True, 'state': 'pending', 'id': 'action'}})]
        with patch.object(transport.subprocess, 'run', side_effect=results) as run, \
                patch.object(transport.time, 'sleep'):
            result, code = transport.invoke_json(command)
        self.assertEqual(code, 0)
        self.assertEqual(result['state'], 'pending')
        self.assertEqual(result['id'], 'action')
        self.assertEqual(run.call_args_list[0].args[0], command)
        for call in run.call_args_list[1:]:
            self.assertIn('py-result', call.args[0])
            self.assertIn('python-request', call.args[0])
            self.assertNotIn('click', call.args[0])

    def test_queued_player_install_keeps_player_capability_shape(self):
        with patch.object(transport.subprocess, 'run', side_effect=[
                response({'runtime_state': 'queued', 'request_id': 'request'}, 1),
                response({'ok': True, 'state': 'completed', 'side': 'client', 'value': {
                    'ok': True, 'capabilities': {'click': True}, 'player_capabilities': {'eat': True}}})]), \
                patch.object(transport.time, 'sleep'):
            result, code = transport.invoke_json(self.command('install'))
        self.assertEqual(result['capabilities'], {'eat': True})
        self.assertEqual(result['alias'], 'mcpy.player')
        self.assertEqual(code, 0)

    def test_unknown_result_never_resubmits_or_polls_as_completed(self):
        with patch.object(transport.subprocess, 'run', return_value=response({
                'ok': False, 'runtime_state': 'unknown', 'request_id': 'request'}, 1)) as run:
            result, code = transport.invoke_json(self.command('player', 'attack'))
        self.assertEqual(run.call_count, 1)
        self.assertEqual(code, 1)
        self.assertEqual(result['runtime_state'], 'unknown')

    def test_queued_ui_wrong_side_is_rejected(self):
        with patch.object(transport.subprocess, 'run', side_effect=[
                response({'runtime_state': 'queued', 'request_id': 'request'}, 1),
                response({'ok': True, 'state': 'completed', 'side': 'server', 'value': {'ok': True}})]), \
                patch.object(transport.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'incompatible'):
                transport.invoke_json(self.command('ui', 'snapshot'))

    def test_world_mutations_require_explicit_fixture_flag_before_cli_calls(self):
        result = subprocess.run([sys.executable, str(ROOT/'run.py'), '--project', '/unused',
                                 '--launch', '--suite', 'all'], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b'--prepare-fixture', result.stderr)


if __name__ == '__main__':
    unittest.main()

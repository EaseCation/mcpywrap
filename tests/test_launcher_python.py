import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from mcpywrap.mcstudio.launcher_python import LauncherPythonChannel
from mcpywrap.mcstudio.runtime_debug import RuntimeControlServer, control_request


class LauncherPythonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.safaia = Mock(pending=None)
        self.channel = LauncherPythonChannel(self.safaia, self.root)
        self.channel.pid = 123
        self.channel.metadata.write_text('{}')

    def test_server_uses_safaia_without_native_rpc(self):
        self.safaia.execute.return_value = {'state': 'completed', 'side': 'server', 'value': 3}
        with patch.object(self.channel, '_rpc') as native:
            result = self.channel.execute('1 + 2', side='server')
        native.assert_not_called()
        self.safaia.execute.assert_called_once_with('1 + 2', 'server', 12)
        self.assertEqual(result['value'], 3)

    def test_lost_submission_returns_recoverable_id_without_retry(self):
        with patch.object(self.channel, '_rpc', side_effect=TimeoutError('lost response')) as rpc:
            result = self.channel.submit('counter += 1', request_id='a' * 32)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['request_id'], 'a' * 32)
        self.assertEqual(rpc.call_count, 1)

    def test_false_and_null_values_are_completed_results(self):
        for value in (False, None, 0):
            result = self.channel._normalize({'state': 'completed', 'request_id': 'b' * 32,
                'value': {'value': value, 'stdout': '', 'stderr': '', 'error': None}})
            self.assertEqual(result['state'], 'completed')
            self.assertIs(result['value'], value)

    def test_query_and_cancel_do_not_submit_code(self):
        with patch.object(self.channel, '_rpc', return_value={'state': 'cancelled', 'request_id': 'c' * 32}) as rpc:
            self.channel.request('c' * 32, cancel=True)
        rpc.assert_called_once_with('cancel', {'request_id': 'c' * 32})

    def test_history_cleanup_failure_preserves_confirmed_result(self):
        self.channel.finished.extend(str(i) for i in range(64))
        result = {'state': 'completed', 'request_id': 'new', 'value': 42}
        with patch.object(self.channel, '_rpc', side_effect=ConnectionError('closed')):
            self.assertEqual(self.channel._remember(result), result)
        self.assertEqual(self.channel.finished[0], '0')

    def test_wrong_process_metadata_rejected_before_connect(self):
        self.channel.metadata.write_text(json.dumps({'protocol': 1, 'pid': 999, 'socket': '/tmp/unused'}))
        self.channel.metadata.chmod(0o600)
        with patch('mcpywrap.mcstudio.launcher_python.socket.socket') as connect:
            with self.assertRaisesRegex(ValueError, '不属于当前游戏进程'):
                self.channel.status()
        connect.assert_not_called()

    def test_queue_actions_use_existing_authenticated_control_transport(self):
        fake = Mock()
        fake.submit.return_value = {'state': 'queued', 'request_id': 'd' * 32, 'side': 'client'}
        fake.request.return_value = {'state': 'completed', 'request_id': 'd' * 32, 'value': 42}
        server = RuntimeControlServer(fake, 'test-token')
        server.start()
        self.addCleanup(server.close)
        (self.root / 'control.json').write_text(json.dumps({'port': server.server_address[1], 'token': 'test-token'}))
        with patch('mcpywrap.mcstudio.sessions.session_path', return_value=self.root), \
             patch('mcpywrap.mcstudio.sessions.read', return_value={'state': 'running', 'worker': {'pid': 1}}), \
             patch('mcpywrap.mcstudio.processes.checked_process', return_value=True):
            first = control_request('.', 'e' * 32, 'submit', code='answer = 42', side='client', condition='True')
            second = control_request('.', 'e' * 32, 'python-result', request_id=first['request_id'])
        fake.submit.assert_called_once_with('answer = 42', 'True', None)
        fake.request.assert_called_once_with('d' * 32, cancel=False)
        self.assertEqual(second['value'], 42)


if __name__ == '__main__':
    unittest.main()

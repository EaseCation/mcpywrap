"""Real loopback HTTP and CLI routing; simulated games, no desktop input or authentication."""
import inspect
import json
import os
import socket
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from click.testing import CliRunner
from mcpywrap.cli import cli
from mcpywrap.remote import service as api
from mcpywrap.remote.client import Client
from mcpywrap.remote.http_server import GameHTTPServer
from mcpywrap.mcstudio import sessions, window
from mcpywrap.mcstudio.discovery import Engine


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.local = self.root/'mac 中文 project'
        self.local.mkdir()
        self.service = api.GameService(self.root/'Windows data')
        self.info = {'protocol_version': 1, 'version': 'fixture', 'capabilities': api.ACTIONS+['mcs-auth'],
                     'desktop': {'available': True}, 'mcs_auth': {'component_available': True}}
        self.addCleanup(patch.stopall)
        patch.object(api, 'capabilities', side_effect=lambda: dict(self.info)).start()
        self.prepare = patch.object(api, 'prepare_network', return_value=(
            Engine('Minecraft.Windows.exe', '3.10', 'engine', 'download', 'test'), None)).start()
        self.live = set()
        def checked(record):
            return Mock() if record['pid'] in self.live else None
        patch.object(api, 'checked_process', side_effect=checked).start()
        patch.object(sessions, 'checked_process', side_effect=checked).start()
        self.start = patch.object(sessions, 'start', side_effect=self.fake_start).start()
        self.stop = patch.object(sessions, 'stop', side_effect=self.fake_stop).start()
        self.http = GameHTTPServer(('127.0.0.1', 0), self.service)
        self.thread = threading.Thread(target=self.http.serve_forever, kwargs={'poll_interval': .01})
        self.thread.start()
        self.addCleanup(self.shutdown)
        self.url = 'http://127.0.0.1:'+str(self.http.server_port)
        self.client = Client(self.url, self.local)
        options = {'mix_stderr': False} if 'mix_stderr' in inspect.signature(CliRunner).parameters else {}
        self.runner = CliRunner(**options)

    def shutdown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)

    def fake_start(self, root, **kwargs):
        session = kwargs['session_id']
        path = sessions.session_path(root, session)
        path.mkdir(parents=True)
        data = {'session': session, 'project': str(root), 'origin': kwargs['origin'],
                'request_id': kwargs['request_id'], 'state': 'running', 'mode': 'network',
                'game': {'pid': 71, 'created_at': 1, 'executable': 'Minecraft.Windows.exe'},
                'worker': {'pid': 72}, 'network': kwargs['network'], 'mcs_auth': kwargs['auth_context'] is not None,
                'log_path': str(path/'game.log'), 'engine_log_path': str(path/'engine.log')}
        self.live.update((71, 72))
        sessions.save(path/'session.json', data)
        for source in ('game', 'engine', 'worker'):
            (path/(source+'.log')).write_text(source+' 中文 已加载 😀\n', encoding='utf-8')
        return data

    def fake_stop(self, root, session):
        path = sessions.session_path(root, session)/'session.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        self.live.clear()
        data.update(state='exited', exit_code=0)
        sessions.save(path, data)
        return {'session': session, 'state': 'exited'}

    def create(self, session='a'*32, **kwargs):
        return self.client.request('POST', '/sessions', {'request_id': session, 'host': 'server.local', **kwargs})

    def call(self, *args, remote=True):
        flags = ['--remote', self.url] if remote else ['--local']
        return self.runner.invoke(cli, ['--project', str(self.local), '--non-interactive', *flags, *args, '--json'])

    def test_connect_status_logs_and_precise_stop_over_http(self):
        data = self.create(mcs_auth=True)
        self.assertEqual(data['project'], str(self.local))
        self.assertEqual(data['remote_project'], str(self.service.root))
        self.prepare.assert_called_once()
        self.assertIs(self.prepare.call_args.kwargs['interactive'], False)
        self.assertEqual(data['service_instance'], self.service.instance)
        self.assertFalse(data['connection_verified'])
        for source in ('game', 'engine', 'worker'):
            data = self.client.request('GET', '/sessions/'+'a'*32+'/logs?source='+source)
            self.assertIn(source+' 中文 已加载 😀', data['text'])
        self.assertEqual(self.client.request('GET', '/sessions')['sessions'][0]['session'], 'a'*32)
        self.client.request('POST', '/sessions/'+'a'*32+'/stop', {})
        self.client.request('POST', '/sessions/'+'a'*32+'/stop', {})
        self.assertFalse(self.live)

    def test_idempotency_conflict_and_busy(self):
        self.create()
        self.create()
        self.start.assert_called_once()
        for sid, host in (('a'*32, 'another.host'), ('b'*32, 'server.local')):
            with self.assertRaises(api.RemoteError) as error:
                self.client.request('POST', '/sessions', {'request_id': sid, 'host': host})
            self.assertEqual(error.exception.status, 409)

    def test_concurrent_creation_returns_busy_without_queue(self):
        self.service.create_lock.acquire()
        try:
            with self.assertRaises(api.RemoteError) as error:
                self.create()
            self.assertEqual(error.exception.code, 'busy')
        finally:
            self.service.create_lock.release()
        self.start.assert_not_called()

    def test_recovery_and_shutdown_do_not_touch_local_game(self):
        self.create()
        local = sessions.session_path(self.service.root, 'b'*32)
        local.mkdir(parents=True)
        sessions.save(local/'session.json', {'state': 'running', 'game': {'pid': 999}, 'origin': None})
        recovered = api.GameService(self.service.root)
        self.assertNotEqual(recovered.instance, self.service.instance)
        self.assertTrue(recovered.active())
        with self.assertRaises(api.RemoteError):
            recovered.record('b'*32)
        recovered.close()
        self.assertEqual([call.args[1] for call in self.stop.call_args_list], ['a'*32])

    def test_authentication_optional_and_wrong_token(self):
        self.client.require('doctor')
        self.http.token = 'fixture-token'
        for token in (None, 'incorrect'):
            with self.assertRaises(api.RemoteError) as error:
                Client(self.url, self.local, token).require('doctor')
            self.assertEqual(error.exception.status, 401)
        Client(self.url, self.local, 'fixture-token').require('doctor')

    def test_missing_capability_and_protocol_no_launch(self):
        for key, value in (('capabilities', []), ('protocol_version', 99)):
            old = self.info[key]
            self.info[key] = value
            result = self.call('connect', 'server.local', '--detach')
            self.assertEqual(result.exit_code, 1, result.output)
            self.info[key] = old
        self.start.assert_not_called()

    def test_configured_run_and_project_commands_route_correctly(self):
        config = self.local/'pyproject.toml'
        config.write_text('[tool.mcpywrap]\nremote_url="'+self.url+'"\n[tool.mcpywrap.server]\nhost="server.local"\n')
        result = self.runner.invoke(cli, ['--project', str(self.local), 'run', '--detach', '--json'])
        self.assertEqual(result.exit_code, 0, result.output)
        for args in (('run', '--new', '--detach'), ('run', '--list'), ('connect', 'server.local')):
            self.assertEqual(self.call(*args).exit_code, 2)
        config.unlink()
        self.assertEqual(self.call('run', '--detach').exit_code, 2)
        result = self.call('init', '--name', 'demo', '--type', 'addon')
        self.assertEqual(result.exit_code, 0, result.output)
        result = self.call('package')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(Path(json.loads(result.stdout)['artifact']).is_file())
        self.assertEqual(self.start.call_count, 1)

    def test_local_switch_and_endpoint_precedence(self):
        from mcpywrap.mcstudio import diagnostics
        (self.local/'pyproject.toml').write_text('[tool.mcpywrap]\nremote_url="http://invalid.invalid:1"\n')
        with patch.dict(os.environ, {'MCPY_REMOTE': self.url}):
            result = self.runner.invoke(cli, ['--project', str(self.local), 'doctor', '--capabilities', '--json'])
            self.assertEqual(json.loads(result.stdout)['execution'], 'remote')
            with patch.object(diagnostics, 'diagnose', return_value={'ok': True}):
                self.assertEqual(self.call('doctor', remote=False).exit_code, 0)
        with patch.dict(os.environ, {'MCPY_REMOTE': 'http://invalid.invalid:1'}):
            self.assertEqual(self.call('doctor', '--capabilities').exit_code, 0)

    def test_screenshot_download_and_input_bound_to_session(self):
        self.create()
        image = window.png_bytes(1, 1, b'\x00\x00\xff\x00')
        with patch.object(window, 'operate', return_value={
                'content': image, 'width': 1, 'height': 1, 'session': 'a'*32,
                'capture': 'background-window', 'capture_fallback': False}) as action:
            output = self.local/'截图 😀.png'
            result = self.call('screenshot', '--session', 'a'*32, '--output', str(output))
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(output.read_bytes(), image)
            response = json.loads(result.stdout)
            self.assertEqual(Path(response['image']), output)
            self.assertEqual(response['capture'], 'background-window')
            self.assertFalse(response['capture_fallback'])
            self.assertNotEqual(self.call('screenshot', '--session', 'a'*32, '--output', str(output)).exit_code, 0)
            self.assertEqual(action.call_count, 1)
        with patch.object(window, 'operate', return_value={
                'content': image, 'width': 1, 'height': 1, 'session': 'a'*32,
                'capture': 'visible-client-area', 'capture_fallback': True,
                'capture_fallback_reason': '后台捕获返回全黑画面'}):
            output = self.local/'fallback.png'
            result = self.call('screenshot', '--session', 'a'*32, '--output', str(output))
            self.assertEqual(result.exit_code, 0, result.output)
            response = json.loads(result.stdout)
            self.assertEqual(response['capture'], 'visible-client-area')
            self.assertTrue(response['capture_fallback'])
            self.assertEqual(response['capture_fallback_reason'], '后台捕获返回全黑画面')
        with patch.object(window, 'operate', return_value={'sent': True, 'released': True, 'effect_verified': False}) as action:
            result = self.call('key', '--session', 'a'*32, 'SHIFT+W', '--hold-ms', '500')
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(action.call_args.args[1:4], ('a'*32, 'key', {'keys': ['SHIFT+W'], 'hold_ms': 500}))

    def test_window_actions_serialized_and_cancelled_at_shutdown(self):
        self.create()
        self.service.desktop_lock.acquire()
        try:
            with self.assertRaises(api.RemoteError) as error:
                self.client.request('POST', '/sessions/'+'a'*32+'/screenshot', {})
            self.assertEqual(error.exception.code, 'busy')
        finally:
            self.service.desktop_lock.release()
        self.service.close()
        self.assertTrue(self.service.action_cancel.is_set())

    def test_unknown_session_and_file_or_command_fields_rejected(self):
        self.create()
        cases = [('GET', '/sessions/'+'b'*32, None),
                 ('GET', '/sessions/'+'a'*32+'/logs?source=../../secret', None),
                 ('POST', '/sessions', {'request_id': 'b'*32, 'host': 'server.local', 'command': 'whoami'}),
                 ('POST', '/sessions/'+'a'*32+'/screenshot', {'output': 'C:/private'}),
                 ('POST', '/exec', {'command': 'whoami'})]
        for method, path, data in cases:
            with self.subTest(path=path), self.assertRaises(api.RemoteError):
                self.client.request(method, path, data)

    def test_start_failure_can_be_found_and_not_replayed(self):
        self.start.side_effect = ValueError('启动等待超时')
        with self.assertRaises(api.RemoteError):
            self.create()
        data = self.create()
        self.assertEqual(data['state'], 'failed')
        self.assertEqual(self.start.call_count, 1)
        self.assertEqual(self.client.request('GET', '/sessions')['sessions'][0]['state'], 'failed')

    def test_disconnected_start_is_retained_and_retrievable(self):
        entered, resume, finished = threading.Event(), threading.Event(), threading.Event()
        def start(root, **kwargs):
            entered.set()
            if not resume.wait(3):
                raise ValueError('test timed out')
            result = self.fake_start(root, **kwargs)
            finished.set()
            return result
        self.start.side_effect = start
        body = json.dumps({'request_id': 'a'*32, 'host': 'server.local'}).encode()
        with socket.create_connection(('127.0.0.1', self.http.server_port)) as sock:
            sock.sendall(b'POST /v1/sessions HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: '+
                         str(len(body)).encode()+b'\r\n\r\n'+body)
            self.assertTrue(entered.wait(3))
        resume.set()
        self.assertTrue(finished.wait(3))
        data = self.create()
        self.assertEqual(data['state'], 'running')
        self.start.assert_called_once()
        self.stop.assert_not_called()

    def test_close_cancels_inflight_preparation_before_launch(self):
        entered, resume = threading.Event(), threading.Event()
        prepared = self.prepare.return_value
        def prepare(*args, **kwargs):
            entered.set()
            resume.wait(3)
            return prepared
        self.prepare.side_effect = prepare
        errors = []
        def launch():
            try:
                self.create()
            except api.RemoteError as exc:
                errors.append(exc.code)
        caller = threading.Thread(target=launch)
        caller.start()
        self.assertTrue(entered.wait(3))
        closer = threading.Thread(target=self.service.close)
        closer.start()
        self.assertTrue(self.service.closing.wait(3))
        resume.set()
        caller.join(3); closer.join(3)
        self.assertFalse(caller.is_alive() or closer.is_alive())
        self.start.assert_not_called()
        self.assertEqual(errors, ['service_stopping'])

    def test_pid_reuse_prevents_stop_and_new_launch(self):
        self.create()
        with patch.object(sessions, 'checked_process', side_effect=ValueError('进程身份不匹配')):
            with self.assertRaises(api.RemoteError):
                self.client.request('POST', '/sessions/'+'a'*32+'/stop', {})
            with self.assertRaises(api.RemoteError):
                self.create('b'*32)
        self.stop.assert_not_called()
        self.assertEqual(self.start.call_count, 1)

    def test_unregistered_worker_reserves_slot_until_explicit_cancel(self):
        path = sessions.session_path(self.service.root, 'a'*32)
        path.mkdir(parents=True)
        sessions.save(path/'session.json', {'origin': 'remote', 'session': 'a'*32, 'state': 'starting',
                                           'game': None, 'worker': None})
        self.assertTrue(self.service.active())
        # Use the real stop implementation for the not-yet-registered worker case.
        with patch.object(sessions, 'stop', return_value={'session': 'a'*32, 'state': 'exited'}):
            self.service.stop('a'*32)
        self.assertTrue((path/'stop').is_file())
        self.assertFalse(self.service.active())

    def test_retired_pid_reuse_does_not_block_new_work_or_cleanup(self):
        self.create()
        self.fake_stop(self.service.root, 'a'*32)
        self.stop.reset_mock()
        with patch.object(api, 'checked_process', side_effect=ValueError('reused PID')):
            self.assertFalse(self.service.active())
            self.service.close()
        self.stop.assert_not_called()

    def test_unavailable_and_redirect_never_fall_back(self):
        with patch('mcpywrap.remote.client.Client.request', side_effect=api.RemoteError('offline', 'remote_unavailable')):
            result = self.call('connect', 'server.local', '--detach')
        self.assertEqual(result.exit_code, 1)
        self.start.assert_not_called()

    def test_directory_lock_exclusive(self):
        with api.directory_lock(self.root/'locked'):
            with self.assertRaises(api.RemoteError):
                with api.directory_lock(self.root/'locked'):
                    self.fail('second service acquired lock')

    @unittest.skipUnless(os.name == 'nt', 'Windows interactive service command')
    def test_serve_ctrl_c_always_closes_service(self):
        with patch('mcpywrap.remote.service.GameService') as service, \
                patch('mcpywrap.remote.http_server.GameHTTPServer') as server:
            http = server.return_value.__enter__.return_value
            http.token = None
            http.serve_forever.side_effect = KeyboardInterrupt
            result = self.runner.invoke(cli, ['--local', 'serve', '--data-dir', str(self.root/'console-service')])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(server.call_args.args[0], ('0.0.0.0', 18765))
        service.return_value.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()

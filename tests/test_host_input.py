"""Windows 同一状态机的设备适配与会话 worker 路由；不操作真实桌面。"""
import contextlib
import heapq
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.request import Request, urlopen
from unittest.mock import Mock, patch
from types import SimpleNamespace

from mcpywrap.input_executor import InputExecutor
from mcpywrap.input_plan import input_key_plan, normalize_input_plan, InputPlanError
from mcpywrap.mcstudio.host_input import WindowsInputAdapter, HostInputManager
from mcpywrap.mcstudio import window
from mcpywrap.mcstudio.unified_input import execute


class WindowsUnifiedTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.
        self.queue = []
        self.counter = 0
        self.manager = SimpleNamespace(project=Path('.'), session='a'*32, game=Mock(return_value={'ok': True}))
        self.adapter = WindowsInputAdapter(self.manager)
        self.adapter.clock = lambda: self.now
        self.manager.schedule = self.schedule
        self.control = InputExecutor(self.adapter)
        self.manager.executor = self.control
        self.target = window.GameWindow.__new__(window.GameWindow)
        self.target.foreground = Mock(); self.target.check_foreground = Mock(); self.target.close = Mock()
        self.target.client_area = Mock(return_value=(800, 600, SimpleNamespace(x=20, y=30)))
        self.target._client_area = Mock(side_effect=lambda **kwargs: self.target.client_area())
        self.target.game = {'pid': 123}
        self.target.owner = Mock(return_value=123)
        self.target.user = Mock()
        self.target.user.GetAsyncKeyState.return_value = 0
        self.target.user.MapVirtualKeyW.return_value = 87
        self.target.user.GetSystemMetrics.side_effect = {76: 0, 77: 0, 78: 1920, 79: 1080}.get
        def cursor(pointer):
            pointer._obj.x, pointer._obj.y = 30, 40
            return True
        self.target.user.GetCursorPos.side_effect = cursor
        self.sent = []
        def send(count, pointer, size):
            item = pointer._obj
            self.sent.append(('key', item.keyboard.vk, item.keyboard.flags) if item.kind == 1 else ('mouse', item.mouse.flags))
            return count
        self.target.user.SendInput.side_effect = send
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch('mcpywrap.mcstudio.host_input.os.name', 'nt'))
        self.stack.enter_context(patch('mcpywrap.mcstudio.window.session_game', return_value=self.target.game))
        self.stack.enter_context(patch('mcpywrap.mcstudio.window.GameWindow', return_value=self.target))
        self.stack.enter_context(patch('mcpywrap.mcstudio.window.desktop_input_lock', return_value=contextlib.nullcontext()))
        self.addCleanup(self.stack.close)

    def schedule(self, delay, callback):
        self.counter += 1
        heapq.heappush(self.queue, (self.now+delay, self.counter, callback))

    def advance(self, seconds):
        deadline = self.now+seconds
        count = 0
        while self.queue and self.queue[0][0] <= deadline:
            due, _, callback = heapq.heappop(self.queue)
            self.now = due; callback(); count += 1
            if count > 20000: raise AssertionError('loop')
        self.now = deadline

    def result(self, op): return self.control.status(op['operation_id'], True)

    def test_windows_key_preserves_explicit_order_and_actual_hold(self):
        recipe = input_key_plan('W+CTRL', 100); recipe['backend'] = 'windows-sendinput'
        op = self.control.run(recipe)
        self.advance(.2)
        result = self.result(op)
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(self.sent, [('key', 87, 0), ('key', 162, 0), ('key', 162, 2), ('key', 87, 2)])
        self.assertTrue(all(row['input_path'] == 'windows-sendinput' for row in result['events']))
        self.assertIn('send_started_ns', result['events'][0])
        self.target.foreground.assert_called_once()
        self.assertEqual(self.manager.game.call_args_list[0].args[0], '_reserve')
        self.assertEqual(self.manager.game.call_args_list[-1].args[0], '_unreserve')

    def test_pointer_and_keyboard_plan_share_order_and_cleanup(self):
        recipe = {'schema_version': 1, 'backend': 'windows-sendinput', 'width': 800, 'height': 600,
                  'steps': [{'action': 'key_down', 'key': 'CTRL'},
                            {'action': 'pointer.move', 'x': 10, 'y': 20},
                            {'action': 'pointer.down', 'button': 'right'},
                            {'action': 'wait', 'duration_ms': 100},
                            {'action': 'pointer.up', 'button': 'right'},
                            {'action': 'key_up', 'key': 'CTRL'}]}
        op = self.control.run(recipe)
        self.advance(.05)
        result = self.control.cancel(op['operation_id'])
        self.assertEqual(result['state'], 'cancelled')
        self.assertEqual(self.sent, [('key', 162, 0), ('mouse', 0xC001), ('mouse', 8), ('mouse', 16), ('key', 162, 2)])
        self.assertEqual([r['key'] for r in self.result(op)['cleanup_events']], ['right', 'CTRL'])

    def test_mixed_physical_representations_reject_before_foreground(self):
        op = self.control.run({'schema_version': 1, 'backend': 'windows-sendinput', 'steps': [
            {'action': 'key_down', 'key': 'W'}, {'action': 'key_up', 'key': 'W'},
            {'action': 'key_down', 'key': 'SC:0x11'}, {'action': 'key_up', 'key': 'SC:0x11'}]})
        self.advance(.1)
        self.assertEqual(self.result(op)['state'], 'failed')
        self.target.foreground.assert_not_called()
        self.assertFalse(self.sent)

    def test_release_failure_retains_window_and_reservation_until_retry(self):
        recipe = input_key_plan('W', 100); recipe['backend'] = 'windows-sendinput'
        op = self.control.run(recipe)
        self.advance(.05)
        self.target.user.SendInput.return_value = 0
        self.target.user.SendInput.side_effect = lambda *args: 0
        result = self.control.cancel(op['operation_id'])
        self.assertEqual(result['state'], 'unknown')
        self.target.close.assert_not_called()
        self.target.user.SendInput.side_effect = lambda count, *args: count
        self.assertTrue(self.control.stop()['ok'])
        self.target.close.assert_called_once()

    def test_foreground_or_preexisting_inputs_fail_without_new_edges(self):
        self.target.user.GetAsyncKeyState.return_value = 0x8000
        recipe = input_key_plan('W'); recipe['backend'] = 'windows-sendinput'
        op = self.control.run(recipe); self.advance(.1)
        self.assertEqual(self.result(op)['code'], 'input_busy')
        self.assertFalse(self.sent)


class UnifiedWorkerRoutingTests(unittest.TestCase):
    def test_http_input_endpoint_preserves_request_and_result(self):
        from mcpywrap.remote.http_server import GameHTTPServer
        service = Mock()
        service.instance = 'fixture'
        service.unified_input.return_value = {'ok': True, 'state': 'pending', 'operation_id': 'b'*32, 'request_id': 'b'*32}
        server = GameHTTPServer(('127.0.0.1', 0), service)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}); thread.start()
        try:
            data = {'method': 'run', 'parameters': {'plan': input_key_plan('W'), 'request_id': 'b'*32}}
            request = Request('http://127.0.0.1:'+str(server.server_port)+'/v1/sessions/'+'a'*32+'/input',
                data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'}, method='POST')
            with urlopen(request, timeout=3) as response:
                result = json.load(response)
            service.unified_input.assert_called_once_with('a'*32, data)
            self.assertEqual(result['operation_id'], 'b'*32)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)

    def test_worker_manager_read_only_and_cancel_dispatch(self):
        channel = Mock()
        channel.execute.return_value = {'state': 'completed', 'side': 'client', 'request_id': 'wire',
                                        'value': {'ok': True, 'actions': {}, 'active': None}}
        manager = HostInputManager(channel, Path('.'), 'a'*32)
        try:
            caps = manager.dispatch('capabilities', {})
            self.assertIn('windows-sendinput', caps['backends'])
            self.assertIn('game', caps['backends'])
            result = manager.dispatch('observe', {'view': 'player'})
            self.assertEqual(result['transport']['request_id'], 'wire')
            with self.assertRaises(InputPlanError): manager.dispatch('stop', {'bad': 1})
        finally: manager.close()

    def test_device_status_and_stop_work_without_game_runtime_install(self):
        channel = Mock()
        channel.execute.return_value = {'state': 'completed', 'side': 'client', 'request_id': 'wire',
                                        'value': {'ok': False, 'code': 'not_installed'}}
        manager = HostInputManager(channel, Path('.'), 'a'*32)
        try:
            status = manager.dispatch('status', {})
            self.assertTrue(status['ok'])
            self.assertFalse(status['game_installed'])
            self.assertTrue(manager.dispatch('stop', {})['ok'])
        finally: manager.close()

    def test_old_worker_windows_rejected_without_game_fallback(self):
        recipe = input_key_plan('W'); recipe['backend'] = 'windows-sendinput'
        with tempfile.TemporaryDirectory() as directory:
            with patch('mcpywrap.command_context.remote_url', return_value=None), \
                 patch('mcpywrap.mcstudio.runtime_ui.execute') as game:
                result = execute(Path(directory), 'a'*32, 'run', {'plan': recipe})
            self.assertEqual(result['code'], 'not_supported')
            game.assert_not_called()

    def test_remote_worker_receives_same_plan_once_no_device_on_caller(self):
        recipe = normalize_input_plan({'schema_version': 1, 'steps': [{'action': 'player.jump'}]})
        with patch('mcpywrap.command_context.remote_url', return_value='http://windows'), \
             patch('mcpywrap.remote.client.Client') as client:
            client.return_value.request.side_effect = [
                {'capabilities': ['unified-input']}, {'ok': True, 'state': 'pending', 'operation_id': 'b'*32, 'request_id': 'b'*32}]
            result = execute(Path('.'), 'a'*32, 'run', {'plan': recipe, 'request_id': 'b'*32})
        self.assertEqual(result['operation_id'], 'b'*32)
        args = client.return_value.request.call_args.args
        self.assertEqual(args[:2], ('POST', '/sessions/'+'a'*32+'/input'))
        self.assertEqual(args[2]['parameters']['plan'], recipe)


if __name__ == '__main__': unittest.main()

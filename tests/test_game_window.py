"""游戏窗口尺寸：参数校验、启动后应用、运行中调整、各平台系统 API 适配及重启/联调组/远程的传递。"""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from click.testing import CliRunner

from mcpywrap_core.cli import cli
from mcpywrap_core.engines.host import EngineError
from mcpywrap_core.mcstudio import sessions
from mcpywrap_core.mcstudio.network import ServerTarget
from mcpywrap_core.runtime import game_window, groups
from mcpywrap_core.runtime.game_window import (LaunchSizer, parse_size, requested_window_size,
                                               window_size_scope)


class SizeRules(unittest.TestCase):
    def test_parse_accepts_common_separators_and_rejects_out_of_range(self):
        self.assertEqual(parse_size('1280x720'), (1280, 720))
        self.assertEqual(parse_size(' 1920X1080 '), (1920, 1080))
        self.assertEqual(parse_size('800×600'), (800, 600))
        for value in ('1280', '1280*720', '0x0', '100x100', '9000x720', '1280x-720', 'axb', None):
            with self.subTest(value=value), self.assertRaises(ValueError) as error:
                parse_size(value)
            self.assertEqual(error.exception.code, 'invalid_size')

    def test_scope_is_nested_and_restored(self):
        self.assertIsNone(requested_window_size())
        with window_size_scope((1280, 720)):
            self.assertEqual(requested_window_size(), [1280, 720])
            with window_size_scope(None):
                self.assertIsNone(requested_window_size())
            self.assertEqual(requested_window_size(), [1280, 720])
        self.assertIsNone(requested_window_size())


class CommandValidation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def call(self, *args):
        return CliRunner().invoke(cli, ['--local', '--project', str(self.root), '--non-interactive', *args, '--json'])

    def test_invalid_requests_fail_before_backend_work(self):
        with patch('mcpywrap_core.engines.backend.get_backend') as backend:
            for args in (['connect', 'localhost', '--detach', '--window-size', '1280'],
                         ['run', '--list', '--window-size', '1280x720'],
                         ['window', 'resize', '--session', 'a' * 32, '--size', '10x10']):
                with self.subTest(args=args):
                    result = self.call(*args)
                    self.assertNotEqual(result.exit_code, 0)
            backend.return_value.connect.assert_not_called()
            backend.return_value.run.assert_not_called()

    def test_connect_launches_inside_the_requested_scope(self):
        seen = {}
        backend = Mock(managed_install=False)
        backend.connect.side_effect = lambda *args, **kwargs: seen.setdefault('size', requested_window_size()) and {
            'session': 'a' * 32, 'state': 'running'}
        with patch('mcpywrap_core.engines.backend.get_backend', return_value=backend):
            result = self.call('connect', 'localhost', '--detach', '--window-size', '1600x900')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(seen['size'], [1600, 900])
        self.assertIsNone(requested_window_size())

    def test_run_reusing_a_session_resizes_its_window(self):
        backend = Mock(managed_install=False, capabilities=())
        backend.run.return_value = {'session': 'a' * 32, 'state': 'running', 'already_running': True}
        (self.root/'pyproject.toml').write_text('[project]\nname = "fixture"\n', encoding='utf-8')
        applied = {'requested': {'width': 1280, 'height': 720}, 'state': 'applied', 'width': 1280, 'height': 720}
        with patch('mcpywrap_core.engines.backend.get_backend', return_value=backend), \
                patch('mcpywrap_core.commands.run_cmd.config_exists', return_value=True), \
                patch.object(game_window, 'apply_to_running', return_value=applied) as apply:
            result = self.call('run', '--no-gui', '--detach', '--window-size', '1280x720')
        self.assertEqual(result.exit_code, 0, result.output)
        apply.assert_called_once()
        self.assertEqual(apply.call_args.args[1:], ('a' * 32, (1280, 720)))
        self.assertEqual(json.loads(result.stdout)['window']['state'], 'applied')


class LaunchApplication(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.session = 'a' * 32
        sessions.session_path(self.root, self.session).mkdir(parents=True)
        self.clock = [1000.0]
        clock = patch.object(game_window.time, 'monotonic', side_effect=lambda: self.clock[0])
        clock.start(); self.addCleanup(clock.stop)

    def sizer(self, size=(1280, 720)):
        data = {'window_size': list(size) if size else None}
        return LaunchSizer(data), data

    def poll(self, sizer, data, native, advance=1):
        self.clock[0] += advance
        with patch.object(game_window, '_native', side_effect=native):
            return sizer.poll(self.root, self.session, data)

    def test_no_request_never_touches_the_window(self):
        sizer, data = self.sizer(None)
        native = Mock()
        self.assertFalse(self.poll(sizer, data, native))
        native.assert_not_called()
        self.assertNotIn('window', data)

    def test_waits_for_the_window_then_applies(self):
        sizer, data = self.sizer()
        missing = Mock(side_effect=EngineError('no window', 'window_unavailable'))
        self.assertFalse(self.poll(sizer, data, missing))
        self.assertEqual(data['window']['state'], 'pending')
        self.assertTrue(self.poll(sizer, data, lambda *a: ({}, {'width': 1280, 'height': 720})))
        self.assertEqual(data['window'], {'requested': {'width': 1280, 'height': 720}, 'state': 'applied',
                                          'width': 1280, 'height': 720, 'error': None, 'code': None, 'hint': None})

    def test_permanent_errors_and_timeouts_are_recorded_without_raising(self):
        sizer, data = self.sizer()
        denied = Mock(side_effect=EngineError('denied', 'permission_missing', 'grant it'))
        self.assertTrue(self.poll(sizer, data, denied))
        self.assertEqual((data['window']['state'], data['window']['code'], data['window']['hint']),
                         ('failed', 'permission_missing', 'grant it'))
        self.assertFalse(self.poll(sizer, data, denied))
        sizer, data = self.sizer()
        missing = Mock(side_effect=EngineError('no window', 'window_unavailable'))
        self.assertTrue(self.poll(sizer, data, missing, advance=game_window.LAUNCH_TIMEOUT + 1))
        self.assertEqual(data['window']['code'], 'window_unavailable')

    def test_reapplies_when_the_game_restores_its_size_until_world_ready(self):
        sizer, data = self.sizer()
        self.poll(sizer, data, lambda *a: ({}, {'width': 1280, 'height': 720}))
        calls = []
        def drifted(project, session, size=None):
            calls.append(size)
            return {}, {'width': 1280, 'height': 720} if size else {'width': 720, 'height': 480}
        self.assertTrue(self.poll(sizer, data, drifted))
        self.assertEqual(calls, [None, (1280, 720)])
        data['world_ready'] = True
        native = Mock()
        self.assertFalse(self.poll(sizer, data, native))
        native.assert_not_called()

    def test_manual_resize_wins_over_the_launch_size(self):
        sizer, data = self.sizer()
        self.poll(sizer, data, lambda *a: ({}, {'width': 1280, 'height': 720}))
        game_window.manual_marker(self.root, self.session).touch()
        native = Mock(return_value=({}, {'width': 1920, 'height': 1080}))
        self.assertFalse(self.poll(sizer, data, native))
        self.assertFalse(self.poll(sizer, data, native))
        native.assert_not_called()


class RunningResize(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.session = 'b' * 32
        directory = sessions.session_path(self.root, self.session)
        directory.mkdir(parents=True)
        sessions.save(directory/'session.json', {'session': self.session, 'project': str(self.root),
                                                 'state': 'running', 'backend': 'windows',
                                                 'window': {'requested': {'width': 1280, 'height': 720}, 'state': 'applied'}})

    def test_resize_is_refused_while_recording(self):
        from mcpywrap_core.mcstudio import recordings
        path = recordings.record_path(self.root, self.session, 'c' * 32)
        path.parent.mkdir(parents=True)
        path.write_text('{}', encoding='utf-8')
        with patch.object(recordings, 'read', return_value={'state': 'recording'}), \
                patch.object(game_window, '_native') as native, self.assertRaises(EngineError) as error:
            game_window.resize(self.root, self.session, 1280, 720)
        self.assertEqual(error.exception.code, 'busy')
        native.assert_not_called()

    def test_resize_marks_manual_size_and_reports_actual(self):
        with patch.object(game_window, '_native', return_value=({}, {'width': 1600, 'height': 900, 'scale': 1})) as native:
            result = game_window.resize(self.root, self.session, 1600, 900)
        native.assert_called_once_with(self.root, self.session, (1600, 900))
        self.assertEqual((result['width'], result['height'], result['resized']), (1600, 900, True))
        self.assertTrue(game_window.manual_marker(self.root, self.session).exists())
        with patch.object(game_window, '_native', return_value=({'window': {'state': 'applied'}},
                                                                {'width': 1600, 'height': 900})):
            info = game_window.info(self.root, self.session)
        self.assertEqual(info['launch_request'], {'state': 'applied'})

    def test_apply_to_running_reports_failures_without_raising(self):
        with patch.object(game_window, 'resize', side_effect=EngineError('denied', 'permission_missing', 'grant')):
            result = game_window.apply_to_running(self.root, self.session, (1280, 720))
        self.assertEqual((result['state'], result['code'], result['hint']), ('failed', 'permission_missing', 'grant'))


class MacOSHelper(unittest.TestCase):
    def run_helper(self, stdout, stderr=b''):
        completed = subprocess.CompletedProcess([], 0, stdout, stderr)
        with patch('mcpywrap_core.mcstudio.recordings.macos_helper', return_value=Path('/helper')), \
                patch.object(game_window.subprocess, 'run', return_value=completed) as run:
            return game_window._macos({'pid': 42}, (1280, 720)), run.call_args.args[0]

    def test_sends_pid_and_size_and_returns_state(self):
        result, command = self.run_helper(b'{"ok": true, "width": 1280, "height": 720, "scale": 2}\n')
        self.assertEqual(command, [str(Path('/helper')), '--window', '--pid', '42', '--width', '1280', '--height', '720'])
        self.assertEqual(result['scale'], 2)

    def test_errors_carry_codes_and_actionable_hints(self):
        for payload, code, hint in ((b'{"ok": false, "code": "permission_missing", "error": "x"}', 'permission_missing', '辅助功能'),
                                    (b'{"ok": false, "code": "invalid_size", "error": "x", "scale": 2}', 'invalid_size', '2 倍')):
            with self.subTest(code=code), self.assertRaises(EngineError) as error:
                self.run_helper(payload)
            self.assertEqual(error.exception.code, code)
            self.assertIn(hint, error.exception.hint)
        with self.assertRaises(EngineError) as error:
            self.run_helper(b'', b'usage: mcpy-macos-capture --capabilities')
        self.assertEqual(error.exception.code, 'capability_missing')


class FakeUser32:
    """GetClientRect/GetWindowRect/SetWindowPos 的最小模拟：边框 16x39，SetWindowPos 设置外框。"""

    def __init__(self, client=(1280, 720), style=0x00CF0000, zoomed=False, accept=True):
        self.client, self.style, self.zoomed, self.accept = list(client), style, zoomed, accept
        self.calls = []

    def GetClientRect(self, hwnd, rect):
        rect._obj.right, rect._obj.bottom = self.client
        return 1

    def GetWindowRect(self, hwnd, rect):
        rect._obj.left, rect._obj.top = 100, 50
        rect._obj.right, rect._obj.bottom = 100 + self.client[0] + 16, 50 + self.client[1] + 39
        return 1

    def GetWindowLongW(self, hwnd, index):
        return self.style

    def IsIconic(self, hwnd):
        return 0

    def IsZoomed(self, hwnd):
        return self.zoomed

    def SetWindowPos(self, hwnd, after, x, y, width, height, flags):
        self.calls.append((width, height, flags))
        if self.accept:
            self.client = [width - 16, height - 39]
        return 1


class WindowsResize(unittest.TestCase):
    def window(self, user):
        from mcpywrap_core.mcstudio.window import GameWindow
        window = object.__new__(GameWindow)
        window.user, window.hwnd = user, 7
        window.validate_process = lambda: None
        return window

    def test_sets_outer_size_from_current_frame_without_activation(self):
        user = FakeUser32()
        result = self.window(user).resize_client(1920, 1080)
        self.assertEqual(user.calls, [(1936, 1119, 0x0002 | 0x0004 | 0x0010 | 0x0200)])
        self.assertEqual((result['width'], result['height'], result['fullscreen']), (1920, 1080, False))

    def test_rejects_fullscreen_maximized_and_reports_refused_sizes(self):
        for user, code in ((FakeUser32(style=0x90000000), 'window_fullscreen'),
                           (FakeUser32(zoomed=True), 'window_state_conflict')):
            with self.subTest(code=code), self.assertRaises(EngineError) as error:
                self.window(user).resize_client(1920, 1080)
            self.assertEqual(error.exception.code, code)
            self.assertEqual(user.calls, [])
        with patch('mcpywrap_core.mcstudio.window.time.sleep'), self.assertRaises(EngineError) as error:
            self.window(FakeUser32(accept=False)).resize_client(1920, 1080, timeout=0)
        self.assertEqual(error.exception.code, 'window_size_rejected')


class Persistence(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.seen = []
        self.backend = Mock(id='windows', capabilities=())
        def connect(*args, **kwargs):
            self.seen.append(requested_window_size())
            return {'session': kwargs.get('session_id', 'b' * 32), 'state': 'running'}
        self.backend.connect.side_effect = connect

    def test_group_members_and_retries_use_the_group_size(self):
        with window_size_scope((1280, 720)):
            record = groups._new(self.root, self.backend, 'network', {'overrides': {}})
        self.assertEqual(record['recipe']['window_size'], [1280, 720])
        with patch.object(groups, 'get_backend', return_value=self.backend), patch.object(groups, '_ready'):
            for index in (0, 1, 1):
                groups._connect_member(record, index, ServerTarget('localhost'))
        self.assertEqual(self.seen, [[1280, 720]] * 3)

    def test_single_session_restart_keeps_the_launch_size(self):
        session = 'c' * 32
        data = {'session': session, 'mode': 'network', 'backend': 'windows', 'background': False,
                'window_size': [1600, 900], 'network': {'target': {'host': 'localhost', 'port': 19132, 'auth': 'none'}}}
        with patch.object(groups, 'membership', return_value=None), patch.object(sessions, 'read', return_value=data), \
                patch.object(sessions, 'stop'), patch.object(groups, 'get_backend', return_value=self.backend):
            groups.restart(self.root, session=session)
        self.assertEqual(self.seen, [[1600, 900]])

    def test_new_sessions_record_the_scope_or_explicit_size(self):
        with patch.object(sessions.subprocess, 'Popen', return_value=Mock(pid=1)), \
                patch.object(sessions, '_notify_start'), patch.object(sessions, 'wait_started'), \
                patch('mcpywrap_core.project_scripts.startup_options', return_value={}), \
                patch('mcpywrap_core.project_scripts.reject_recursion'):
            with window_size_scope((1280, 720)):
                sessions.start(self.root, session_id='d' * 32, network={'target': {}})
            sessions.start(self.root, session_id='e' * 32, network={'target': {}}, window_size=[960, 540])
            sessions.start(self.root, session_id='f' * 32, network={'target': {}})
        sizes = [json.loads((sessions.session_path(self.root, s * 32)/'session.json').read_text(encoding='utf-8'))
                 .get('window_size') for s in 'def']
        self.assertEqual(sizes, [[1280, 720], [960, 540], None])


class RemoteWindow(unittest.TestCase):
    def test_service_validates_and_forwards_the_launch_size(self):
        from mcpywrap_core.mcstudio.discovery import Engine
        from mcpywrap_core.remote import service as api
        from mcpywrap_core.remote.protocol import RemoteError
        with tempfile.TemporaryDirectory() as root:
            game = api.GameService(Path(root))
            started = {}
            def start(project, **kwargs):
                started.update(kwargs)
                return {'session': kwargs['session_id'], 'state': 'running', 'game': None}
            with patch.object(api, 'capabilities', return_value={'desktop': {'available': True}}), \
                    patch.object(api, 'prepare_network', return_value=(Engine('g', '3.10', 'e', 'd', 't'), None)), \
                    patch.object(sessions, 'start', side_effect=start), \
                    patch.object(sessions, 'handoff', side_effect=lambda data: dict(data)):
                game.create({'request_id': 'd' * 32, 'host': 'server.local', 'window_size': [1280, 720]})
                self.assertEqual(started['window_size'], [1280, 720])
                for size in ([1280], '1280x720', [10, 10], [1280.0, 720]):
                    with self.subTest(size=size), self.assertRaises(RemoteError):
                        game.create({'request_id': 'e' * 32, 'host': 'server.local', 'window_size': size})
            game.close()

    def test_capability_is_declared_and_client_requires_it(self):
        from mcpywrap_core.remote import client as remote
        fake = Mock()
        fake.request.return_value = {'ok': True}
        with patch.object(remote, 'Client', return_value=fake), \
                patch('mcpywrap_core.command_context.remote_url', return_value='http://host:1'), \
                patch('mcpywrap_core.command_context.project_dir', return_value=Path('.')):
            remote.routed_window('resize', {'session': 'a' * 32, 'size': (1280, 720)})
            remote.routed_window('info', {'session': 'a' * 32})
        fake.require.assert_called_with('window-size')
        self.assertEqual(fake.request.call_args_list[0].args, ('POST', '/sessions/' + 'a' * 32 + '/window',
                                                                {'width': 1280, 'height': 720}))
        self.assertEqual(fake.request.call_args_list[1].args, ('GET', '/sessions/' + 'a' * 32 + '/window'))


if __name__ == '__main__':
    unittest.main()

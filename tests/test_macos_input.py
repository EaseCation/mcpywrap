"""macOS 前台设备输入后端：计划校验、键码映射、准备阶段的授权/前台/客户区守卫与事件投递。"""
import sys
import unittest
from unittest.mock import Mock, patch

from mcpywrap_core.input_plan import InputPlanError, normalize_input_plan
from mcpywrap_core.mcstudio import macos_input
from mcpywrap_core.mcstudio.macos_input import MacInputAdapter, mac_key_code

GAME = {'pid': 77, 'created_at': 1.0, 'executable': '/x/mcpelauncher-client'}


def plan(steps, **extra):
    return normalize_input_plan(dict({'schema_version': 1, 'backend': 'macos-cgevent', 'steps': steps}, **extra))


class FakeHelper:
    def __init__(self, prepare=None, state=None):
        self.calls = []
        self.prepare = dict({'ok': True, 'post_allowed': True, 'frontmost': GAME['pid'], 'keys_down': [], 'buttons': [False] * 3,
                             'client': {'x': 10, 'y': 40, 'width': 1440, 'height': 960}}, **(prepare or {}))
        self.state = dict(self.prepare, **dict({'cursor_inside': True}, **(state or {})))

    def request(self, op, **fields):
        self.calls.append((op, fields))
        if op == 'prepare': return self.prepare
        if op == 'state': return self.state
        return {'ok': True, 'send_started_ns': 1, 'send_finished_ns': 2, 'accepted': True}

    def close(self):
        self.calls.append(('close', {}))


class Plans(unittest.TestCase):
    def test_pointer_actions_are_device_only_and_need_a_reference_viewport(self):
        normalized = plan([{'action': 'pointer.move', 'x': 5, 'y': 6}], width=1440, height=960)
        self.assertEqual(normalized['backend'], 'macos-cgevent')
        with self.assertRaises(InputPlanError):
            plan([{'action': 'pointer.move', 'x': 5, 'y': 6}])
        with self.assertRaises(InputPlanError):
            plan([{'action': 'player.jump'}])
        with self.assertRaises(InputPlanError):
            normalize_input_plan({'schema_version': 1, 'backend': 'game', 'steps': [{'action': 'pointer.wheel', 'delta': 120}]})

    def test_key_names_map_to_macos_virtual_keys(self):
        self.assertEqual(mac_key_code('W'), 13)
        self.assertEqual(mac_key_code('SHIFT'), 56)
        self.assertEqual(mac_key_code('OEM_2'), 44)
        for name in ('VK:0x41', 'MEDIA_NEXT'):
            with self.subTest(name=name), self.assertRaises(InputPlanError):
                mac_key_code(name)


class Adapter(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        self.manager = Mock(project='/p', session='s' * 32)
        self.manager.game.return_value = {'code': 'not_installed'}
        self.adapter = MacInputAdapter(self.manager)
        patch('mcpywrap_core.runtime.window_policy.require_foreground_input').start()
        patch.object(MacInputAdapter, '_game', return_value=GAME).start()
        patch('mcpywrap_core.mcstudio.recordings.macos_helper', return_value='helper').start()
        lock = Mock(); lock.__enter__ = Mock(); lock.__exit__ = Mock()
        patch.object(macos_input, 'desktop_input_lock', return_value=lock).start()

    def operation(self, steps, helper, **extra):
        normalized = plan(steps, **extra)
        patch.object(macos_input, 'MacInputHelper', return_value=helper).start()
        op = {'operation_id': 'o', '_signature': 'x', 'plan': normalized,
              '_bindings': self.adapter.validate(normalized), 'released': True}
        return op

    def test_prepare_requires_accessibility_permission_and_foreground(self):
        for prepare, code in (({'post_allowed': False}, 'permission_missing'),
                              ({'frontmost': 1}, 'foreground_unavailable'),
                              ({'keys_down': [13]}, 'input_busy')):
            with self.subTest(code=code):
                op = self.operation([{'action': 'key', 'keys': ['W'], 'duration_ms': 50}], FakeHelper(prepare))
                with self.assertRaises(InputPlanError) as caught:
                    self.adapter.prepare(op)
                self.assertEqual(caught.exception.code, code)

    def test_pointer_plan_checks_viewport_and_cursor_before_button_down(self):
        helper = FakeHelper(state={'cursor_inside': False})
        steps = [{'action': 'pointer.down', 'button': 'left'}, {'action': 'pointer.up', 'button': 'left'}]
        op = self.operation(steps, helper, width=1440, height=960)
        self.adapter.prepare(op)
        with self.assertRaises(InputPlanError) as caught:
            self.adapter.send('pointer', 'left', True)
        self.assertEqual(caught.exception.code, 'pointer_outside')
        self.assertTrue(self.adapter.send('pointer', 'left', False))
        mismatched = self.operation(steps, FakeHelper(), width=800, height=600)
        with self.assertRaises(InputPlanError) as caught:
            MacInputAdapter(self.manager).prepare(mismatched)
        self.assertEqual(caught.exception.code, 'viewport_changed')

    def test_key_edges_and_pointer_motion_are_forwarded_with_send_times(self):
        helper = FakeHelper()
        op = self.operation([{'action': 'key', 'keys': ['W'], 'duration_ms': 50},
                             {'action': 'pointer.relative', 'dx': 20, 'dy': 0}], helper, width=1440, height=960)
        self.adapter.prepare(op)
        self.assertTrue(self.adapter.send('key', 13, True))
        self.assertEqual(self.adapter.last_send['send_started_ns'], 1)
        stage = {'step': op['plan']['steps'][1]}
        self.adapter.begin(op, stage)
        self.assertEqual(helper.calls[-1], ('relative', {'dx': 20, 'dy': 0}))
        self.assertTrue(stage['result']['accepted'])
        self.adapter.finished(op)
        self.assertEqual(helper.calls[-1][0], 'close')

    def test_lost_foreground_is_detected_by_the_guard(self):
        helper = FakeHelper()
        op = self.operation([{'action': 'key', 'keys': ['W'], 'duration_ms': 50}], helper)
        self.adapter.prepare(op)
        helper.state['frontmost'] = 1
        with self.assertRaises(InputPlanError) as caught:
            self.adapter.guard(op)
        self.assertEqual(caught.exception.code, 'foreground_lost')


class Manager(unittest.TestCase):
    def test_platform_selects_the_device_backend_and_reports_both_in_capabilities(self):
        from mcpywrap_core.mcstudio import host_input
        with patch.object(host_input.sys, 'platform', 'darwin'):
            manager = host_input.HostInputManager(Mock(), '/p', 's' * 32)
        self.addCleanup(manager.close)
        self.assertEqual(manager.device_backend, 'macos-cgevent')
        with patch.object(manager, 'game', return_value={'ok': True, 'actions': {}}):
            backends = manager.dispatch('capabilities', {})['backends']
        self.assertEqual(set(backends), {'game', 'windows-sendinput', 'macos-cgevent'})
        self.assertTrue(backends['macos-cgevent']['foreground_required'])
        self.assertEqual(backends['macos-cgevent']['actions']['pointer.move']['supported'], sys.platform == 'darwin')
        with self.assertRaises(InputPlanError) as caught:
            manager.dispatch('run', {'plan': {'backend': 'windows-sendinput'}, 'request_id': 'r'})
        self.assertEqual(caught.exception.code, 'not_supported')


if __name__ == '__main__':
    unittest.main()

"""统一计划的语义、能力、公共传输和旧入口隔离；仅模拟引擎。"""
import copy
import heapq
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from click.testing import CliRunner

from mcpywrap.cli import cli
from mcpywrap.input_plan import normalize_input_plan, InputPlanError, input_key_plan, INPUT_ACTIONS
from mcpywrap.mcstudio.runtime_input_payload import GameInputController
from mcpywrap.mcstudio.runtime_player_payload import PlayerController
from mcpywrap.mcstudio.runtime_ui_payload import UIController, UIError
from test_runtime_player import PlayerAPI, Native, GUI
from test_runtime_ui import API, ROOT


def plan(steps, **kwargs):
    return dict(schema_version=1, steps=steps, **kwargs)


class UnifiedInputTests(unittest.TestCase):
    def setUp(self):
        self.api = PlayerAPI()
        for key, code in {'A': 65, 'D': 68, 'RETURN': 13, 'MENU': 18, 'CAPS_LOCK': 20,
                          'PG_UP': 33, 'GRAVE': 192, 'APOSTRAPHE': 222}.items():
            setattr(self.api.enum.KeyBoardType, 'KEY_'+key, code)
        self.gui = GUI(self.api)
        self.inputs = []
        self.gui.simulate_keyboard_event = lambda code, down: self.inputs.append((self.api.now, code, down)) or True
        self.ui = UIController(self.api, self.gui, 'fake-engine', clock=lambda: self.api.now)
        self.ui.events = Mock()
        self.native = Native(self.api)
        self.player = PlayerController(self.ui, self.native)
        self.ui.player = self.player
        self.control = GameInputController(self.ui, self.player)
        self.ui.input = self.control
        self.control.adapter.clock = lambda: self.api.now
        self.control.adapter.clock_source = 'fake-monotonic'

    def result(self, op):
        return self.control.status(op['operation_id'], details=True)

    def late(self, seconds):
        _, _, callback = heapq.heappop(self.api.scheduled)
        self.api.now = seconds
        callback()

    def test_shortcut_and_json_use_same_plan_order_and_lifecycle(self):
        expected = input_key_plan('W+CTRL', 100)
        for recipe in (expected, plan([{'action': 'key', 'keys': ['W', 'CONTROL'], 'duration_ms': 100}])):
            op = self.control.run(recipe)
            self.api.advance(.2)
            result = self.result(op)
            self.assertEqual(result['plan'], expected)
            self.assertEqual(result['state'], 'completed')
        self.assertEqual([(c, d) for _, c, d in self.inputs], [(87, True), (17, True), (17, False), (87, False)]*2)
        self.assertTrue(self.result(op)['released'])
        self.assertNotIn('plan', self.control.status(op['operation_id']))

    def test_plan_compilation_supports_explicit_automatic_and_mixed(self):
        automatic = plan([{'action': 'key', 'keys': ['W'], 'duration_ms': 100},
                          {'action': 'wait', 'duration_ms': 20, 'delay_ms': 5}, {'action': 'player.jump'}])
        expected = [0, 105, 125]
        compiled = normalize_input_plan(automatic)
        self.assertEqual([s['at_ms'] for s in compiled['steps']], expected)
        mixed = copy.deepcopy(automatic); mixed['steps'][1].pop('delay_ms'); mixed['steps'][1]['at_ms'] = 105
        self.assertEqual(normalize_input_plan(mixed), compiled)
        self.assertNotIn('at_ms', automatic['steps'][0])

    def test_late_duration_and_wait_keep_runtime_semantics(self):
        for waiting in (False, True):
            with self.subTest(waiting=waiting):
                self.setUp()
                steps = [{'action': 'key', 'keys': ['W'], 'duration_ms': 500}]
                if waiting: steps.append({'action': 'wait', 'duration_ms': 100})
                steps.append(dict(action='key', keys=['SPACE'], duration_ms=80, **({} if waiting else {'delay_ms': 100})))
                op = self.control.run(plan(steps))
                self.api.advance(0)
                self.late(.2)  # 持有完成轮询迟到；不改变整个计划。
                self.api.advance(1)
                result = self.result(op)
                self.assertEqual(result['state'], 'completed')
                self.assertAlmostEqual(self.inputs[1][0]-self.inputs[0][0], .5, delta=.011)
                if waiting:
                    self.assertGreaterEqual(self.inputs[2][0]-self.inputs[1][0], .1-1e-9)
        self.setUp()
        op = self.control.run(plan([{'action': 'key', 'keys': ['W'], 'duration_ms': 500},
                                   {'action': 'key', 'keys': ['SPACE'], 'duration_ms': 80, 'delay_ms': 100}]))
        self.api.advance(0)
        # 引擎输入调用耗时使第一动作实际开始/持有结束迟到。
        self.control.active['_stage']['until'] = .7
        self.api.advance(1)
        self.assertAlmostEqual(self.inputs[2][0], .7, delta=.011)

    def test_key_duration_begins_at_actual_dispatch_not_after_submission_overhead(self):
        def send(code, down):
            self.inputs.append((self.api.now, code, down))
            if down: self.api.now += .02
            return True
        self.gui.simulate_keyboard_event = send
        op = self.control.key('CTRL+W', duration_ms=100)
        self.api.advance(.2)
        self.assertEqual(self.result(op)['state'], 'completed')
        self.assertAlmostEqual(self.inputs[-1][0]-self.inputs[0][0], .1, delta=.011)

    def test_first_callback_is_origin_and_waiting_interval_blocks_legacy(self):
        op = self.control.run(plan([{'action': 'key_down', 'key': 'W', 'at_ms': 500},
                                   {'action': 'key_up', 'key': 'W', 'at_ms': 1000}]))
        self.assertEqual(self.player.dispatch('jump')['code'], 'busy')
        with self.assertRaises(UIError): self.ui._ready()
        self.late(2)
        self.assertTrue(self.control.observe()['ok'])
        self.api.advance(.499)
        self.assertEqual(self.inputs, [])
        self.api.advance(.502)
        self.assertEqual(self.result(op)['state'], 'completed')
        self.assertAlmostEqual(self.inputs[0][0], 2.5, delta=.002)

    def test_held_forward_attack_and_independent_jump(self):
        op = self.control.run(plan([{'action': 'key_down', 'key': 'W'},
                                   {'action': 'player.attack', 'at_ms': 200},
                                   {'action': 'key_down', 'key': 'SPACE', 'at_ms': 300},
                                   {'action': 'key_up', 'key': 'SPACE', 'at_ms': 450},
                                   {'action': 'key_up', 'key': 'W', 'at_ms': 600}]))
        self.api.advance(.46)
        self.assertEqual(self.result(op)['held_keys'], ['W'])
        self.assertEqual(self.api.health, 5)
        self.assertEqual(self.player.dispatch('key', keys='A')['code'], 'busy')
        self.api.advance(.2)
        self.assertEqual(self.result(op)['state'], 'completed')
        self.assertEqual([r['input_path'] for r in self.result(op)['steps']][1], 'game-player:attack')

    def test_menu_keys_allowed_but_page_change_cancels_remaining(self):
        self.api.node.top = 'pause_screen'; self.api.node.screen = 'pause.pause_screen'
        op = self.control.key('ESC', duration_ms=100)
        self.api.advance(.2)
        self.assertEqual(self.result(op)['state'], 'completed')
        self.assertEqual(self.player.dispatch('key', keys='ESC')['code'], 'menu_open')
        self.api.node.top = 'hud_screen'; self.api.node.screen = 'hud.hud_screen'
        op = self.control.run(plan([{'action': 'key_down', 'key': 'W'}, {'action': 'wait', 'duration_ms': 500},
                                   {'action': 'key_up', 'key': 'W'}]))
        self.api.advance(.1); self.api.node.top = 'pause_screen'; self.ui._changed()
        count = len(self.inputs); self.api.advance(1)
        self.assertEqual(len(self.inputs), count)
        self.assertEqual(self.result(op)['state'], 'cancelled')
        self.assertTrue(self.result(op)['released'])

    def test_expectation_checked_before_each_player_action(self):
        op = self.control.run(plan([{'action': 'player.select_slot', 'slot': 2},
                                   {'action': 'player.attack', 'expect': {'selected_slot': 1}}]))
        self.api.advance(.2)
        self.assertEqual(self.result(op)['code'], 'expectation_failed')
        self.assertEqual(self.api.health, 10)

    def test_cancel_releases_child_action_and_owned_keys(self):
        op = self.control.run(plan([{'action': 'key_down', 'key': 'W'},
                                   {'action': 'player.sneak', 'duration_ms': 1000},
                                   {'action': 'key_up', 'key': 'W'}]))
        self.api.advance(.1)
        self.assertTrue(self.api.sneaking)
        result = self.control.cancel(op['operation_id'])
        self.assertTrue(result['ok'])
        self.assertTrue(result['released']); self.assertFalse(self.api.sneaking)
        self.api.advance(2)
        self.assertEqual(len(self.inputs), 2)

    def test_uncertain_press_and_release_failure_blocks_until_retry(self):
        fail_release = [True]
        def send(code, down):
            self.inputs.append((self.api.now, code, down))
            if down and code == 32: raise RuntimeError('uncertain press')
            return not (code == 32 and not down and fail_release[0])
        self.gui.simulate_keyboard_event = send
        op = self.control.run(plan([{'action': 'key', 'keys': ['W', 'SPACE'], 'duration_ms': 100}]))
        self.api.advance(0)
        self.assertEqual(self.result(op)['state'], 'unknown')
        self.assertEqual(self.result(op)['held_keys'], ['SPACE'])
        self.assertEqual(self.player.dispatch('jump')['code'], 'busy')
        self.assertEqual(self.control.dispatch('run', plan=input_key_plan('W'))['code'], 'busy')
        fail_release[0] = False
        self.assertTrue(self.control.stop()['ok'])
        self.assertEqual(self.result(op)['state'], 'failed')
        self.assertTrue(self.result(op)['released'])

    def test_child_release_unknown_can_be_retried(self):
        self.native.release_error = True
        op = self.control.run(plan([{'action': 'player.eat', 'duration_ms': 100}]))
        self.api.advance(.2)
        self.assertEqual(self.result(op)['state'], 'unknown')
        self.native.release_error = False
        self.assertTrue(self.control.stop()['ok'])
        self.assertIsNone(self.player.active)

    def test_idempotency_uses_normalized_plan_and_cloned_results(self):
        recipe = plan([{'action': 'key', 'keys': ['control', 'w']}])
        op = self.control.run(recipe, request_id='a'*32)
        recipe['steps'][0]['keys'][0] = 'A'; op['plan']['steps'][0]['keys'][0] = 'D'
        self.api.advance(.2)
        repeat = self.control.key('CTRL+W', request_id='a'*32)
        self.assertEqual(repeat['state'], 'completed')
        self.assertEqual(len(self.inputs), 4)
        self.assertEqual(self.control.dispatch('key', keys='W', request_id='a'*32)['code'], 'request_conflict')

    def test_lateness_abort_and_timeout_before_resuming(self):
        op = self.control.run(plan([{'action': 'key_down', 'key': 'W'},
                                   {'action': 'key_up', 'key': 'W', 'at_ms': 100}], max_lateness_ms=20))
        self.api.advance(0); self.late(.5)
        self.assertEqual(self.result(op)['code'], 'deadline_missed')
        self.assertEqual(self.result(op)['index'], 1)
        self.setUp()
        op = self.control.key('W')
        self.late(126)
        self.assertEqual(self.result(op)['code'], 'input_timeout')
        self.assertEqual(self.inputs, [])

    def test_no_clock_or_device_semantics_never_fallback(self):
        for key in ('RCTRL', 'LSHIFT', 'NUMPAD_ENTER', 'SC:0x11', 'VK:0x57', 'MOUSE_LEFT'):
            self.assertEqual(self.control.dispatch('key', keys=key)['code'], 'not_supported')
        self.assertFalse(self.inputs)
        self.control.adapter.clock = None
        self.assertFalse(self.control.capabilities()['actions']['key']['supported'])
        self.assertEqual(self.control.dispatch('key', keys='W')['code'], 'not_supported')

    def test_bad_later_steps_rejected_before_any_side_effect(self):
        invalid = [plan([{'action': 'key_down', 'key': 'W'}]),
                   plan([{'action': 'key_down', 'key': 'CTRL'}, {'action': 'key_down', 'key': 'CONTROL'}]),
                   plan([{'action': 'key', 'keys': ['W'], 'duration_ms': 100}, {'action': 'player.jump', 'at_ms': 20}]),
                   plan([{'action': 'wait', 'duration_ms': True}]),
                   plan([{'action': 'key', 'keys': 'CTRL+W'}]),
                   plan([{'action': 'key', 'keys': ['W'], 'hold_ms': 100}]),
                   plan([{'action': 'player.look', 'pitch': 0, 'yaw': float('nan')}]),
                   plan([{'action': 'player.jump', 'expect': {'bad': True}}]),
                   plan([{'action': 'pointer.relative', 'dx': 1, 'dy': 2}]),
                   plan([{'action': 'ui.click', 'node': 1, 'snapshot': 's'}, {'action': 'wait', 'duration_ms': 100}]),
                   dict(plan([{'action': 'wait', 'duration_ms': 1}]), schema_version=True)]
        for recipe in invalid:
            with self.subTest(recipe=recipe), self.assertRaises(InputPlanError): self.control.run(recipe)
        self.assertFalse(self.inputs); self.assertFalse(self.api.scheduled)

    def test_plan_size_limit_after_canonical_serialization(self):
        recipe = plan([{'action': 'player.jump', 'expect': {'item': '界'*256}}]*32)
        with self.assertRaises(InputPlanError) as error: normalize_input_plan(recipe)
        self.assertEqual(error.exception.code, 'plan_too_large')

    def test_nested_expect_is_cloned_before_submission(self):
        recipe = plan([{'action': 'player.attack', 'at_ms': 200, 'expect': {'target': {'entityId': 'cow'}}}])
        op = self.control.run(recipe)
        recipe['steps'][0]['expect']['target']['entityId'] = 'other'
        self.api.advance(.4)
        self.assertEqual(self.result(op)['state'], 'completed')
        self.assertEqual(self.api.health, 5)

    def test_failed_steps_have_actual_boundaries_and_bounded_errors(self):
        op = self.control.run(plan([{'action': 'player.attack', 'expect': {'item': 'missing'}}]))
        self.api.advance(.1)
        row = self.result(op)['steps'][0]
        self.assertEqual(row['result']['state'], 'failed')
        self.assertEqual(row['result']['code'], 'expectation_failed')
        self.assertGreaterEqual(row['finished_ms'], row['started_ms'])

    def test_ui_modifier_click_and_snapshot_stale_before_press(self):
        self.api.node.top = 'settings_screen'; self.api.node.screen = 'settings.settings_screen'
        observed = self.control.observe(view='ui')
        node = next(row for row in observed['nodes'] if row['role'] == 'button')
        recipe = plan([{'action': 'ui.click', 'node': node['id'], 'snapshot': observed['snapshot'], 'keys': ['CTRL', 'SHIFT']}])
        op = self.control.run(recipe)
        self.api.advance(.2)
        self.assertEqual(self.result(op)['state'], 'completed')
        self.assertEqual([(c, d) for _, c, d in self.inputs], [(17, True), (16, True), (16, False), (17, False)])
        result = self.control.dispatch('run', plan=recipe)
        self.assertEqual(result['code'], 'stale_snapshot')
        self.assertEqual(len(self.inputs), 4)

    def test_ui_transition_is_allowed_only_for_current_single_node_action(self):
        self.api.node.top = 'settings_screen'; self.api.node.screen = 'settings.settings_screen'
        observed = self.control.observe(view='ui'); node = next(row for row in observed['nodes'] if row['role'] == 'button')
        original = self.gui.simulate_button_event
        def click(x, y, state):
            result = original(x, y, state)
            if state == 0:
                self.api.node.top = 'pause_screen'; self.ui._changed()
            return result
        self.gui.simulate_button_event = click
        op = self.control.run(plan([{'action': 'ui.click', 'node': node['id'], 'snapshot': observed['snapshot']}]))
        self.api.advance(.2)
        self.assertEqual(self.result(op)['state'], 'completed')
        self.assertTrue(self.result(op)['released'])

    def test_hbui_observe_returns_limitation_and_navigation_actions(self):
        self.api.node.top = 'ui://./hbui/index.html'
        result = self.control.observe()
        self.assertTrue(result['ok'])
        self.assertFalse(result['observation_available'])
        self.assertIn('key', result['allowed_actions'])
        self.assertNotIn('ui.click', result['allowed_actions'])
        self.assertFalse(result['nodes'])

    def test_unified_stop_releases_legacy_inputs(self):
        self.player.key('CTRL+W', hold_ms=1000)
        self.assertTrue(self.control.stop()['ok'])
        self.assertIsNone(self.player.active)
        self.assertEqual([(c, d) for _, c, d in self.inputs], [(17, True), (87, True), (87, False), (17, False)])

    def test_native_launcher_clock_is_used_without_platform_fallback(self):
        from mcpywrap.mcstudio import runtime_key_timeline_payload as clocks
        import sys
        native = types.ModuleType('_mcpy_launcher')
        native.monotonic = lambda: 123.
        with patch.dict(sys.modules, {'_mcpy_launcher': native}), \
             patch.object(clocks.time, 'monotonic', None), patch.object(clocks.sys, 'platform', 'darwin'):
            clock, source = clocks.key_timeline_clock()
        self.assertEqual(source, 'launcher.steady_clock')
        self.assertEqual(clock(), 123.)

    def test_public_help_only_recommends_unified_input(self):
        runner = CliRunner()
        root = runner.invoke(cli, ['--help']).output
        runtime = runner.invoke(cli, ['runtime', '--help']).output
        for name in ('key', 'mouse', 'input-sequence'):
            self.assertNotIn('  '+name+' ', root)
            self.assertEqual(runner.invoke(cli, [name, '--help']).exit_code, 0)
        self.assertIn('  input ', runtime)
        for name in ('player', 'ui'):
            self.assertNotIn('  '+name+' ', runtime)
            self.assertEqual(runner.invoke(cli, ['runtime', name, '--help']).exit_code, 0)

    def test_cli_json_shortcut_and_transport_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory)/'input.json'
            file.write_text(json.dumps(plan([{'action': 'key', 'keys': ['CTRL', 'W'], 'duration_ms': 500}])))
            with patch('mcpywrap.mcstudio.unified_input.execute', return_value={'ok': True}) as execute:
                runner = CliRunner()
                for args in (['run', '--file', str(file)], ['key', 'CTRL+W', '--duration-ms', '500']):
                    result = runner.invoke(cli, ['--local', 'runtime', 'input']+args+['--session', 'a'*32, '--request-id', 'b'*32, '--json'])
                    self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(execute.call_args_list[0].args, execute.call_args_list[1].args)
            from mcpywrap.mcstudio.runtime_ui import execute as game_execute
            with patch('mcpywrap.mcstudio.runtime_debug.control_request', return_value={
                    'state': 'completed', 'side': 'client', 'request_id': 'wire',
                    'value': {'ok': True, 'operation_id': 'b'*32, 'request_id': 'b'*32, 'state': 'pending'}}):
                result = game_execute(Path('.'), 'a'*32, 'run', {'plan': input_key_plan('W'), 'request_id': 'b'*32}, family='input')
            self.assertEqual(result['request_id'], 'b'*32)
            self.assertEqual(result['transport']['request_id'], 'wire')


if __name__ == '__main__': unittest.main()

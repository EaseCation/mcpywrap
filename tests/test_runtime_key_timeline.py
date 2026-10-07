"""按键边沿顺序、故障清理与公开传输契约；不启动真实游戏。"""
import copy
import heapq
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from click.testing import CliRunner
from mcpywrap.cli import cli
from mcpywrap.mcstudio import runtime_key_timeline_payload as payload
from mcpywrap.mcstudio.runtime_player_payload import PlayerController
from mcpywrap.mcstudio.runtime_ui_payload import UIController, UIError
from test_runtime_player import PlayerAPI, GUI


def event(at, action, key):
    return {'at': at, 'action': action, 'key': key}


def plan(events=None, **extra):
    return dict(schema_version=1, clock='monotonic_ms', events=events or [
        event(0, 'key_down', 'W'), event(300, 'key_down', 'SPACE'),
        event(450, 'key_up', 'SPACE'), event(1000, 'key_up', 'W')], **extra)


class KeyTimelineTests(unittest.TestCase):
    def setUp(self):
        self.api = PlayerAPI()
        self.api.enum.KeyBoardType.KEY_A = 65
        self.api.enum.KeyBoardType.KEY_D = 68
        self.gui = GUI(self.api)
        self.inputs = []
        self.gui.simulate_keyboard_event = lambda code, down: self.inputs.append((code, down, self.api.now)) or True
        self.ui = UIController(self.api, self.gui, 'test-engine', clock=lambda: self.api.now)
        self.ui.events = Mock()
        self.player = PlayerController(self.ui, timeline_clock=lambda: self.api.now)
        self.ui.player = self.player

    def result(self, operation):
        return self.player.status(operation['id'], details=True)

    def stalled_callback(self, now):
        _, _, callback = heapq.heappop(self.api.scheduled)
        self.api.now = now
        callback()

    def test_independent_jump_release_keeps_forward_held(self):
        op = self.player.timeline(plan())
        self.api.advance(.451)
        midway = self.result(op)
        self.assertEqual(midway['held_keys'], ['W'])
        self.assertEqual(midway['index'], 3)
        self.assertEqual([(c, d) for c, d, _ in self.inputs], [(87, True), (32, True), (32, False)])
        self.api.advance(.6)
        result = self.result(op)
        self.assertEqual(result['state'], 'completed')
        self.assertTrue(result['released'])
        self.assertFalse(result['held_keys'])
        self.assertFalse(result['effect_verified'])
        self.assertEqual(result['cleanup_events'], [])
        self.assertEqual([r['index'] for r in result['events']], [0, 1, 2, 3])
        self.assertEqual(result['events'][2]['held_keys'], ['W'])
        self.assertEqual([r['keycode'] for r in result['events']], [87, 32, 32, 87])

    def test_overlap_direction_switch_and_three_key_chord(self):
        recipe = plan([event(0, 'key_down', 'W'), event(0, 'key_down', 'A'),
                       event(100, 'key_down', 'SPACE'), event(200, 'key_up', 'A'),
                       event(200, 'key_down', 'D'), event(300, 'key_up', 'SPACE'),
                       event(400, 'key_up', 'D'), event(500, 'key_up', 'W')])
        op = self.player.timeline(recipe)
        self.api.advance(.101)
        self.assertEqual(self.result(op)['held_keys'], ['W', 'A', 'SPACE'])
        self.api.advance(.101)
        self.assertEqual(self.result(op)['held_keys'], ['W', 'SPACE', 'D'])
        self.api.advance(.4)
        self.assertEqual(self.result(op)['state'], 'completed')

    def test_equal_time_respects_list_order_on_every_run(self):
        for keys in (('W', 'CTRL'), ('CTRL', 'W')):
            expected = [self.player._key_codes(k)[0] for k in keys]
            for _ in range(3):
                self.inputs[:] = []
                op = self.player.timeline(plan([event(0, 'key_down', k) for k in keys] +
                                               [event(100, 'key_up', k) for k in keys]))
                self.api.advance(.2)
                self.assertEqual([c for c, _, _ in self.inputs], expected+expected)
                self.assertEqual(self.result(op)['state'], 'completed')

    def test_same_time_down_and_up_are_not_extended(self):
        op = self.player.timeline(plan([event(0, 'key_down', 'SPACE'), event(0, 'key_up', 'SPACE')]))
        self.api.advance(0)
        self.assertEqual(self.inputs, [(32, True, 0), (32, False, 0)])
        self.assertEqual(self.result(op)['state'], 'completed')

    def test_clock_starts_at_first_callback_and_offsets_do_not_accumulate(self):
        op = self.player.timeline(plan())
        self.stalled_callback(2.)
        self.assertEqual(self.inputs, [(87, True, 2.)])
        self.api.advance(1.01)
        result = self.result(op)
        self.assertEqual([r['at'] for r in result['events']], [0, 300, 450, 1000])
        for row in result['events']:
            self.assertAlmostEqual(row['started_ms'], row['at'], delta=1.01)
            self.assertGreaterEqual(row['finished_ms'], row['started_ms'])

    def test_late_callbacks_continue_and_log_compressed_hold(self):
        op = self.player.timeline(plan())
        self.api.advance(0)
        self.stalled_callback(.6)
        self.assertEqual([(c, d) for c, d, _ in self.inputs], [(87, True), (32, True), (32, False)])
        records = self.result(op)['events']
        self.assertAlmostEqual(records[1]['lateness_ms'], 300)
        self.assertAlmostEqual(records[2]['lateness_ms'], 150)
        self.assertEqual(records[1]['started_ms'], records[2]['started_ms'])
        self.api.advance(.5)
        self.assertEqual(self.result(op)['state'], 'completed')

    def test_optional_lateness_limit_stops_without_submitting_missed_edge(self):
        op = self.player.timeline(plan(max_lateness=100))
        self.api.advance(0)
        self.stalled_callback(.6)
        result = self.result(op)
        self.assertEqual(result['code'], 'deadline_missed')
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['index'], 1)
        self.assertEqual([(c, d) for c, d, _ in self.inputs], [(87, True), (87, False)])
        self.assertEqual(result['cleanup_events'][0]['release_of_index'], 0)
        self.api.advance(2)
        self.assertEqual(len(self.inputs), 2)

    def test_timeout_checked_before_start_and_after_pause(self):
        for start in (False, True):
            op = self.player.timeline(plan())
            if start:
                self.api.advance(0)
            before = len(self.inputs)
            self.stalled_callback(self.api.now+126)
            result = self.result(op)
            self.assertEqual(result['code'], 'timeline_timeout')
            self.assertTrue(result['released'])
            self.assertEqual(len(self.inputs)-before, 1 if start else 0)

    def test_waiting_and_empty_held_interval_remain_busy(self):
        op = self.player.timeline(plan([event(500, 'key_down', 'SPACE'), event(600, 'key_up', 'SPACE'),
                                       event(1000, 'key_down', 'W'), event(1100, 'key_up', 'W')]))
        for amount in (0, .7):
            self.api.advance(amount)
            self.assertEqual(self.result(op)['held_keys'], [])
            self.assertEqual(self.player.dispatch('key', keys='W')['code'], 'busy')
            self.assertEqual(self.player.dispatch('sequence', steps=[{'action': 'jump'}])['code'], 'busy')
            with self.assertRaises(UIError):
                self.ui._ready()
            self.assertTrue(self.player.snapshot()['ok'])
            self.assertTrue(self.player.status()['ok'])
        self.player.stop()

    def test_legacy_key_snapshot_keeps_original_observation_fields(self):
        self.player.key('CTRL+W', hold_ms=100)
        self.assertIn('before', self.player.snapshot()['active'])
        self.api.advance(.2)
        self.assertIn('after', self.player.snapshot()['last_action'])

    def test_cancel_cleans_up_reverse_actual_press_order_and_never_resumes(self):
        op = self.player.timeline(plan())
        self.api.advance(.301)
        result = self.player.cancel(op['id'])
        self.assertEqual(result['state'], 'cancelled')
        self.assertTrue(result['released'])
        self.assertEqual([(c, d) for c, d, _ in self.inputs][-2:], [(32, False), (87, False)])
        self.api.advance(2)
        self.assertEqual(len(self.inputs), 4)
        self.assertEqual(self.result(op)['index'], 2)

    def test_lifecycle_cleanup_during_menu_world_change_and_uninstall(self):
        for reason in ('menu', 'world', 'unload', 'close'):
            with self.subTest(reason=reason):
                self.setUp()
                op = self.player.timeline(plan())
                self.api.advance(.301)
                if reason == 'menu':
                    self.api.node.top = 'pause_screen'
                    self.ui._changed()
                elif reason == 'world':
                    self.api.GetLocalPlayerId = lambda: None
                    self.api.advance(.06)
                elif reason == 'unload':
                    self.player._timeline_unload()
                else:
                    self.ui.close()
                result = self.result(op)
                self.assertTrue(result['released'])
                self.assertIn(result['state'], ('failed', 'cancelled'))
                count = len(self.inputs)
                self.api.advance(2)
                self.assertEqual(len(self.inputs), count)

    def test_world_identity_change_stops_before_next_edge(self):
        op = self.player.timeline(plan())
        self.api.advance(0)
        self.api.GetCurrentDimension = lambda: 1
        self.api.advance(.06)
        result = self.result(op)
        self.assertEqual(result['code'], 'world_changed')
        self.assertEqual(result['index'], 1)
        self.assertTrue(result['released'])

    def test_partial_press_failure_releases_even_uncertain_key(self):
        def send(code, down):
            self.inputs.append((code, down, self.api.now))
            if code == 32 and down:
                raise RuntimeError('may already have pressed')
            return True
        self.gui.simulate_keyboard_event = send
        op = self.player.timeline(plan())
        self.api.advance(.4)
        result = self.result(op)
        self.assertEqual(result['state'], 'failed')
        self.assertIsNone(result['events'][1]['accepted'])
        self.assertEqual([r['key'] for r in result['cleanup_events']], ['SPACE', 'W'])
        self.assertTrue(result['released'])

    def test_release_failure_retains_ownership_until_stop_retry(self):
        reject = [True]
        def send(code, down):
            self.inputs.append((code, down, self.api.now))
            return not (code == 32 and not down and reject[0])
        self.gui.simulate_keyboard_event = send
        op = self.player.timeline(plan())
        self.api.advance(.6)
        result = self.result(op)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['held_keys'], ['SPACE'])
        self.assertEqual(result['unconfirmed_release_keys'], ['SPACE'])
        self.assertEqual(self.player.dispatch('jump')['code'], 'busy')
        count = len(self.inputs)
        self.api.advance(2)
        self.assertEqual(len(self.inputs), count)
        reject[0] = False
        self.assertTrue(self.player.stop()['ok'])
        self.assertEqual(self.result(op)['state'], 'failed')
        self.assertTrue(self.result(op)['released'])

    def test_cleanup_log_is_bounded_and_reports_loss(self):
        op = self.player.timeline(plan())
        self.api.advance(0)
        self.gui.simulate_keyboard_event = lambda *args: False
        for _ in range(514):
            self.player.stop()
        result = self.result(op)
        self.assertLessEqual(len(result['cleanup_events']), 512)
        self.assertGreaterEqual(result['cleanup_events_dropped'], 2)
        self.assertEqual(len(result['cleanup_events'])+result['cleanup_events_dropped'], 514)
        self.assertLessEqual(len(json.dumps(result)), 180000)
        self.assertTrue(result['logs_truncated'])
        stop = self.player.stop()
        self.assertNotIn('cleanup_events', stop['active'])
        self.assertLess(len(json.dumps(stop)), 2000)

    def test_unbounded_engine_error_is_truncated_without_losing_cleanup(self):
        def send(code, down):
            if down:
                raise RuntimeError('异常'*10000)
            return True
        self.gui.simulate_keyboard_event = send
        op = self.player.timeline(plan())
        self.api.advance(0)
        result = self.result(op)
        self.assertTrue(result['released'])
        self.assertEqual(result['state'], 'failed')
        self.assertTrue(result['error_truncated'])
        self.assertEqual(len(result['error']), 512)
        self.assertEqual(len(result['events'][0]['error']), 512)

    def test_timer_failure_before_input_or_after_press_releases(self):
        self.api.AddTimer = Mock(return_value=None)
        op = self.player.timeline(plan())
        self.assertEqual(self.result(op)['code'], 'timer_unavailable')
        self.assertFalse(self.inputs)
        self.setUp()
        op = self.player.timeline(plan())
        self.api.AddTimer = Mock(side_effect=RuntimeError('timer failed'))
        self.api.advance(0)
        self.assertEqual(self.result(op)['state'], 'failed')
        self.assertTrue(self.result(op)['released'])
        self.assertEqual([(c, d) for c, d, _ in self.inputs], [(87, True), (87, False)])

    def test_plan_copy_and_idempotency_before_during_and_after_execution(self):
        recipe = plan()
        op = self.player.timeline(recipe, request_id='e'*32)
        self.assertEqual(self.player.timeline(copy.deepcopy(recipe), request_id='e'*32)['id'], op['id'])
        self.api.advance(.4)
        count = len(self.inputs)
        self.player.timeline(recipe, request_id='e'*32)
        self.assertEqual(len(self.inputs), count)
        recipe['events'][0]['key'] = 'A'
        op['plan']['events'][0]['key'] = 'D'
        with self.assertRaises(UIError):
            self.player.timeline(plan(max_lateness=10), request_id='e'*32)
        self.api.advance(1)
        result = self.player.timeline(plan(), request_id='e'*32)
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(len(self.inputs), 4)
        self.assertEqual(self.result(op)['plan']['events'][0]['key'], 'W')
        self.assertNotIn('events', self.player.status(op['id']))
        self.assertNotIn('plan', self.player.snapshot()['last_action'])

    def test_alias_pairing_and_preflight_rejects_all_invalid_plans_without_input(self):
        valid = plan([event(0, 'key_down', 'CTRL'), event(10, 'key_up', 'CONTROL')])
        invalid = [plan([event(0, 'key_down', 'W')]),
                   plan([event(0, 'key_up', 'W')]),
                   plan([event(0, 'key_down', 'CTRL'), event(0, 'key_down', 'CONTROL')]),
                   plan([event(1, 'key_down', 'W'), event(0, 'key_up', 'W')]),
                   plan([event(-1, 'key_down', 'W'), event(1, 'key_up', 'W')]),
                   plan([event(True, 'key_down', 'W'), event(1, 'key_up', 'W')]),
                   plan([event(0, 'key_down', 'W'), event(120001, 'key_up', 'W')]),
                   plan([event(0, 'key_down', 'W+SPACE'), event(1, 'key_up', 'W+SPACE')]),
                   plan([event(0, 'key_down', 'UNKNOWN'), event(1, 'key_up', 'UNKNOWN')]),
                   plan([event(0, 'key_down', 'MOUSE_LEFT'), event(1, 'key_up', 'MOUSE_LEFT')]),
                   plan([event(0, 'wait', 'W')]), plan(extra=True), plan(max_lateness=-1),
                   plan(max_lateness=True), dict(plan(), schema_version=True),
                   dict(plan(), clock='client_tick'), dict(plan(), events=[]),
                   dict(plan(), events=valid['events']*129),
                   plan([dict(event(0, 'key_down', 'W'), unexpected=1)]),
                   {'events': []}, [], None]
        for recipe in invalid:
            with self.subTest(recipe=recipe), self.assertRaises(UIError):
                self.player.timeline(recipe)
        self.assertEqual(self.inputs, [])
        self.assertEqual(self.api.scheduled, [])
        op = self.player.timeline(valid)
        self.api.advance(.1)
        self.assertEqual(self.result(op)['state'], 'completed')

    def test_maximum_event_count_and_duration(self):
        recipe = plan([row for i in range(128) for row in
                       (event(i*2, 'key_down', 'W'), event(i*2+1, 'key_up', 'W'))])
        op = self.player.timeline(recipe)
        self.api.advance(.3)
        self.assertEqual(self.result(op)['index'], 256)
        self.assertFalse(self.result(op)['logs_truncated'])
        op = self.player.timeline(plan([event(0, 'key_down', 'W'), event(120000, 'key_up', 'W')]))
        self.api.advance(120.01)
        self.assertEqual(self.result(op)['state'], 'completed')

    def test_missing_capability_never_uses_wall_clock_fallback(self):
        self.player.timeline_clock = None
        self.assertFalse(self.player.capabilities()['capabilities']['timeline'])
        self.assertEqual(self.player.dispatch('timeline', plan=plan())['code'], 'not_supported')
        self.assertFalse(self.inputs)
        with patch.object(payload.time, 'monotonic', None), patch.object(payload.time, 'clock', lambda: 1, create=True):
            with patch.object(payload.sys, 'platform', 'darwin'):
                self.assertEqual(payload.key_timeline_clock(), (None, None))
            with patch.object(payload.sys, 'platform', 'win32'):
                self.assertEqual(payload.key_timeline_clock()[1], 'windows.time.clock')

    def test_cli_forwards_same_json_plan_and_explicit_request_id(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory)/'plan.json'
            filename.write_text(json.dumps(plan()), encoding='utf-8-sig')
            with patch('mcpywrap.mcstudio.runtime_ui.execute', return_value={'ok': True}) as execute:
                result = CliRunner().invoke(cli, ['--local', 'runtime', 'player', 'timeline', '--session', 'a'*32,
                                                  '--file', str(filename), '--request-id', 'b'*32, '--json'])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(execute.call_args.args[2:], ('timeline', {'plan': plan(), 'request_id': 'b'*32}))
            self.assertEqual(execute.call_args.kwargs['family'], 'player')

    def test_remote_transport_sends_one_plan_and_unknown_result_keeps_id(self):
        from mcpywrap.mcstudio.runtime_ui import execute
        with patch('mcpywrap.command_context.remote_url', return_value='http://remote'), \
             patch('mcpywrap.remote.client.Client') as client:
            client.return_value.request.side_effect = OSError('reply lost')
            result = execute(Path('.'), 'a'*32, 'timeline', {'plan': plan(), 'request_id': 'b'*32}, family='player')
            self.assertEqual(result['state'], 'unknown')
            self.assertEqual(result['operation'], 'b'*32)
            client.return_value.request.assert_called_once()
            args = client.return_value.request.call_args.args
            self.assertEqual(args[:2], ('POST', '/sessions/'+'a'*32+'/py'))
            self.assertEqual(args[2]['side'], 'client')
            self.assertIn("dispatch", args[2]['code'])

    def test_unconfirmed_install_stage_does_not_send_remaining_source(self):
        from mcpywrap.mcstudio.runtime_ui import execute
        with patch('mcpywrap.command_context.remote_url', return_value=None), \
             patch('mcpywrap.mcstudio.sessions.read', return_value={
                 'state': 'running', 'game': {'executable': 'D:/engine/test/Minecraft.Windows.exe'}}), \
             patch('mcpywrap.mcstudio.runtime_debug.control_request', return_value={
                 'state': 'unknown', 'side': 'client', 'request_id': 'stage'}) as request:
            result = execute(Path('.'), 'a'*32, 'install', family='player')
            self.assertEqual(result['state'], 'unknown')
            request.assert_called_once()

    def test_queued_install_stage_queries_original_request_before_final_install(self):
        from mcpywrap.mcstudio.runtime_ui import execute
        from mcpywrap.mcstudio.runtime_ui import install_sources
        replies = [{'state': 'queued', 'side': 'client', 'request_id': 'stage-id'}] + [
                   {'state': 'completed', 'side': 'client', 'value': {'ok': True, 'stage': 'staged'}}
                   for _ in install_sources('test')[:-1]] + [
                   {'state': 'completed', 'side': 'client', 'value': {
                       'ok': True, 'player_capabilities': {'timeline': True}, 'player_timeline': {'clocks': ['monotonic_ms']}}}]
        with patch('mcpywrap.command_context.remote_url', return_value=None), \
             patch('mcpywrap.mcstudio.sessions.read', return_value={
                 'state': 'running', 'game': {'executable': 'D:/engine/test/Minecraft.Windows.exe'}}), \
             patch('mcpywrap.mcstudio.runtime_debug.control_request', side_effect=replies) as request, \
             patch('mcpywrap.mcstudio.runtime_ui.time.sleep'):
            result = execute(Path('.'), 'a'*32, 'install', family='player')
            self.assertTrue(result['capabilities']['timeline'])
            self.assertEqual(result['timeline']['clocks'], ['monotonic_ms'])
            self.assertEqual(request.call_args_list[1].args[2], 'python-result')
            self.assertEqual(request.call_args_list[1].kwargs['request_id'], 'stage-id')
            self.assertNotEqual(request.call_args_list[0].kwargs['code'], request.call_args_list[2].kwargs['code'])


if __name__ == '__main__':
    unittest.main()

"""One timeline contract, shared Windows sender, real CLI/HTTP serialization elsewhere."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from click.testing import CliRunner
from mcpywrap.cli import cli
from mcpywrap.timeline import compile_timeline
from mcpywrap.mcstudio import input_sequence as seq, window


class TimelineTests(unittest.TestCase):
    def test_automatic_mixed_and_explicit_plans_have_identical_times(self):
        automatic = [{'action': 'key'}, {'action': 'wait', 'delay_ms': 5}, {'action': 'key'}]
        explicit = [{'action': 'key', 'at_ms': 0}, {'action': 'wait', 'at_ms': 15}, {'action': 'key', 'at_ms': 20}]
        mixed = [{'action': 'key'}, {'action': 'wait', 'at_ms': 15}, {'action': 'key'}]
        for plan in (automatic, explicit, mixed):
            self.assertEqual(compile_timeline(plan, [10, 5, 0], 100), explicit)
        self.assertNotIn('at_ms', automatic[0])

    def test_overlap_ambiguous_timing_and_non_integer_times_rejected(self):
        for plan in ([{'at_ms': 0}, {'at_ms': 5}], [{'delay_ms': True}],
                     [{'at_ms': 1, 'delay_ms': 0}], [{'at_ms': -1}], [{'at_ms': float('nan')}],
                     [{'at_ms': 99}]):
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                compile_timeline(plan, [10] * len(plan), 100)


class InputSequenceTests(unittest.TestCase):
    def target(self):
        target = window.GameWindow.__new__(window.GameWindow)
        target.foreground, target.check_foreground = Mock(), Mock()
        target.client_area = Mock(return_value=(800, 600, SimpleNamespace(x=20, y=30)))
        target._client_area = Mock(side_effect=target.client_area)
        target.game, target.owner = {'pid': 5}, Mock(return_value=5)
        target.user = Mock()
        target.user.GetAsyncKeyState.return_value = 0
        target.user.GetSystemMetrics.side_effect = {76: 0, 77: 0, 78: 1920, 79: 1080}.get
        target.user.MapVirtualKeyW.return_value = 49
        def cursor(point):
            point._obj.x, point._obj.y = 50, 60
            return True
        target.user.GetCursorPos.side_effect = cursor
        sent = []
        def send(count, pointer, size):
            events = [pointer._obj] if count == 1 else list(pointer)
            for event in events:
                sent.append(('key', event.keyboard.vk, event.keyboard.flags) if event.kind == 1 else
                            ('mouse', event.mouse.data, event.mouse.flags))
            return count
        target.user.SendInput.side_effect = send
        return target, sent

    def run_plan(self, target, plan, **kwargs):
        now = [1000000000]
        def clock():
            now[0] += 10000
            return now[0]
        with patch.object(seq.time, 'perf_counter_ns', side_effect=clock), \
             patch.object(seq.time, 'sleep', side_effect=lambda seconds: now.__setitem__(0, now[0] + round(seconds * 1e9))):
            return seq.run_sequence(target, plan, **kwargs)

    @staticmethod
    def keys():
        return [{'type': 'key_down', 'key': '1'}, {'type': 'key_up', 'key': '1', 'delay_ms': 5}]

    def test_default_compilation_and_real_send_bounds_no_fixed_gap(self):
        target, sent = self.target()
        plan = self.keys() + [{'type': 'mouse_down', 'button': 'right', 'at_ms': 10},
                              {'type': 'mouse_up', 'button': 'right', 'at_ms': 20}]
        result = self.run_plan(target, plan, width=800, height=600)
        self.assertTrue(result['ok'])
        target.foreground.assert_called_once()
        self.assertEqual(sent, [('key', 49, 0), ('key', 49, 2), ('mouse', 0, 8), ('mouse', 0, 16)])
        self.assertEqual([r['at_ms'] for r in result['plan']], [0, 5, 10, 20])
        for record in result['events']:
            self.assertLessEqual(record['scheduled_ns'], record['send_started_ns'])
            self.assertLessEqual(record['send_started_ns'], record['send_finished_ns'])
            self.assertLess(record['lateness_ms'], .15)
        self.assertFalse(result['effect_verified'])
        self.assertEqual(result['cleanup_events'], [])

    def test_same_timestamp_uses_one_batch_with_shared_call_bounds(self):
        target, sent = self.target()
        result = self.run_plan(target, [{'type': 'key_down', 'key': '1'}, {'type': 'key_up', 'key': '1'}])
        self.assertEqual([r['at_ms'] for r in result['plan']], [0, 0])
        self.assertEqual(result['events'][1]['interval_ms'], 0)
        self.assertEqual(result['events'][1]['batch_size'], 2)
        self.assertEqual(result['events'][0]['send_started_ns'], result['events'][1]['send_started_ns'])
        self.assertEqual(len(sent), 2)

    def test_partial_batch_does_not_invent_individual_acceptance(self):
        target, _ = self.target()
        target.user.SendInput.side_effect = [1, 1]
        result = self.run_plan(target, [{'type':'key_down','key':'1'}, {'type':'key_up','key':'1'}])
        self.assertEqual(result['state'], 'unknown')
        self.assertTrue(result['released'])
        self.assertTrue(all(r['accepted'] is None for r in result['events']))
        self.assertEqual(result['events'][0]['batch_inserted_count'], 1)

    def test_all_preflight_errors_precede_foreground_and_input(self):
        bad = [[], self.keys()[:1], [self.keys()[1]], self.keys() + self.keys()[:1],
               [{'type': 'key_down', 'key': 'CTRL+1'}],
               [{'type': 'wheel', 'delta': True}],
               [{'type': 'move', 'x': -1, 'y': 0}],
               [{'type': 'relative', 'dx': 1, 'dy': 2, 'extra': 1}],
               self.keys() * 129]
        for plan in bad:
            target, sent = self.target()
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                self.run_plan(target, plan, width=800, height=600)
            target.foreground.assert_not_called()
            self.assertFalse(sent)

    def test_alias_overlap_and_scan_representation_mixing_rejected(self):
        target, _ = self.target()
        for plan in ([{'type': 'key_down', 'key': 'CTRL'}, {'type': 'key_down', 'key': 'LCTRL'}],
                     self.keys() + [{'type': 'key_down', 'key': 'SC:0x02'}, {'type': 'key_up', 'key': 'SC:0x02'}]):
            with self.assertRaises(ValueError): self.run_plan(target, plan)
        target.foreground.assert_not_called()

    def test_held_inputs_and_mouse_geometry_abort_before_send(self):
        target, sent = self.target()
        target.user.GetAsyncKeyState.return_value = 0x8000
        with self.assertRaises(ValueError): self.run_plan(target, self.keys())
        target.user.GetAsyncKeyState.return_value = 0
        with self.assertRaises(ValueError): self.run_plan(target, [{'type': 'wheel', 'delta': 120}], width=900, height=600)
        self.assertFalse(sent)

    def test_focus_loss_releases_only_our_inputs_and_returns_partial_trace(self):
        target, sent = self.target()
        original = target.user.SendInput.side_effect
        def lose_focus(*args):
            result = original(*args)
            target.check_foreground.side_effect = ValueError('focus lost')
            return result
        target.user.SendInput.side_effect = lose_focus
        result = self.run_plan(target, self.keys())
        self.assertFalse(result['ok'])
        self.assertTrue(result['released'])
        self.assertEqual(sent, [('key', 49, 0), ('key', 49, 2)])
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['cleanup_events'][0]['type'], 'key_up')

    def test_failed_down_and_cleanup_failure_remain_unknown(self):
        target, _ = self.target()
        target.user.SendInput.side_effect = [0, 0]
        result = self.run_plan(target, self.keys())
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['code'], 'release_failed')
        self.assertFalse(result['released'])
        self.assertFalse(result['events'][0]['accepted'])
        self.assertFalse(result['cleanup_events'][0]['accepted'])

    def test_keyboard_interrupt_keeps_trace_and_releases(self):
        target, _ = self.target()
        target.user.SendInput.side_effect = [KeyboardInterrupt(), 1]
        result = self.run_plan(target, self.keys())
        self.assertEqual(result['state'], 'unknown')
        self.assertIsNone(result['events'][0]['accepted'])
        self.assertTrue(result['cleanup_events'][0]['accepted'])

    def test_deadline_miss_stops_remaining_and_still_releases(self):
        target, sent = self.target()
        result = self.run_plan(target, self.keys(), max_lateness_ms=0)
        self.assertEqual(result['code'], 'deadline_missed')
        self.assertFalse(sent)
        self.assertTrue(result['released'])

    def test_delay_after_first_down_aborts_before_up_and_cleans_up(self):
        target, sent = self.target()
        original = target.user.SendInput.side_effect
        def slow(*args):
            result = original(*args)
            if len(sent) == 1:
                seq.time.sleep(.02)
            return result
        target.user.SendInput.side_effect = slow
        result = self.run_plan(target, self.keys(), max_lateness_ms=1)
        self.assertEqual(result['code'], 'deadline_missed')
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(sent[-1], ('key',49,2))
        self.assertTrue(result['released'])

    def test_geometry_change_after_down_stops_and_releases(self):
        target, sent = self.target()
        original = target.user.SendInput.side_effect
        def resize(*args):
            result = original(*args)
            target._client_area = Mock(return_value=(900,600,SimpleNamespace(x=20,y=30)))
            return result
        target.user.SendInput.side_effect = resize
        result = self.run_plan(target, [{'type':'mouse_down','button':'left'},
                                       {'type':'mouse_up','button':'left','delay_ms':5}], width=800,height=600)
        self.assertFalse(result['ok'])
        self.assertTrue(result['released'])
        self.assertEqual(sent, [('mouse',0,2), ('mouse',0,4)])

    def test_move_relative_and_wheel_are_separate_batches_with_correct_payloads(self):
        target, sent = self.target()
        plan=[{'type':'move','x':200,'y':100}, {'type':'relative','dx':-7,'dy':2},
              {'type':'wheel','delta':-120}]
        result=self.run_plan(target,plan,width=800,height=600)
        self.assertTrue(result['ok'])
        self.assertEqual([r['batch_size'] for r in result['events']], [1,1,1])
        self.assertEqual([r[-1] for r in sent], [0xC001,1,0x800])
        self.assertEqual(sent[-1][1], (-120)&0xFFFFFFFF)

    def test_mouse_cursor_outside_target_is_rejected(self):
        target, sent = self.target()
        target.owner.return_value = 999
        result = self.run_plan(target, [{'type': 'mouse_down', 'button': 'left'},
                                       {'type': 'mouse_up', 'button': 'left'}], width=800, height=600)
        self.assertFalse(result['ok'])
        self.assertFalse(sent)

    def test_cli_reads_bom_file_locally_and_preserves_failure_trace(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'plan.json'
            path.write_text(json.dumps(self.keys()), encoding='utf-8-sig')
            with patch.object(window, 'operate', return_value={'ok': False, 'events': [{'accepted': False}]}) as call:
                result = CliRunner().invoke(cli, ['--local', 'input-sequence', '--file', str(path), '--session', 'a'*32, '--json'])
            self.assertNotEqual(result.exit_code, 0)
            self.assertEqual(json.loads(result.output)['events'], [{'accepted': False}])
            self.assertEqual(call.call_args.args[3]['events'], self.keys())


if __name__ == '__main__':
    unittest.main()

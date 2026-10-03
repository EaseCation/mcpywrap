"""Opt-in real SendInput and receipt evidence in an owned, inert Windows fixture."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from mcpywrap.mcstudio.input_sequence import run_sequence
from mcpywrap.mcstudio.window import GameWindow, desktop_input_lock


@unittest.skipUnless(os.name == 'nt' and os.environ.get('MCPY_NATIVE_TESTS') == '1', 'opt-in interactive Windows desktop')
class NativeInputSequenceTests(unittest.TestCase):
    def test_zero_to_twenty_ms_submissions_and_receiver_event_order(self):
        import psutil
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = root/'receiver.json'
            env = dict(os.environ, QT_QPA_PLATFORM='windows')
            child = subprocess.Popen([sys.executable, str(Path(__file__).with_name('manual_input_window.py')),
                                      '--state', str(state)], env=env, creationflags=subprocess.CREATE_NO_WINDOW)
            target = None
            try:
                deadline = time.monotonic() + 8
                while not state.exists() and time.monotonic() < deadline:
                    self.assertIsNone(child.poll())
                    time.sleep(.05)
                self.assertTrue(state.exists())
                receiver = json.loads(state.read_text(encoding='utf-8'))
                self.assertIn(receiver['pid'], [child.pid] + [p.pid for p in psutil.Process(child.pid).children(recursive=True)])
                process = psutil.Process(receiver['pid'])
                # Test the shared Windows backend against our own receiver,
                # preserving process identity checks. Public CLI remains game-only.
                target = GameWindow({'pid': process.pid, 'created_at': process.create_time(), 'executable': process.exe()})
                width, height, _ = target._client_area(require_foreground=False, require_uncovered=False)
                plan = [{'type': 'move', 'x': width//2, 'y': height//2}]
                for i, gap in enumerate((0, 1, 5, 10, 20)):
                    base = 20 + i * 80
                    plan += [{'type': 'key_down', 'key': str(i+1), 'at_ms': base},
                             {'type': 'key_up', 'key': str(i+1), 'at_ms': base},
                             {'type': 'mouse_down', 'button': 'right', 'at_ms': base+gap},
                             {'type': 'mouse_up', 'button': 'right', 'at_ms': base+gap}]
                with desktop_input_lock():
                    result = run_sequence(target, plan, width, height)
                self.assertTrue(result['ok'], result)
                self.assertTrue(result['released'])
                self.assertEqual(result['accepted_events'], len(plan))
                deadline = time.monotonic() + 4
                received = []
                while time.monotonic() < deadline:
                    try:
                        received = json.loads(state.with_suffix('.events.json').read_text())
                    except (OSError, ValueError):
                        pass
                    if len(received) >= 20:
                        break
                    time.sleep(.02)
                self.assertEqual([r['type'] for r in received], ['key_down','key_up','mouse_down','mouse_up']*5)
                self.assertEqual([r['value'] for r in received if r['type']=='key_down'], list(range(49,54)))
                for event in result['events']:
                    self.assertLessEqual(event['scheduled_ns'], event['send_started_ns'])
                    self.assertLessEqual(event['send_started_ns'], event['send_finished_ns'])
                # No brittle real-time deadline assertion: measured jitter is evidence.
                evidence = {'result': result, 'receiver': received, 'gaps': []}
                for i, gap in enumerate((0,1,5,10,20)):
                    key, mouse = result['events'][1+i*4], result['events'][3+i*4]
                    evidence['gaps'].append({'requested_ms': gap,
                        'submitted_ms': (mouse['send_started_ns']-key['send_started_ns'])/1e6,
                        'received_ms': (received[2+i*4]['received_ns']-received[i*4]['received_ns'])/1e6})
                destination = os.environ.get('MCPY_INPUT_TEST_REPORT')
                if destination:
                    with Path(destination).open('x', encoding='utf-8') as stream:
                        json.dump(evidence, stream, ensure_ascii=False, indent=2)
                print(json.dumps({'native_input_gaps': evidence['gaps']}))
            finally:
                if target:
                    target.close()
                state.with_suffix('.stop').touch()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    child.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()

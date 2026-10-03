"""Public CLI timing check in an owned game: empty slots 8/9 and air clicks only."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Output must be new')
    prefix = [sys.executable, '-X', 'utf8', '-m', 'mcpywrap', '--local', '--project', args.project]
    history = []

    def call(*command):
        process = subprocess.run(prefix + list(command) + ['--session', args.session, '--json'],
                                 capture_output=True, encoding='utf-8', timeout=40)
        result = json.loads(process.stdout)
        history.append({'command': command, 'result': result})
        if process.returncode or not result.get('ok'):
            raise RuntimeError(result)
        return result

    before = None
    error = None
    result = None
    try:
        call('runtime', 'install')
        before = call('runtime', 'player', 'snapshot')
        assert before['screen'] == 'hud_screen'
        assert not before['hotbar'][7]['item'] and not before['hotbar'][8]['item'], 'Slots 8/9 must be empty'
        call('runtime', 'player', 'look', '--pitch', '-80', '--yaw', '0')
        state = call('runtime', 'player', 'snapshot')
        assert state['target']['type'] == 'None', 'Need empty sky without a target'
        capture = call('screenshot', '--background-only', '--output', str(args.output.with_suffix('.png')))
        size = [capture['width'], capture['height']]
        plan = []
        for i, gap in enumerate((0, 1, 5, 10, 20)):
            at = i * 80
            key = '8' if i % 2 == 0 else '9'
            plan += [{'type': 'key_down', 'key': key, 'at_ms': at},
                     {'type': 'key_up', 'key': key},
                     {'type': 'mouse_down', 'button': 'right', 'delay_ms': gap},
                     {'type': 'mouse_up', 'button': 'right'}]
        result = call('input-sequence', '--events', json.dumps(plan), '--width', str(size[0]), '--height', str(size[1]))
        assert result['released'] and result['accepted_events'] == len(plan)
        after = call('runtime', 'player', 'snapshot')
        assert after['selected_slot'] == 8 and after['carried'] is None
        assert after['hotbar'] == before['hotbar']
        # The same default compiler also drives the injected Python 2 backend.
        queued = call('runtime', 'player', 'sequence', '--steps', json.dumps([
            {'action':'select_slot','slot':9}, {'action':'wait','duration_ms':20},
            {'action':'select_slot','slot':8,'at_ms':100}]))
        deadline = time.monotonic() + 5
        while queued['state'] == 'pending' and time.monotonic() < deadline:
            time.sleep(.1)
            queued = call('runtime', 'player', 'status', '--operation', queued['id'])
        assert queued['state'] == 'completed' and queued['index'] == 3
        assert [s['at_ms'] for s in queued['plan']] == [0,0,100]
    except Exception as exc:
        error = str(exc)
    finally:
        if before:
            try:
                call('runtime', 'player', 'stop')
                call('runtime', 'player', 'select-slot', str(before['selected_slot']))
                call('runtime', 'player', 'look', '--pitch', str(before['rotation']['pitch']), '--yaw', str(before['rotation']['yaw']))
            except Exception as exc:
                error = (error or '') + '; restore: ' + str(exc)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({'ok': error is None, 'error': error, 'history': history},
                                         ensure_ascii=False, indent=2), encoding='utf-8')
    gaps = []
    if result:
        for i, gap in enumerate((0,1,5,10,20)):
            events = result['events']
            gaps.append({'requested_ms': gap, 'submitted_ms': (events[i*4+2]['send_started_ns']-events[i*4]['send_started_ns'])/1e6})
    print(json.dumps({'ok':error is None, 'error':error, 'gaps':gaps}, ensure_ascii=False))
    return int(error is not None)


if __name__ == '__main__':
    raise SystemExit(main())

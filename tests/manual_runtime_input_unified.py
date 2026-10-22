"""可选统一输入实机验收；显式运行，使用专用测试世界，默认测试不会启动游戏。"""
import argparse
import json
import math
from pathlib import Path
import sys
import time
import uuid

from manual.runtime_controls.support import invoke_json


def require(condition, message):
    if not condition: raise RuntimeError(message)


class LiveInput:
    def __init__(self, args):
        self.args = args
        self.output = Path(args.output).resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.session = args.session
        self.owned = False
        self.fixture = self.probe = False
        self.report = {'ok': False, 'optional_manual_test': True, 'cases': [], 'history': [], 'cleanup': []}
        self.prefix = [sys.executable, '-X', 'utf8', '-m', 'mcpywrap_core', '--local', '--project',
                       str(Path(args.project).resolve()), '--non-interactive']

    def call(self, *args, session=True, allow_failure=False, timeout=60):
        command = self.prefix+list(args)+(['--session', self.session] if session else [])+['--json']
        result, code = invoke_json(command, timeout=timeout, history=self.report['history'])
        require(allow_failure or (code == 0 and result.get('ok')), str(result))
        return result

    def py(self, code=None, filename=None, side='client'):
        args = ['runtime', 'py', '--side', side]+(['--file', str(filename)] if filename else ['--code', code])
        result = self.call(*args)
        require(result.get('state') == 'completed', 'Python result unconfirmed')
        return result.get('value')

    def input(self, *args, **kwargs): return self.call('runtime', 'input', *args, **kwargs)

    def wait(self, operation):
        deadline = time.monotonic()+15
        while operation['state'] == 'pending' and time.monotonic() < deadline:
            time.sleep(.1)
            operation = self.input('status', '--operation', operation['operation_id'], '--details', allow_failure=True)
        return operation

    def run_plan(self, name, steps, backend='game', request_id=None, **extra):
        recipe = dict(schema_version=1, backend=backend, steps=steps, **extra)
        path = self.output/(name+'.plan.json')
        path.write_text(json.dumps(recipe, ensure_ascii=False, indent=2), encoding='utf8')
        rid = request_id or uuid.uuid4().hex
        operation = self.input('run', '--file', str(path), '--request-id', rid)
        result = self.wait(operation)
        (self.output/(name+'.result.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
        require(result['state'] == 'completed' and result['released'] and not result['logs_truncated'], 'Operation did not complete with full evidence: '+str(result))
        return result

    def case(self, name, function):
        result = function()
        self.report['cases'].append({'name': name, 'state': 'passed', 'details': result})
        print(name+': passed', flush=True)

    def hud(self):
        for _ in range(6):
            if self.input('observe')['view'] == 'player': return
            self.py('mcpy.api.PopTopUI()\n_result=True'); time.sleep(.3)
        raise RuntimeError('HUD not reached')

    def overlap(self):
        self.py('_result=manual_fixture.reset_player()', side='server')
        time.sleep(.2)
        rid = uuid.uuid4().hex
        self.py("import sys\n_result=sys.modules['_mcpy_optional_unified_input_probe'].probe.start("+repr(rid)+')')
        result = self.run_plan('overlap-'+rid, [
            {'action': 'key_down', 'key': 'W'}, {'action': 'key_down', 'key': 'SPACE', 'at_ms': 500},
            {'action': 'key_up', 'key': 'SPACE', 'at_ms': 700}, {'action': 'key_up', 'key': 'W', 'at_ms': 2000}], request_id=rid)
        observation = self.py("import sys\n_result=sys.modules['_mcpy_optional_unified_input_probe'].probe.stop()")
        (self.output/(rid+'.observed.json')).write_text(json.dumps(observation, ensure_ascii=False, indent=2), encoding='utf8')
        samples = observation['samples']; require(samples and not observation['truncated'], 'No complete observation')
        height = max(s['position'][1] for s in samples)-samples[0]['position'][1]
        held_jump_seen = False; after = []
        for sample in samples:
            if 'SPACE' in sample['held_keys']: held_jump_seen = True
            if held_jump_seen and sample['held_keys'] == ['W']: after.append(sample)
        require(height > .2 and len(after) >= 3, 'No real jump or independent W-only interval')
        delta = math.hypot(after[-1]['position'][0]-after[0]['position'][0], after[-1]['position'][2]-after[0]['position'][2])
        require(delta > .2, 'No continued motion after SPACE release')
        expected = [(r['key'], r['action']) for r in result['events']]
        require(expected == [('W', 'key_down'), ('SPACE', 'key_down'), ('SPACE', 'key_up'), ('W', 'key_up')], 'Order changed')
        require(all(abs(v) < .01 for v in self.input('observe')['input_vector']), 'Input remained held')
        return {'height': height, 'movement_after_space_up': delta, 'operation_id': rid}

    def mixed_attack(self):
        self.py("_result=manual_fixture.spawn_target('adult')", side='server')
        # Teleport and entity geometry reach the client on later frames. Aim
        # only after observing the reset, then require the real crosshair hit.
        position = self.py('_result=manual_fixture.position()', side='server')
        deadline = time.monotonic()+8
        while True:
            state = self.input('observe')
            if all(abs(state['position'][i]-position[i]) < .3 for i in range(3)): break
            require(time.monotonic() < deadline, 'Client did not observe fixture teleport')
            time.sleep(.1)
        target = self.py('_result=manual_fixture.target_geometry()', side='server')
        self.run_plan('aim', [{'action': 'player.select_slot', 'slot': 2},
                              dict(action='player.look_at', **dict(zip(('x', 'y', 'z'), target['aim'])))])
        while True:
            state = self.input('observe')
            if state['target'].get('entityId') == target['entity']: break
            require(time.monotonic() < deadline, 'Crosshair did not acquire fixture target: '+str(state))
            time.sleep(.1)
        before = self.py('_result=manual_fixture.health()', side='server')
        self.py('manual_fixture.events=[]\n_result=True', side='server')
        result = self.run_plan('mixed-attack', [{'action': 'key_down', 'key': 'W'},
            {'action': 'player.attack', 'at_ms': 200, 'expect': {'target': {'type': 'Entity', 'entityId': target['entity']}}},
            {'action': 'key_up', 'key': 'W', 'at_ms': 600}])
        after = self.py('_result=manual_fixture.health()', side='server')
        events = self.py('_result=manual_fixture.readback()', side='server')['events']
        require(after < before and any(e.get('cause') == 'entity_attack' and e.get('damage', 0) > 0 and
                e.get('srcId') == state['player_id'] and e.get('entityId') == target['entity'] for e in events),
                'No attributed server damage during held W')
        return {'before_health': before, 'after_health': after, 'operation_id': result['operation_id']}

    def menu(self):
        # T 会引发计划取消，但必须清理自己的边沿；当前菜单 ESC 同样允许。
        path = self.output/'chat.plan.json'; path.write_text(json.dumps({'schema_version': 1, 'steps': [{'action': 'key', 'keys': ['T'], 'duration_ms': 80}]}))
        result = self.wait(self.input('run', '--file', str(path)))
        time.sleep(.5)
        observed = self.input('observe')
        require(observed['view'] == 'ui' and 'chat' in observed['screen'], 'Chat did not open')
        require(result['released'], 'Open-chat key not released')
        result = self.wait(self.input('key', 'ESC', '--duration-ms', '80'))
        time.sleep(.5)
        require(result['released'] and self.input('observe')['view'] == 'player', 'Menu ESC did not return HUD')
        return {'menu': observed['screen']}

    def ui_click(self):
        self.py('mcpy.api.OpenPauseGui()\n_result=True'); time.sleep(.5)
        observed = self.input('observe', '--view', 'ui', '--details')
        node = next(n for n in observed['nodes'] if n['role'] == 'button' and n['name'] == '设置')
        result = self.run_plan('ui-modifier-click', [{'action': 'ui.click', 'node': node['id'], 'snapshot': observed['snapshot'], 'keys': ['CTRL']}])
        time.sleep(.8)
        screen = self.input('observe')['screen']
        require('settings' in screen, 'Settings did not open')
        self.hud()
        return {'screen': screen, 'operation_id': result['operation_id']}

    def cancel_held(self):
        self.py('_result=manual_fixture.reset_player()', side='server')
        path = self.output/'cancel-held.plan.json'
        path.write_text(json.dumps({'schema_version': 1, 'steps': [
            # Sneak prevents walking off the finite elevated test arena while
            # host CLI queries are in flight; cancel must release both keys.
            {'action': 'key', 'keys': ['SHIFT', 'W'], 'duration_ms': 10000}]}))
        operation = self.input('run', '--file', str(path))
        deadline = time.monotonic()+5
        while not operation.get('held_keys') and time.monotonic() < deadline:
            operation = self.input('status', '--operation', operation['operation_id'])
        require(operation.get('held_keys') == ['SHIFT', 'W'], 'Both keys were not held before cancellation')
        cancelled = self.wait(self.input('cancel', '--operation', operation['operation_id']))
        require(cancelled['state'] == 'cancelled' and cancelled['released'], 'Cancellation did not release W')
        require(all(abs(v) < .01 for v in self.input('observe')['input_vector']), 'Input remained held after cancellation')
        return {'operation_id': operation['operation_id'], 'released': True}

    def monotonic_clock(self):
        started = time.monotonic()
        before = self.py('_result=mcpy.input.adapter.clock()')
        time.sleep(.3)
        after = self.py('_result=mcpy.input.adapter.clock()')
        require(.3 <= after-before <= time.monotonic()-started+.1, 'Clock did not advance while idle')
        # Change only the temporary Python wall-clock callable, never the OS
        # clock. Scheduling must continue using the native elapsed-time source.
        wall = self.py("import time\n_saved_wall=time.time\ntry:\n time.time=lambda: -1000000000.0\n _a=mcpy.input.adapter.clock()\n time.time=lambda: 1000000000.0\n _b=mcpy.input.adapter.clock()\n _result=_b-_a\nfinally:\n time.time=_saved_wall")
        require(0 <= wall < 1, 'Wall-clock change affected the input clock')
        self.py('mcpy.api.OpenPauseGui()\n_result=True')
        paused_before = self.py('_result=mcpy.input.adapter.clock()')
        time.sleep(.3)
        paused_after = self.py('_result=mcpy.input.adapter.clock()')
        self.hud()
        require(paused_after-paused_before >= .3, 'Clock stopped in pause menu')
        return {'idle_seconds': after-before, 'wall_change_delta': wall,
                'pause_seconds': paused_after-paused_before}

    def windows(self):
        result = self.run_plan('windows-order', [{'action': 'key', 'keys': ['W', 'CTRL'], 'duration_ms': 200}], backend='windows-sendinput')
        require([r['key'] for r in result['events']] == ['W', 'CTRL', 'CTRL', 'W'], 'Windows order changed')
        repeat_path = self.output/'windows-order.plan.json'
        repeat = self.input('run', '--file', str(repeat_path), '--request-id', result['request_id'])
        require(repeat['operation_id'] == result['operation_id'] and repeat['state'] == 'completed', 'Windows idempotency failed')
        return {'operation_id': result['operation_id'], 'input_paths': sorted(set(r['input_path'] for r in result['events']))}

    def run(self):
        try:
            if self.args.launch:
                result = self.call('run', '--new', '--world-type', 'flat', '--game-type', 'survival', '--difficulty', 'peaceful',
                    '--no-mob-spawn', '--no-gui', '--detach', '--engine-version', self.args.engine_version, session=False)
                self.session, self.owned = result['session'], True
            deadline = time.monotonic()+180
            while True:
                session = self.call('status')
                if session.get('world_ready'): break
                # macOS status reports process state; verify HUD through the
                # public client channel instead of waiting on a Windows field.
                if session.get('backend') == 'macos-arm64':
                    ready = self.call('runtime', 'py', '--side', 'client', '--code',
                        "import mod.client.extraClientApi as api, gui\n_result = api.GetLevelId() not in (None, -1, '-1') and gui.get_top_screen() == 'hud_screen'",
                        allow_failure=True, timeout=max(1, deadline-time.monotonic()))
                    if ready.get('state') == 'completed' and ready.get('value') is True: break
                require(time.monotonic() < deadline, 'World not ready'); time.sleep(.5)
            self.report.update(session=self.session, engine=session.get('launch', {}).get('engine_version') or
                               Path(session['game']['executable']).parent.name)
            self.call('runtime', 'install')
            caps = self.input('capabilities'); self.report['capabilities'] = caps
            require(caps['actions']['key']['supported'], 'Missing unified game clock/key capability')
            if session.get('backend') == 'macos-arm64':
                require(caps['clock_source'] == 'launcher.steady_clock', 'Native macOS clock was not selected')
            self.case('monotonic-clock', self.monotonic_clock)
            self.py(filename=Path(__file__).parent/'manual/runtime_controls/server_fixture.py', side='server'); self.fixture = True
            self.py(filename=Path(__file__).parent/'manual/runtime_controls/input_probe.py'); self.probe = True
            self.run_plan('initial-look', [{'action': 'player.look', 'pitch': 0, 'yaw': 0}])
            for i in range(3): self.case('overlap-'+str(i+1), self.overlap)
            self.case('cancel-held', self.cancel_held)
            self.case('mixed-held-attack', self.mixed_attack)
            self.case('menu-keys', self.menu)
            self.case('ui-modifier-click', self.ui_click)
            if self.args.windows_device:
                require(sys.platform == 'win32', 'Windows device test requested on another platform')
                self.case('windows-device-order', self.windows)
            self.report['ok'] = True
        except Exception as error:
            self.report['error'] = str(error)
        finally:
            def clean(name, function):
                try: self.report['cleanup'].append({'name': name, 'result': function()})
                except Exception as error:
                    self.report['cleanup'].append({'name': name, 'error': str(error)}); self.report['ok'] = False
            if self.session:
                clean('input-release', lambda: self.input('stop'))
                if self.probe: clean('observation', lambda: self.py("import sys\n_result=sys.modules['_mcpy_optional_unified_input_probe'].probe.close()"))
                if self.fixture: clean('fixture', lambda: self.py('_result=manual_fixture.cleanup()', side='server'))
                if self.owned: clean('owned-session', lambda: self.call('stop'))
            (self.output/'report.json').write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps({'ok': self.report['ok'], 'error': self.report.get('error'), 'output': str(self.output)}, ensure_ascii=False))
        return 0 if self.report['ok'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    ownership = parser.add_mutually_exclusive_group(required=True)
    ownership.add_argument('--session'); ownership.add_argument('--launch', action='store_true')
    parser.add_argument('--engine-version'); parser.add_argument('--output', required=True)
    parser.add_argument('--prepare-fixture', action='store_true', help='允许修改专用测试世界的地形、位置、模式、物品')
    parser.add_argument('--windows-device', action='store_true', help='明确允许占用Windows前台做特殊设备测试')
    args = parser.parse_args()
    if not args.prepare_fixture: parser.error('需要 --prepare-fixture 和专用测试世界')
    if args.launch and not args.engine_version: parser.error('--launch需要固定已安装引擎版本')
    return LiveInput(args).run()


if __name__ == '__main__': raise SystemExit(main())

"""OPTIONAL live runtime tests. Never run by unittest discovery or normal mcpy startup."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

from support import invoke_json

ROOT = Path(__file__).resolve().parent
TESTS = ROOT.parents[1]
UNSUPPORTED = {'unsupported_ui', 'unsupported_capability', 'unsupported_feature'}


class UnsupportedCase(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class LiveTests:
    def __init__(self, args):
        self.args = args
        self.project = Path(args.project).resolve()
        self.output = Path(args.output).resolve()
        self.session = args.session
        self.owned = False
        self.fixture_attempted = False
        self.report = {'optional_manual_test': True, 'ok': False, 'platform': sys.platform,
                       'project': str(self.project), 'cases': [], 'history': [], 'cleanup': [],
                       'desktop_foreground_verified': False}
        self.prefix = [sys.executable, '-X', 'utf8', '-m', 'mcpywrap', '--local',
                       '--project', str(self.project), '--non-interactive']

    def call(self, *arguments, session=True, allow_failure=False):
        command = self.prefix + list(arguments)
        if session:
            command += ['--session', self.session]
        result, code = invoke_json(command + ['--json'], self.args.timeout, self.report['history'])
        if not allow_failure and (code or not result.get('ok')):
            error = json.dumps(result, ensure_ascii=False)
            if result.get('code') in UNSUPPORTED:
                raise UnsupportedCase(error)
            raise RuntimeError(error)
        return result

    def py(self, code, side='client'):
        result = self.call('runtime', 'py', '--side', side, '--code', code)
        require(result.get('state') == 'completed', 'Python result is not confirmed: '+str(result))
        return result.get('value')

    def player(self, *arguments):
        return self.call('runtime', 'player', *arguments)

    def action(self, *arguments):
        result = self.player(*arguments)
        deadline = time.monotonic()+self.args.timeout
        while result.get('state') == 'pending' and time.monotonic() < deadline:
            time.sleep(.25)
            result = self.player('status', '--operation', result['id'], '--details')
        require(result.get('state') == 'completed', 'Action did not complete: '+str(result))
        return result

    def observe(self, predicate, timeout=None):
        deadline = time.monotonic()+(self.args.timeout if timeout is None else timeout)
        while True:
            state = self.player('snapshot')
            if predicate(state):
                return state
            if time.monotonic() >= deadline:
                raise RuntimeError('Player did not reach expected state: '+str(state))
            time.sleep(.25)

    def server(self, expression):
        return self.py('_result = manual_fixture.'+expression, 'server')

    def hud(self):
        for _ in range(6):
            if self.py('_result = mcpy.api.GetTopUI()') in ('hud_screen', 'ui://./hbui/gameplay.html'):
                return
            self.py('_result = mcpy.api.PopTopUI()')
            time.sleep(.25)
        raise RuntimeError('Close game menus before running the player suite')

    def case(self, name, function):
        entry = {'name': name}
        started = time.monotonic()
        try:
            value = function()
            entry.update(state='passed', details=value)
        except UnsupportedCase as error:
            entry.update(state='skipped', reason=str(error))
        except Exception as error:
            entry.update(state='failed', error=str(error))
        entry['elapsed_seconds'] = time.monotonic()-started
        self.report['cases'].append(entry)
        print(name+': '+entry['state'], flush=True)
        return entry['state']

    def child(self, name, *arguments):
        output = self.output.with_name(self.output.stem+'-'+name+'.json')
        command = [sys.executable, '-X', 'utf8', str(TESTS/('manual_runtime_'+name+'.py')),
                   '--project', str(self.project), '--session', self.session,
                   '--output', str(output), *arguments]
        if self.args.require_background:
            command.append('--require-background')
        process = subprocess.run(command, capture_output=True, encoding='utf-8', errors='replace',
                                 timeout=max(180, self.args.timeout*4))
        log = output.with_suffix('.log')
        log.write_text(process.stdout+process.stderr, encoding='utf-8')
        require(output.is_file(), 'Manual helper produced no report: '+process.stdout+process.stderr)
        result = json.loads(output.read_text(encoding='utf-8'))
        self.report['history'].extend(result.get('history', []))
        if not result.get('ok') or process.returncode:
            message = str(result.get('error') or process.stderr)
            if any(code in message for code in UNSUPPORTED):
                raise UnsupportedCase(message)
            raise RuntimeError(message)
        if self.args.require_background:
            self.report['desktop_foreground_verified'] = True
        return {'report': str(output)}

    def probe(self):
        deadline = time.monotonic()+self.args.timeout
        ready_code = "import mod.client.extraClientApi as api, gui\n_result = api.GetLevelId() not in (None, -1, '-1') and gui.get_top_screen() in ('hud_screen', 'ui://./hbui/gameplay.html')"
        while True:
            ready = self.call('runtime', 'py', '--code', ready_code, allow_failure=True)
            if ready.get('state') == 'completed' and ready.get('value') is True:
                break
            require(ready.get('state') in ('completed', 'unavailable'), 'Readiness result is unconfirmed: '+str(ready))
            require(time.monotonic() < deadline, 'World/HUD did not become ready')
            time.sleep(.5)
        self.call('runtime', 'install')
        result = self.call('runtime', 'py', '--file', str(ROOT/'client_probe.py'))
        self.probe_result = result['value']
        if self.data.get('mode') == 'local':
            self.report['server_probe'] = self.py(
                "import mod.server.extraServerApi as api\n_result = {'world': api.GetLevelId(), 'players': api.GetPlayerList()}", 'server')
        return self.probe_result

    def ui(self):
        capabilities = self.probe_result['ui']['capabilities']
        if not all(capabilities.get(key) for key in ('snapshot', 'click', 'scroll', 'slide')):
            raise UnsupportedCase('Required native UI methods are unavailable: '+str(capabilities))
        return self.child('ui')

    def prepare(self):
        if self.data.get('mode') != 'local':
            raise UnsupportedCase('Server fixture requires a local world; network servers are never modified')
        self.hud()
        require(self.player('snapshot')['dimension'] == 0, 'Server fixture only supports an Overworld test arena')
        self.fixture_attempted = True
        result = self.call('runtime', 'py', '--side', 'server', '--file', str(ROOT/'server_fixture.py'))
        fixture = result['value']
        require(fixture.get('ok'), 'Server fixture preparation failed: '+str(fixture))
        self.origin = fixture['origin']
        self.position = fixture['position']
        self.observe(lambda state: all(abs(state['position'][i]-self.position[i]) < .3 for i in range(3))
                     and state['hunger'] == 10 and state['arrows'] == 16
                     and (state['hotbar'][2]['item'] or {}).get('count') == 3)
        return fixture

    def movement(self):
        caps = self.probe_result['player']['capabilities']
        if not all(caps.get(key) for key in ('sequence', 'look', 'move', 'key', 'sneak', 'jump')):
            raise UnsupportedCase('Required game-native movement methods unavailable: '+str(caps))
        self.server('reset_player()')
        self.observe(lambda s: all(abs(s['position'][i]-self.position[i]) < .3 for i in range(3)))
        job = self.action('sequence', '--file', str(ROOT/'movement.json'))
        state = self.player('snapshot')
        require(not any(abs(value)>.01 for value in state['input_vector'])
                and not state['sneaking'] and not state['sprinting'], 'Movement input was not released')
        return {'steps': job['index'], 'released': True}

    def food(self):
        caps = self.probe_result['player']['capabilities']
        if not all(caps.get(key) for key in ('sequence', 'select_slot', 'eat', 'shoot', 'look')):
            raise UnsupportedCase('Food/bow methods unavailable: '+str(caps))
        before = self.server('readback()')
        client = self.child('player', '--food-slot', '3', '--bow-slot', '4')
        deadline = time.monotonic()+self.args.timeout
        while True:
            after = self.server('readback()')
            food_count = (after.get('food') or {}).get('count')
            arrow_count = (after.get('arrows') or {}).get('count')
            if after['hunger'] > before['hunger'] and food_count == 2 and arrow_count == 15:
                return dict(client, server_before=before, server_after=after)
            if time.monotonic() >= deadline:
                raise RuntimeError('Server did not confirm food/arrow changes: '+str(after))
            time.sleep(.25)

    def attack_and_bow(self):
        return {age: self.attack_and_bow_for_age(age) for age in ('adult', 'baby')}

    def attack_and_bow_for_age(self, age):
        caps = self.probe_result['player']['capabilities']
        if not all(caps.get(key) for key in ('attack', 'shoot', 'select_slot', 'look_at')):
            raise UnsupportedCase('Target interaction methods unavailable: '+str(caps))
        self.server('spawn_target('+repr(age)+')')
        # Component-group age changes apply on the next engine frame.
        time.sleep(.25)
        target = self.server('target_geometry()')
        require((target['collision_size'][1] < 1.) == (age == 'baby'), 'Fixture age did not take effect: '+str(target))
        collision_size = target['collision_size']
        self.observe(lambda s: all(abs(s['position'][i]-self.position[i]) < .3 for i in range(3)))
        self.action('select-slot', '2')
        self.action('look-at', *map(str, target['aim']))
        state = self.observe(lambda s: s['target'].get('entityId') == target['entity'], timeout=8)
        require((state.get('carried') or {}).get('name') == 'minecraft:wooden_sword', 'Expected wooden sword')
        health_before = self.server('health()')
        require(health_before == target['health'], 'Target was damaged before the automatic attack; discard this run')
        self.py('manual_fixture.events = []\n_result = True', 'server')
        started = time.monotonic()
        self.action('attack', '--snapshot', state['snapshot'])
        while True:
            attacked = self.server('health()')
            melee_events = [event for event in self.server('readback()')['events']
                            if event.get('cause') == 'entity_attack' and event.get('damage', 0) > 0
                            and event.get('srcId') == state['player_id'] and event.get('entityId') == target['entity']]
            if attacked < health_before and melee_events:
                break
            require(time.monotonic()-started < 5, 'No attributed automatic melee damage within 5 seconds')
            time.sleep(.25)
        melee_seconds = time.monotonic()-started
        target = self.server('aim_for_bow()')
        time.sleep(.5)
        self.action('select-slot', '4')
        self.action('look-at', *map(str, target['aim']))
        state = self.observe(lambda s: s['target'].get('type') == 'Entity')
        self.action('shoot', '--snapshot', state['snapshot'], '--hold-ms', '1200')
        deadline = time.monotonic()+self.args.timeout
        while True:
            events = self.server('readback()')['events']
            hits = [event for event in events if event.get('cause') == 'projectile'
                    and event.get('srcId') == state['player_id'] and event.get('projectileId')]
            if hits:
                return {'age': age, 'collision_size': collision_size, 'health_before_attack': health_before, 'health_after_attack': attacked,
                        'melee_events': melee_events, 'melee_seconds': melee_seconds, 'projectile_events': hits}
            require(time.monotonic() < deadline, 'Server did not observe projectile damage: '+str(events))
            time.sleep(.25)

    def place_and_dig(self):
        caps = self.probe_result['player']['capabilities']
        if not all(caps.get(key) for key in ('use_block', 'dig', 'look_at', 'select_slot')):
            raise UnsupportedCase('Block interaction methods unavailable: '+str(caps))
        block = self.server('prepare_block()')
        self.observe(lambda s: all(abs(s['position'][i]-self.position[i]) < .3 for i in range(3)))
        time.sleep(.5)
        self.action('select-slot', '1')
        self.action('look-at', *map(str, block['aim']))
        state = self.observe(lambda s: s['target'].get('type') == 'Block')
        self.action('use-item', '--snapshot', state['snapshot'], '--mode', 'block')
        deadline = time.monotonic()+self.args.timeout
        while self.server('block_readback()').get('name') != 'minecraft:cobblestone':
            require(time.monotonic() < deadline, 'Server did not observe placed cobblestone')
            time.sleep(.25)
        placed = self.server('block_readback()')
        self.server('survival()')
        self.action('select-slot', '6')
        state = self.observe(lambda s: (s.get('carried') or {}).get('name') == 'minecraft:diamond_pickaxe'
                             and s['target'].get('type') == 'Block')
        self.action('dig', '--snapshot', state['snapshot'], '--duration-ms', '5000')
        deadline = time.monotonic()+self.args.timeout
        while self.server('block_readback()').get('name') != 'minecraft:air':
            require(time.monotonic() < deadline, 'Server did not observe block removal')
            time.sleep(.25)
        return {'placed': placed, 'removed': self.server('block_readback()')}

    def run(self):
        before = None
        try:
            if self.args.launch:
                result = self.call('run', '--new', '--no-gui', '--detach', session=False)
                require(not result.get('already_running'), 'Manual runner will not take ownership of an existing session')
                self.session, self.owned = result['session'], True
            self.report['session'] = self.session
            self.data = self.call('status')
            self.report['backend'] = self.data.get('backend', 'windows')
            self.report['capabilities'] = self.call('runtime', 'capabilities')
            require(self.case('client-server-probe', self.probe) == 'passed', 'Runtime probe failed')
            if self.args.suite in ('ui', 'all'):
                self.case('native-ui', self.ui)
            if self.args.suite in ('player', 'all'):
                if self.case('server-fixture', self.prepare) == 'passed':
                    before = self.player('snapshot')
                    self.case('food-and-bow', self.food)
                    self.case('movement-sequence', self.movement)
                    self.case('attack-and-projectile', self.attack_and_bow)
                    self.case('place-and-dig', self.place_and_dig)
            self.report['ok'] = not any(case['state'] == 'failed' for case in self.report['cases'])
        except Exception as error:
            self.report['error'] = str(error)
        finally:
            if self.session:
                def clean(name, function):
                    try:
                        self.report['cleanup'].append({'name': name, 'state': 'completed', 'result': function()})
                    except Exception as error:
                        self.report['cleanup'].append({'name': name, 'state': 'failed', 'error': str(error)})
                        self.report['ok'] = False
                clean('release-owned-input', lambda: self.player('stop'))
                if before:
                    clean('restore-slot', lambda: self.action('select-slot', str(before['selected_slot'])))
                    clean('restore-look', lambda: self.action('look', '--pitch', str(before['rotation']['pitch']),
                                                             '--yaw', str(before['rotation']['yaw'])))
                if self.fixture_attempted:
                    clean('server-fixture', lambda: self.py(
                        "import sys\n_m = sys.modules.get('_mcpy_optional_controls_fixture')\n"
                        "_result = _m.fixture.cleanup() if _m is not None else {'ok': True, 'fixture': 'absent'}\n"
                        "sys.modules.pop('_mcpy_optional_controls_fixture', None)", 'server'))
                if self.owned:
                    clean('stop-owned-session', lambda: self.call('stop'))
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.report['coverage'] = {state: sum(case['state'] == state for case in self.report['cases'])
                                       for state in ('passed', 'failed', 'skipped')}
            self.output.write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'ok': self.report['ok'], 'output': str(self.output), 'session': self.session}, ensure_ascii=True))
        return 0 if self.report['ok'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, help='Initialized, disposable local Addon project')
    ownership = parser.add_mutually_exclusive_group(required=True)
    ownership.add_argument('--session', help='Attach without stopping this session at the end')
    ownership.add_argument('--launch', action='store_true', help='Start a NEW world; stop only this owned session at the end')
    parser.add_argument('--suite', choices=('probe', 'ui', 'player', 'all'), default='probe')
    parser.add_argument('--prepare-fixture', action='store_true', help='Explicitly allow changes to terrain, mode, position, hunger and inventory')
    parser.add_argument('--output', help='New JSON path; defaults to ignored PROJECT/.runtime/manual-tests/')
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--require-background', action='store_true', help='Windows foreground verification only; omit on macOS')
    args = parser.parse_args(argv)
    if args.suite in ('player', 'all') and not args.prepare_fixture:
        parser.error('player/all requires --prepare-fixture and a disposable test world')
    if args.require_background and sys.platform != 'win32':
        parser.error('--require-background is Windows-only; game-native controls do not require desktop permission on macOS')
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    if not (Path(args.project)/'pyproject.toml').is_file():
        parser.error('Initialize a disposable Addon project first')
    if not args.output:
        args.output = str(Path(args.project)/'.runtime/manual-tests'/(uuid.uuid4().hex+'.json'))
    output = Path(args.output)
    siblings = [output, output.with_name(output.stem+'-ui.json'), output.with_name(output.stem+'-player.json')]
    if any(path.exists() for path in siblings):
        parser.error('Output paths must be new; existing reports are preserved')
    return LiveTests(args).run()


if __name__ == '__main__':
    raise SystemExit(main())

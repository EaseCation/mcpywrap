"""可选 Windows 实机验收：后台组合按键、固定顺序、取消与菜单释放。"""
import argparse
import json
import math
from pathlib import Path
import sys
import threading
import time
import uuid

from manual.runtime_controls.support import invoke_json
from manual_runtime_ui import foreground


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def make_plan(rows):
    return {'schema_version': 1, 'clock': 'monotonic_ms',
            'events': [{'at': at, 'action': action, 'key': key} for at, action, key in rows]}


def check_overlap(operation, observation):
    """检查观测到的实际跳跃，以及 SPACE 松开后仍存在的移动区间。"""
    require(operation.get('state') == 'completed' and operation.get('released'), 'Timeline did not complete and release')
    require(not operation.get('logs_truncated') and not observation.get('truncated'), 'Evidence was truncated')
    require(not observation.get('errors'), 'Observation errors: '+str(observation.get('errors')))
    require([row['index'] for row in operation['events']] == list(range(len(operation['plan']['events']))),
            'Missing or reordered edge records')
    require(all(row['accepted'] is True for row in operation['events']), 'An edge was not confirmed')
    expected_order = [(row['keycode'], int(row['action'] == 'key_down')) for row in operation['events']]
    observed_order = [(int(row['args']['key']), int(row['args']['isDown'])) for row in observation['keys']]
    require(observed_order == expected_order, 'Observed keyboard event order differs from submitted edges')
    samples = observation['samples']
    require(samples, 'No observed player samples')
    base_y = samples[0]['position'][1]
    require(max(row['position'][1] for row in samples)-base_y > .2, 'No actual jump observed')
    space_up = next(row for row in operation['events'] if row['key'] == 'SPACE' and row['action'] == 'key_up')
    forward_up = next(row for row in operation['events'] if row['key'] == 'W' and row['action'] == 'key_up')
    after_release = [row for row in samples if row.get('operation') and
                     row['operation'].get('held_keys') == ['W'] and
                     operation['started_at']+space_up['finished_ms']/1000. <= row['time'] <
                     operation['started_at']+forward_up['started_ms']/1000.]
    require(len(after_release) >= 3, 'No independently observed W-only interval after SPACE release')
    first, last = after_release[0]['position'], after_release[-1]['position']
    movement = math.hypot(last[0]-first[0], last[2]-first[2])
    require(movement > .2, 'Movement did not continue after SPACE release')
    require(any(abs(row['input_vector'][1]) > .1 for row in after_release), 'Forward input was not observed')
    return {'jump_height': max(row['position'][1] for row in samples)-base_y,
            'movement_after_space_up': movement, 'w_only_samples': len(after_release),
            'keyboard_event_order_verified': True}


class TimelineLiveTest:
    def __init__(self, args):
        self.args = args
        self.output = Path(args.output).resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.session = args.session
        self.owned = False
        self.history = []
        self.report = {'ok': False, 'optional_manual_test': True, 'cases': [], 'history': self.history}
        self.prefix = [sys.executable, '-X', 'utf8', '-m', 'mcpywrap', '--local', '--project',
                       str(Path(args.project).resolve()), '--non-interactive']
        self.probe = "sys.modules['_mcpy_optional_key_timeline_probe'].probe"

    def call(self, *arguments, session=True, allow_failure=False):
        command = self.prefix + list(arguments)
        if session:
            command += ['--session', self.session]
        result, code = invoke_json(command+['--json'], timeout=60, history=self.history)
        require(allow_failure or (code == 0 and result.get('ok')), 'CLI failed: '+str(result))
        return result

    def py(self, code):
        result = self.call('runtime', 'py', '--side', 'client', '--code', 'import sys\n'+code)
        require(result.get('state') == 'completed', 'Client Python result is unknown')
        return result['value']

    def player(self, *arguments, **kwargs):
        return self.call('runtime', 'player', *arguments, **kwargs)

    def settle(self):
        deadline = time.monotonic()+10
        while time.monotonic() < deadline:
            state = self.player('snapshot')
            if state['active'] is None and all(abs(value) <= .01 for value in state['input_vector']):
                return state
            time.sleep(.1)
        raise RuntimeError('Input did not settle to zero')

    def run_recipe(self, name, recipe, mode='complete'):
        rid = uuid.uuid4().hex
        path = self.output/(name+'.plan.json')
        path.write_text(json.dumps(recipe, ensure_ascii=False, indent=2), encoding='utf-8')
        self.py('_result = '+self.probe+'.start('+repr(rid)+')')
        operation = self.player('timeline', '--file', str(path), '--request-id', rid)
        deadline = time.monotonic()+10
        cancelled = False
        while operation['state'] == 'pending' and time.monotonic() < deadline:
            if mode == 'cancel' and operation['held_keys'] == ['W', 'SPACE']:
                operation = self.player('cancel', '--operation', rid)
                cancelled = True
                break
            time.sleep(.1)
            operation = self.player('status', '--operation', rid, '--details', allow_failure=True)
        operation = self.player('status', '--operation', rid, '--details', allow_failure=True)
        time.sleep(.25)
        observation = self.py('_result = '+self.probe+'.stop()')
        evidence = {'operation': operation, 'observation': observation, 'mode': mode}
        (self.output/(name+'.evidence.json')).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        require(operation.get('released') and not operation.get('held_keys'), 'Owned keys were not released')
        require(not observation['truncated'] and not observation['errors'], 'Incomplete observation evidence')
        if mode == 'complete':
            metrics = check_overlap(operation, observation)
        elif mode == 'cancel':
            require(cancelled and operation['state'] == 'cancelled', 'Cancellation did not interrupt W+SPACE hold')
            require(operation['index'] == 2, 'Cancelled operation dispatched subsequent events')
            metrics = {'cleanup_order': [row['key'] for row in operation['cleanup_events']]}
            require(metrics['cleanup_order'] == ['SPACE', 'W'], 'Cleanup did not reverse actual press order')
        else:
            screen = self.py('_result = mcpy.api.GetTopUI()')
            require(screen not in ('hud_screen', 'ui://./hbui/gameplay.html'), 'Menu did not open')
            require(operation['state'] in ('cancelled', 'failed') and operation.get('code') == 'menu_open',
                    'Menu transition did not stop timeline')
            # 实机 ESC 在抬起后才打开菜单；允许它的 up，后续 SPACE/W 的计划 up 不得执行。
            require(operation['index'] <= 4, 'Menu operation dispatched subsequent events')
            for _ in range(5):
                self.py('_result = mcpy.api.PopTopUI()')
                if self.py('_result = mcpy.api.GetTopUI()') in ('hud_screen', 'ui://./hbui/gameplay.html'):
                    break
            metrics = {'menu': screen, 'cleanup_order': [row['key'] for row in operation['cleanup_events']]}
        self.settle()
        self.report['cases'].append({'name': name, 'state': 'passed', 'metrics': metrics, 'operation': rid})
        print(name+': passed', flush=True)

    def run(self):
        observations = [foreground()]
        finished = threading.Event()
        def monitor():
            while not finished.wait(.02):
                current = foreground()
                if current != observations[-1]:
                    observations.append(current)
        watcher = None
        before = None
        probe_installed = False
        try:
            if self.args.launch:
                launch = self.call('run', '--new', '--world-type', 'flat', '--game-type', 'survival',
                                   '--difficulty', 'peaceful', '--no-mob-spawn', '--no-gui', '--detach',
                                   '--engine-version', self.args.engine_version, session=False)
                self.session, self.owned = launch['session'], True
                # 启动后恢复原有应用前台；不向游戏发送桌面键鼠。
                if self.args.require_background and observations[0]:
                    import ctypes
                    from ctypes import wintypes
                    user = ctypes.WinDLL('user32')
                    user.SetForegroundWindow.argtypes = [wintypes.HWND]
                    user.SetForegroundWindow(observations[0]['window'])
            deadline = time.monotonic()+90
            while True:
                status = self.call('status')
                if status.get('world_ready'):
                    break
                require(time.monotonic() < deadline, 'Game world did not become ready')
                time.sleep(.5)
            game = status['game']
            actual_engine = Path(game['executable']).parent.name
            require(not self.args.engine_version or self.args.engine_version == actual_engine, 'Actual engine differs from requested version')
            self.report.update(session=self.session, engine=actual_engine)
            if self.args.launch and self.args.require_background and observations[0]:
                user.SetForegroundWindow(observations[0]['window'])
                time.sleep(.2)
            if self.args.require_background:
                require(foreground()['pid'] != game['pid'], 'Keep another app in foreground before the test')
            observations[:] = [foreground()]
            watcher = threading.Thread(target=monitor)
            watcher.start()
            self.call('runtime', 'install')
            capability = self.player('status')
            require(capability['capabilities'].get('timeline'), 'Current engine does not support timeline')
            self.report['capabilities'] = capability
            before = self.settle()
            require(before['screen'] in ('hud_screen', 'ui://./hbui/gameplay.html'), 'Close menus before testing')
            self.player('look', '--pitch', '0', '--yaw', '0')
            self.report['key_settings'] = self.py(
                "view = mcpy.api.GetEngineCompFactory().CreatePlayerView(mcpy.api.GetLevelId())\n"
                "_result = {'layout': view.GetControllerLayout(0), 'input_mode': view.GetToggleOption(mcpy.api.GetMinecraftEnum().OptionId.INPUT_MODE)}")
            probe_path = Path(__file__).parent/'manual/runtime_controls/key_timeline_probe.py'
            response = self.call('runtime', 'py', '--side', 'client', '--file', str(probe_path))
            require(response.get('state') == 'completed', 'Observation probe installation not confirmed')
            probe_installed = True
            overlap = make_plan([(0, 'key_down', 'W'), (500, 'key_down', 'SPACE'),
                                 (700, 'key_up', 'SPACE'), (2000, 'key_up', 'W')])
            for repetition in range(1, 4):
                self.run_recipe('overlap-'+str(repetition), overlap)
            # 修饰键顺序只检查提交记录，仍包含足够长的真实跳跃/移动观测区间。
            for keys in (('W', 'CTRL'), ('CTRL', 'W')):
                recipe = make_plan([(0, 'key_down', k) for k in keys] +
                                   [(500, 'key_down', 'SPACE'), (700, 'key_up', 'SPACE'),
                                    (900, 'key_up', 'CTRL'), (2000, 'key_up', 'W')])
                for repetition in range(1, 4):
                    name = 'order-'+'-'.join(keys)+'-'+str(repetition)
                    self.run_recipe(name, recipe)
                    evidence = json.loads((self.output/(name+'.evidence.json')).read_text(encoding='utf-8'))
                    require([row['key'] for row in evidence['operation']['events'][:2]] == list(keys), 'Modifier order changed')
            self.run_recipe('cancel', make_plan([(0, 'key_down', 'W'), (0, 'key_down', 'SPACE'),
                                                 (5000, 'key_up', 'SPACE'), (6000, 'key_up', 'W')]), 'cancel')
            self.run_recipe('menu', make_plan([(0, 'key_down', 'W'), (0, 'key_down', 'SPACE'),
                                               (1000, 'key_down', 'ESC'), (1100, 'key_up', 'ESC'),
                                               (3000, 'key_up', 'SPACE'), (4000, 'key_up', 'W')]), 'menu')
            self.report['ok'] = True
        except Exception as error:
            self.report['error'] = str(error)
        finally:
            cleanup = []
            def clean(name, function):
                try:
                    cleanup.append({'name': name, 'result': function()})
                except Exception as error:
                    cleanup.append({'name': name, 'error': str(error)})
                    self.report['ok'] = False
            if self.session:
                clean('release', lambda: self.player('stop'))
                if probe_installed:
                    clean('probe', lambda: self.py('_result = '+self.probe+'.close()'))
                if before:
                    clean('rotation', lambda: self.player('look', '--pitch', str(before['rotation']['pitch']),
                                                         '--yaw', str(before['rotation']['yaw'])))
                if self.owned:
                    clean('owned-session', lambda: self.call('stop'))
            finished.set()
            if watcher:
                watcher.join()
            self.report.update(cleanup=cleanup, desktop=observations)
            if self.args.require_background and self.report.get('session') and 'game' in locals():
                verified = all(row['pid'] != game['pid'] for row in observations)
                self.report['background_verified'] = verified
                if not verified:
                    self.report.update(ok=False, background_error='Game took foreground during test')
            (self.output/'report.json').write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'ok': self.report['ok'], 'output': str(self.output), 'error': self.report.get('error')}, ensure_ascii=False))
        return 0 if self.report['ok'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, help='已初始化的专用本地测试 Addon 项目')
    ownership = parser.add_mutually_exclusive_group(required=True)
    ownership.add_argument('--session', help='已有专用平坦世界；结束后保留会话')
    ownership.add_argument('--launch', action='store_true', help='创建平坦测试世界；结束后停止自己的会话')
    parser.add_argument('--engine-version', help='--launch 必须指定已安装的完整引擎版本')
    parser.add_argument('--output', required=True, help='新的证据目录')
    parser.add_argument('--require-background', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('本验收脚本首批仅支持 Windows；不会安装组件或回退桌面输入')
    if args.launch and not args.engine_version:
        parser.error('--launch 需要 --engine-version')
    if not (Path(args.project)/'pyproject.toml').is_file():
        parser.error('先准备专用测试项目')
    if Path(args.output).exists():
        parser.error('证据目录必须不存在')
    return TimelineLiveTest(args).run()


if __name__ == '__main__':
    raise SystemExit(main())

"""Opt-in Windows real-game launch/focus acceptance using isolated profiles and public CLI."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import uuid


class ForegroundEvents:
    def __init__(self):
        self.events = []
        self.ready = threading.Event()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        user = C.WinDLL('user32', use_last_error=True)
        callback_type = C.WINFUNCTYPE(None, W.HANDLE, W.DWORD, W.HWND, W.LONG, W.LONG, W.DWORD, W.DWORD)
        user.SetWinEventHook.restype = W.HANDLE
        user.SetWinEventHook.argtypes = [W.DWORD, W.DWORD, W.HMODULE, callback_type, W.DWORD, W.DWORD, W.DWORD]
        user.UnhookWinEvent.argtypes = [W.HANDLE]
        user.GetForegroundWindow.restype = W.HWND

        def event(hook, kind, hwnd, obj, child, tid, stamp):
            pid = W.DWORD()
            user.GetWindowThreadProcessId(hwnd, C.byref(pid))
            self.events.append({'time': time.monotonic(), 'hwnd': int(hwnd or 0), 'pid': pid.value,
                                'event': kind, 'os_time_ms': stamp})
        callback = callback_type(event)
        hook = user.SetWinEventHook(3, 3, None, callback, 0, 0, 0)
        self.error = None if hook else str(C.WinError(C.get_last_error()))
        event(None, 0, user.GetForegroundWindow(), 0, 0, 0, 0)
        self.ready.set()
        message = W.MSG()
        try:
            while not self.stop.wait(.005):
                while user.PeekMessageW(C.byref(message), None, 0, 0, 1):
                    user.TranslateMessage(C.byref(message))
                    user.DispatchMessageW(C.byref(message))
        finally:
            if hook:
                user.UnhookWinEvent(hook)

    def __enter__(self):
        self.thread.start()
        if not self.ready.wait(5) or self.error:
            raise RuntimeError('Cannot monitor foreground events: ' + str(self.error))
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--engine-version', action='append', required=True)
    parser.add_argument('--ready-timeout', type=float, default=180)
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Run on an unlocked Windows desktop.')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    # Match the engine's expected Windows profile path depth without borrowing user data.
    private = Path(tempfile.mkdtemp(prefix='.mcpy-background-', dir=output.anchor))/'profile'
    roaming, local = private/'AppData/Roaming', private/'AppData/Local'
    data = roaming/'MinecraftPE_Netease/games/com.netease'
    data.mkdir(parents=True)
    local.mkdir(parents=True)
    (roaming/'MinecraftPE_Netease/minecraftpe').mkdir()
    (roaming/'MinecraftPE_Netease/minecraftpe/options.txt').write_text(
        'gfx_renderengine:0\ngfx_max_framerate:30\ngfx_viewdistance:64\ngfx_fullscreen:0\n'
        'has_dismissed_new_player_flow:1\n', encoding='utf8')
    project = output/'后台窗口 测试项目'
    project.mkdir()
    (project/'pyproject.toml').write_text('[project]\nname="background-window-test"\nversion="0.1.0"\n'
        'dependencies=[]\n[tool.mcpywrap]\nproject_type="addon"\n', encoding='utf8')
    for kind, module in (('behavior', 'data'), ('resource', 'resources')):
        pack = project/(kind+'_pack')
        pack.mkdir()
        (pack/'manifest.json').write_text(json.dumps({'format_version': 2, 'header': {
            'name': 'Background window acceptance', 'description': 'Disposable test fixture',
            'uuid': str(uuid.uuid4()), 'version': [1, 0, 0], 'min_engine_version': [1, 18, 0]},
            'modules': [{'type': module, 'uuid': str(uuid.uuid4()), 'version': [1, 0, 0]}]}), encoding='utf8')
    env = dict(os.environ, USERPROFILE=str(private), APPDATA=str(roaming), LOCALAPPDATA=str(local),
               PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    prefix = [sys.executable, '-X', 'utf8', '-m', 'mcpywrap_core', '--local', '--project', str(project), '--non-interactive']
    report = {'ok': False, 'project': str(project), 'profile': str(private), 'cases': [], 'commands': [], 'cleanup': []}
    owned = set()

    def save():
        (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')

    def call(*command, allow_error=False):
        result = subprocess.run(prefix+list(command)+['--json'], env=env, capture_output=True, timeout=240)
        response = json.loads(result.stdout.decode('utf8'))
        report['commands'].append({'args': list(command), 'exit_code': result.returncode, 'result': response,
                                   'stderr': result.stderr.decode('utf8', errors='replace')})
        save()
        if not allow_error and (result.returncode or not response.get('ok')):
            raise RuntimeError(str(response))
        return response

    def ready(sid):
        deadline = time.monotonic()+args.ready_timeout
        while time.monotonic() < deadline:
            state = call('status', '--session', sid)
            if state.get('world_ready'):
                return state
            if state['state'] not in ('starting', 'running'):
                raise RuntimeError(str(state))
            time.sleep(1)
        raise RuntimeError('HUD readiness timed out: ' + sid)

    def launch_case(version, foreground=False):
        case = {'version': version, 'foreground': foreground, 'ok': False}
        report['cases'].append(case)
        with ForegroundEvents() as monitor:
            start = call('run', '--new', '--no-gui', '--detach', '--engine-version', version,
                         *(['--foreground'] if foreground else []))
            sid, pid = start['session'], start['pid']
            owned.add(sid)
            case.update(session=sid, pid=pid, background=start['background'])
            ready(sid)
            time.sleep(3)
            image = call('screenshot', '--session', sid, '--output', str(output/(sid+'.png')))
            case['capture'] = image
            if not foreground:
                rejected = call('key', '--session', sid, 'W', allow_error=True)
                case['desktop_rejected'] = rejected.get('code') == 'foreground_input_disabled'
                if not case['desktop_rejected']:
                    raise RuntimeError('Background desktop input was not rejected: ' + str(rejected))
            time.sleep(.5)
            case['foreground_events'] = list(monitor.events)
            case['game_foreground_events'] = [e for e in monitor.events if e['pid'] == pid]
            case['ok'] = (bool(case['game_foreground_events']) if foreground else not case['game_foreground_events'])
            save()
        call('stop', '--session', sid)
        owned.remove(sid)
        print(version, 'foreground' if foreground else 'background', 'PASS' if case['ok'] else 'FAIL', flush=True)

    try:
        for version in args.engine_version:
            launch_case(version)
        launch_case(args.engine_version[0], foreground=True)
        report['ok'] = all(case['ok'] for case in report['cases'])
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        for sid in list(owned):
            try:
                report['cleanup'].append(call('stop', '--session', sid, allow_error=True))
            except BaseException as error:
                report['cleanup'].append({'session': sid, 'error': repr(error)})
        save()
    if not report['ok']:
        raise SystemExit('One or more game launches stole focus; inspect report.json')


if __name__ == '__main__':
    main()

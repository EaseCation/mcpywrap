"""独立世界中的公开 CLI 验收：节点、后台交互、恢复；不会停止传入会话。"""
import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid


def foreground():
    user = ctypes.WinDLL('user32')
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    handle = user.GetForegroundWindow()
    pid, point = wintypes.DWORD(), wintypes.POINT()
    user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    user.GetCursorPos(ctypes.byref(point))
    return {'window': handle, 'pid': pid.value, 'cursor': [point.x, point.y]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--require-background', action='store_true')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError('验收输出必须是新文件')
    prefix = [sys.executable, '-X', 'utf8', '-m', 'mcpywrap', '--local', '--project', args.project]
    history = []

    def call(*command, allow_failure=False):
        started = time.monotonic()
        process = subprocess.run(prefix + list(command) + ['--session', args.session, '--json'],
                                 capture_output=True, encoding='utf-8', timeout=25)
        data = json.loads(process.stdout)
        history.append({'command': command, 'elapsed_seconds': time.monotonic()-started, 'result': data})
        if not allow_failure and (process.returncode or not data.get('ok')):
            raise RuntimeError(data)
        return data

    def ui(*command, **kwargs): return call('runtime', 'ui', *command, **kwargs)
    def snapshot(): return ui('snapshot', '--details')
    def wait_snapshot(predicate, state=None):
        until=time.monotonic()+6
        while True:
            state=state or snapshot()
            if predicate(state):return state
            if time.monotonic()>=until:raise RuntimeError('UI 未在时限内达到预期状态；未重复发送点击')
            time.sleep(.15)
            state=None
    def select(state, predicate):
        found = [row for row in state['nodes'] if predicate(row)]
        if len(found) != 1:
            raise RuntimeError('预期唯一节点，实际找到 ' + str(len(found)))
        return found[0]
    def action(state, row, verb='click', *options):
        rid = uuid.uuid4().hex
        result = ui(verb, str(row['id']), '--snapshot', state['snapshot'], '--request-id', rid, *options)
        until = time.monotonic()+8
        while result.get('state') == 'pending' and time.monotonic() < until:
            result = ui('status', '--operation', rid)
        if result.get('state') != 'completed':
            raise RuntimeError('动作未完成: ' + str(result))
        return rid

    game = call('status')['game']
    observations, stop = [foreground()], threading.Event()
    if args.require_background and observations[0]['pid'] == game['pid']:
        raise ValueError('请先保持其他应用前台，再运行后台验收')
    def monitor():
        while not stop.wait(.01):
            current = foreground()
            if current != observations[-1]: observations.append(current)
    watcher = threading.Thread(target=monitor)
    watcher.start()
    original_volume = None
    error = None
    try:
        installed = ui('install')
        if not installed['capabilities']['click']:
            raise RuntimeError('当前构建未通过内部触控适配')
        ui('install')  # 重复安装不应破坏监听和后续动作。
        state = snapshot()
        if state['top'] == 'hud_screen':
            call('runtime', 'py', '--side', 'client', '--code', 'mcpy.api.OpenPauseGui()')
            state = snapshot()
        if state['screen'] == 'pause.pause_screen':
            row = select(state, lambda r: r['role']=='button' and r['name']=='设置')
            action(state, row)
            state = wait_snapshot(lambda s:s['screen']=='settings.screen_world_controls_and_settings')
        assert state['screen'] == 'settings.screen_world_controls_and_settings'
        if not state['top'].endswith('game_tab'):
            action(state, select(state, lambda r: r['role']=='toggle' and r['name']=='游戏'))
            state = snapshot()
        scroll = select(state, lambda r: r['role']=='scroll' and '/content_area/' in r['path'])
        original_scroll = scroll['value']
        action(state, scroll, 'scroll', '--percent', '50')
        stale = ui('click', str(next(r for r in state['nodes'] if r['role']=='button')['id']),
                   '--snapshot', state['snapshot'], allow_failure=True)
        assert stale['code'] == 'stale_snapshot'
        state = snapshot()
        scroll = select(state, lambda r: r['role']=='scroll' and '/content_area/' in r['path'])
        assert scroll['value'] == 50
        action(state, scroll, 'scroll', '--percent', str(original_scroll))
        state = snapshot()
        audio = select(state, lambda r: r['role']=='toggle' and r['name']=='音频')
        rid = action(state, audio)
        repeated = ui('click', str(audio['id']), '--snapshot', state['snapshot'], '--request-id', rid)
        assert repeated['state'] == 'completed' and repeated['released']
        state = snapshot()
        state = wait_snapshot(lambda s:s['top'].endswith('sound_tab') and any(r['name']=='音频设置' for r in s['nodes']),state)
        volume = select(state, lambda r: r['role']=='slider' and r['name'].startswith('主音量：'))
        original_volume = volume['value']
        action(state, volume, 'slide', '--fraction', '0.25')
        state = snapshot()
        volume = select(state, lambda r: r['role']=='slider' and r['name'].startswith('主音量：'))
        assert abs(volume['value']-.25) < .02 and volume['name']=='主音量：25'
    except Exception as exc:
        error = str(exc)
    finally:
        if original_volume is not None:
            try:
                state = snapshot()
                volume = select(state, lambda r: r['role']=='slider' and r['name'].startswith('主音量：'))
                action(state, volume, 'slide', '--fraction', str(original_volume))
                restored = snapshot()
                restored_volume = select(restored, lambda r: r['role']=='slider' and r['name'].startswith('主音量：'))
                assert abs(restored_volume['value']-original_volume) < .02
                assert restored_volume['name'] == '主音量：' + str(round(original_volume*100))
            except Exception as exc:
                error = (error or '') + '\n恢复失败: ' + str(exc)
        stop.set(); watcher.join()
        if args.require_background and any(item['pid'] == game['pid'] for item in observations):
            error = (error or '') + '\n验收期间游戏曾成为前台'
        result = {'ok': error is None, 'error': error, 'session': args.session,
                  'game_pid': game['pid'], 'observations': observations,
                  'original_volume': original_volume, 'history': history}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': error is None, 'error': error, 'output': str(output),
                      'calls': len(history), 'desktop_changes': len(observations)-1}, ensure_ascii=False))
    return int(error is not None)


if __name__ == '__main__':
    raise SystemExit(main())

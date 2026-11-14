"""macOS 前台设备输入：与 Windows SendInput 后端相同的统一计划语义，经原生辅助程序向 HID 事件流投递键鼠事件。"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from ..input_plan import InputPlanError, input_require

# 规范化键名 → macOS 虚拟键码（Carbon kVK_*）。左右修饰键分别映射，通用名取左键。
MAC_KEYS = {
    'A': 0, 'S': 1, 'D': 2, 'F': 3, 'H': 4, 'G': 5, 'Z': 6, 'X': 7, 'C': 8, 'V': 9, 'B': 11, 'Q': 12,
    'W': 13, 'E': 14, 'R': 15, 'Y': 16, 'T': 17, '1': 18, '2': 19, '3': 20, '4': 21, '6': 22, '5': 23,
    'EQUALS': 24, '9': 25, '7': 26, 'MINUS': 27, '8': 28, '0': 29, 'RBRACKET': 30, 'O': 31, 'U': 32,
    'LBRACKET': 33, 'I': 34, 'P': 35, 'ENTER': 36, 'L': 37, 'J': 38, 'QUOTE': 39, 'K': 40, 'SEMICOLON': 41,
    'BACKSLASH': 42, 'COMMA': 43, 'SLASH': 44, 'N': 45, 'M': 46, 'PERIOD': 47, 'TAB': 48, 'SPACE': 49,
    'BACKTICK': 50, 'BACKSPACE': 51, 'ESC': 53, 'RWIN': 54, 'LWIN': 55, 'LSHIFT': 56, 'CAPSLOCK': 57,
    'LALT': 58, 'LCTRL': 59, 'RSHIFT': 60, 'RALT': 61, 'RCTRL': 62, 'DECIMAL': 65, 'MULTIPLY': 67, 'ADD': 69,
    'NUMLOCK': 71, 'DIVIDE': 75, 'NUMPAD_ENTER': 76, 'SUBTRACT': 78,
    'NUMPAD0': 82, 'NUMPAD1': 83, 'NUMPAD2': 84, 'NUMPAD3': 85, 'NUMPAD4': 86, 'NUMPAD5': 87, 'NUMPAD6': 88,
    'NUMPAD7': 89, 'NUMPAD8': 91, 'NUMPAD9': 92,
    'F1': 122, 'F2': 120, 'F3': 99, 'F4': 118, 'F5': 96, 'F6': 97, 'F7': 98, 'F8': 100, 'F9': 101, 'F10': 109,
    'F11': 103, 'F12': 111, 'F13': 105, 'F14': 107, 'F15': 113, 'F16': 106, 'F17': 64, 'F18': 79, 'F19': 80,
    'INSERT': 114, 'HELP': 114, 'HOME': 115, 'PAGEUP': 116, 'DELETE': 117, 'END': 119, 'PAGEDOWN': 121,
    'LEFT': 123, 'RIGHT': 124, 'DOWN': 125, 'UP': 126,
}
MAC_ALIASES = {'SHIFT': 'LSHIFT', 'CTRL': 'LCTRL', 'ALT': 'LALT', 'WIN': 'LWIN', 'CMD': 'LWIN', 'COMMAND': 'LWIN',
               'OPTION': 'LALT', 'OEM_1': 'SEMICOLON', 'OEM_PLUS': 'EQUALS', 'OEM_COMMA': 'COMMA',
               'OEM_MINUS': 'MINUS', 'OEM_PERIOD': 'PERIOD', 'OEM_2': 'SLASH', 'OEM_3': 'BACKTICK',
               'OEM_4': 'LBRACKET', 'OEM_5': 'BACKSLASH', 'OEM_6': 'RBRACKET', 'OEM_7': 'QUOTE'}
MODIFIER_CODES = {54, 55, 56, 58, 59, 60, 61, 62}


def mac_key_code(name):
    key = MAC_ALIASES.get(name, name)
    input_require(not key.startswith(('VK:', 'SC:', 'E0:')), 'not_supported', 'macOS 设备后端不接受 Windows 虚拟键/扫描码：' + name)
    input_require(key in MAC_KEYS, 'invalid_key', 'macOS 设备后端没有该键：' + name)
    return MAC_KEYS[key]


@contextmanager
def desktop_input_lock():
    """同一用户的各会话、本机 CLI 与远程服务串行使用桌面键鼠。"""
    import fcntl
    path = Path(tempfile.gettempdir()) / 'mcpywrap-desktop-input.lock'
    with path.open('a+b') as stream:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                input_require(time.monotonic() < deadline, 'busy', '另一个会话正在使用桌面键鼠')
                time.sleep(.02)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class MacInputHelper:
    """常驻 --input 子进程；一次计划一个进程，请求按行往返。"""

    def __init__(self, executable):
        self.process = subprocess.Popen([str(executable), '--input'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=0)
        self.sequence = 0

    def request(self, op, **fields):
        self.sequence += 1
        line = json.dumps(dict(fields, id=self.sequence, op=op), separators=(',', ':')).encode() + b'\n'
        try:
            self.process.stdin.write(line)
            reply = self.process.stdout.readline(65537)
        except OSError as exc:
            raise InputPlanError('unknown', '设备输入辅助程序通信失败：' + str(exc)) from None
        input_require(reply.endswith(b'\n'), 'unknown', '设备输入辅助程序未确认请求')
        value = json.loads(reply)
        input_require(value.get('id') == self.sequence, 'unknown', '设备输入辅助程序响应错序')
        return value

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)


class MacInputAdapter:
    """与 WindowsInputAdapter 相同的执行器接口；需要游戏位于前台与“辅助功能”授权。"""
    input_path = 'macos-cgevent'
    clock_source = 'time.monotonic'
    clock = staticmethod(time.monotonic)

    def __init__(self, manager):
        self.manager = manager
        self.helper = self.lock = None
        self.game = None
        self.area = None
        self.last_send = {}
        self.reserved = False

    def _game(self):
        from . import recordings
        return recordings.recording_game(self.manager.project, self.manager.session)

    def ready(self):
        import sys
        input_require(sys.platform == 'darwin', 'not_supported', '该执行端没有 macOS 设备输入')
        from ..runtime.window_policy import require_foreground_input
        require_foreground_input(self.manager.project, self.manager.session)
        self._game()

    def validate(self, plan):
        input_require(plan['backend'] == self.input_path, 'not_supported', '设备执行器只处理显式 macOS 后端')
        keys, held = {}, set()
        for step in plan['steps']:
            for key in step.get('keys', []) + ([step['key']] if 'key' in step else []):
                keys[key] = mac_key_code(key)
            name = step['action']
            if name == 'key':
                codes = [keys[k] for k in step['keys']]
                input_require(len(set(codes)) == len(codes) and not held.intersection(codes), 'invalid_plan', '设备键别名冲突')
            if name in ('key_down', 'key_up'):
                code = keys[step['key']]
                input_require(code not in held if name == 'key_down' else code in held, 'invalid_plan', '设备键生命周期冲突')
                if name == 'key_down': held.add(code)
                else: held.remove(code)
        return {'keys': keys}

    def prepare(self, op):
        from ..runtime.window_policy import require_foreground_input
        from . import recordings
        require_foreground_input(self.manager.project, self.manager.session)
        reservation = self.manager.game('_reserve', {'operation': op['operation_id'], 'signature': op['_signature']})
        if reservation.get('code') != 'not_installed':
            input_require(reservation.get('ok'), reservation.get('code', 'busy'), reservation.get('error', '无法预留游戏控制层'))
            self.reserved = True
        lock = desktop_input_lock(); lock.__enter__(); self.lock = lock
        self.game = self._game()
        try:
            executable = recordings.macos_helper()
        except ValueError as exc:
            raise InputPlanError('capability_missing', str(exc)) from None
        self.helper = MacInputHelper(executable)
        codes = sorted(set(op['_bindings']['keys'].values()) | MODIFIER_CODES)
        state = self.helper.request('prepare', pid=int(self.game['pid']), keys=codes)
        input_require(state.get('ok'), state.get('code', 'window_unavailable'), state.get('error', '无法定位游戏窗口'))
        input_require(state.get('post_allowed'), 'permission_missing',
                      '需要在“系统设置 > 隐私与安全性 > 辅助功能”中允许运行 mcpy 的终端或宿主应用，然后重启该应用')
        input_require(state.get('frontmost') == self.game['pid'], 'foreground_unavailable', '无法将游戏切换到前台')
        input_require(not state.get('keys_down'), 'input_busy', '目标键或修饰键已按住')
        if any(s['action'].startswith('pointer.') for s in op['plan']['steps']):
            client = state.get('client') or {}
            self.area = (client.get('width'), client.get('height'), client.get('x'), client.get('y'))
            input_require(self.area[:2] == (op['plan']['width'], op['plan']['height']), 'viewport_changed', '客户区与参考尺寸不同')
            input_require(not any(state.get('buttons', [])), 'input_busy', '鼠标按钮已按住')

    def schedule(self, delay, callback):
        self.manager.schedule(delay, callback)

    def _state(self):
        state = self.helper.request('state')
        input_require(state.get('ok') and state.get('frontmost') == self.game['pid'], 'foreground_lost', '游戏失去前台')
        return state

    def guard(self, op):
        if self.helper is None: return
        state = self._state()
        if self.area:
            client = state.get('client') or {}
            input_require((client.get('width'), client.get('height'), client.get('x'), client.get('y')) == self.area,
                          'viewport_changed', '操作期间客户区移动或尺寸改变')

    def binding(self, op, kind, key):
        return op['_bindings']['keys'][key] if kind == 'key' else key

    @staticmethod
    def identity(kind, binding):
        return (kind, binding)

    def _send(self, op, **fields):
        reply = self.helper.request(op, **fields)
        input_require(reply.get('ok'), reply.get('code', 'unknown'), reply.get('error', '设备事件未投递'))
        return reply

    def send(self, kind, binding, down):
        self.last_send = {}
        if kind == 'key':
            reply = self._send('key', code=binding, down=down)
        else:
            if down:
                input_require(self._state().get('cursor_inside'), 'pointer_outside', '指针不在未遮挡的游戏客户区')
            reply = self._send('button', button=binding, down=down)
        self.last_send = {k: reply[k] for k in ('send_started_ns', 'send_finished_ns', 'accepted') if k in reply}
        return True

    def begin(self, op, stage):
        step = stage['step']; name = step['action']
        if name == 'pointer.move': reply = self._send('move', x=step['x'], y=step['y'])
        elif name == 'pointer.relative': reply = self._send('relative', dx=step['dx'], dy=step['dy'])
        elif name == 'pointer.wheel':
            input_require(self._state().get('cursor_inside'), 'pointer_outside', '指针不在未遮挡的游戏客户区')
            reply = self._send('wheel', delta=step['delta'])
        else: raise InputPlanError('not_supported', '设备后端不支持 ' + name)
        stage['result'] = {k: reply[k] for k in ('send_started_ns', 'send_finished_ns', 'accepted') if k in reply}

    def poll(self, op, stage):
        return True

    def cleanup(self, op):
        pass

    def finished(self, op):
        if not op['released']: return
        if self.helper is not None:
            self.helper.close(); self.helper = None
        if self.lock is not None:
            lock, self.lock = self.lock, None
            lock.__exit__(None, None, None)
        self.area = None
        if self.reserved:
            result = self.manager.game('_unreserve', {'operation': op['operation_id']})
            if not result.get('ok'):
                op.update(ok=False, state='unknown', unconfirmed_release_keys=['control_reservation'], released=False)
                self.manager.executor.active = op
                return
            self.reserved = False

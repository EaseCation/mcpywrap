"""会话 worker 的统一 Windows 输入：一个调度线程，状态与幂等历史有界。"""
import ctypes as C
from ctypes import wintypes as W
import os
import threading
import time

from ..input_executor import InputExecutor
from ..input_plan import INPUT_ACTIONS, INPUT_LIMITS, input_action_schema, input_require, InputPlanError, input_signature


class WindowsInputAdapter:
    input_path = 'windows-sendinput'
    clock_source = 'time.perf_counter'
    clock = staticmethod(time.perf_counter)

    def __init__(self, manager):
        self.manager = manager
        self.window = self.sender = self.mutex = None
        self.keys = {}
        self.area = None
        self.last_send = {}
        self.reserved = False

    def ready(self):
        input_require(os.name == 'nt', 'not_supported', '该执行端没有 Windows SendInput')
        from .window import session_game
        session_game(self.manager.project, self.manager.session)

    def validate(self, plan):
        from .window import parse_keys
        input_require(plan['backend'] == 'windows-sendinput', 'not_supported', '设备执行器只处理显式 Windows 后端')
        keys = {}
        held = set()
        for step in plan['steps']:
            for key in step.get('keys', [])+([step['key']] if 'key' in step else []):
                keys[key] = parse_keys(key)[0]
            name = step['action']
            if name == 'key':
                identities = [self.identity('key', keys[k]) for k in step['keys']]
                input_require(len(set(identities)) == len(identities) and not held.intersection(identities), 'invalid_plan', '设备键别名冲突')
            if name in ('key_down', 'key_up'):
                identity = self.identity('key', keys[step['key']])
                input_require(identity not in held if name == 'key_down' else identity in held, 'invalid_plan', '设备键生命周期冲突')
                if name == 'key_down': held.add(identity)
                else: held.remove(identity)
        return {'keys': keys}

    def prepare(self, op):
        from .window import GameWindow, session_game, desktop_input_lock, InputSender, MODIFIERS
        reservation = self.manager.game('_reserve', {'operation': op['operation_id'], 'signature': op['_signature']})
        if reservation.get('code') != 'not_installed':
            input_require(reservation.get('ok'), reservation.get('code', 'busy'), reservation.get('error', '无法预留游戏控制层'))
            self.reserved = True
        mutex = desktop_input_lock(); mutex.__enter__(); self.mutex = mutex
        self.window = GameWindow(session_game(self.manager.project, self.manager.session))
        self.keys = op['_bindings']['keys']
        identities = {}
        for key in self.keys.values():
            vk = key.vk or self.window.user.MapVirtualKeyW(key.scan | (0xE000 if key.extended else 0), 3)
            input_require(bool(vk), 'invalid_key', '扫描码无法解析到虚拟键')
            physical = (vk, key.extended)
            previous = identities.get(physical)
            identity = self.identity('key', key)
            input_require(previous in (None, identity), 'invalid_plan', '同一物理键不能混用 VK/扫描码表示')
            identities[physical] = identity
        for vk in MODIFIERS | {identity[0] for identity in identities}:
            input_require(not self.window.user.GetAsyncKeyState(vk) & 0x8000, 'input_busy', '目标键或修饰键已按住')
        self.window.foreground()
        if any(s['action'].startswith('pointer.') for s in op['plan']['steps']):
            self.area = self.window.client_area()
            input_require(self.area[:2] == (op['plan']['width'], op['plan']['height']), 'viewport_changed', '客户区与参考尺寸不同')
            for vk in (1, 2, 4):
                input_require(not self.window.user.GetAsyncKeyState(vk) & 0x8000, 'input_busy', '鼠标按钮已按住')
        self.sender = InputSender(self.window.user, trace=True)

    def schedule(self, delay, callback):
        self.manager.schedule(delay, callback)

    def guard(self, op):
        if self.window is None: return
        self.window.check_foreground(validate_identity=False)
        if self.area:
            current = self.window._client_area(require_foreground=False, require_uncovered=False)
            input_require(current[:2] == self.area[:2] and
                          (current[2].x, current[2].y) == (self.area[2].x, self.area[2].y),
                          'viewport_changed', '操作期间客户区移动或尺寸改变')

    def binding(self, op, kind, key):
        return op['_bindings']['keys'][key] if kind == 'key' else key

    @staticmethod
    def identity(kind, binding):
        return (kind, binding.vk, binding.scan, binding.extended) if kind == 'key' else (kind, binding)

    def _cursor_guard(self):
        point = W.POINT()
        input_require(self.window.user.GetCursorPos(C.byref(point)), 'pointer_unavailable', '无法读取指针')
        width, height, origin = self.area
        input_require(origin.x <= point.x < origin.x+width and origin.y <= point.y < origin.y+height and
                      self.window.owner(self.window.user.WindowFromPoint(point)) == self.window.game['pid'],
                      'pointer_outside', '指针不在未遮挡的游戏客户区')

    def send(self, kind, binding, down):
        from .window import Input, Mouse, keyboard_input
        if kind == 'key': event = keyboard_input(binding, not down)
        else:
            if down: self._cursor_guard()
            flags = {'left': (2, 4), 'right': (8, 16), 'middle': (32, 64)}[binding][0 if down else 1]
            event = Input(kind=0, mouse=Mouse(0, 0, 0, flags, 0, 0))
        self.last_send = {}
        try:
            self.sender.send(event)
            return True
        finally:
            if self.sender.events:
                self.last_send = {k: self.sender.events[-1][k] for k in ('send_started_ns', 'send_finished_ns', 'batch_inserted_count', 'accepted')}
                self.sender.events[:] = []

    def begin(self, op, stage):
        from .window import Input, Mouse
        step = stage['step']; name = step['action']
        if name == 'pointer.move':
            width, height, origin = self.area
            left, top = self.window.user.GetSystemMetrics(76), self.window.user.GetSystemMetrics(77)
            vw, vh = self.window.user.GetSystemMetrics(78), self.window.user.GetSystemMetrics(79)
            input_require(min(vw, vh) > 1, 'pointer_unavailable', '虚拟桌面尺寸无效')
            x = round((origin.x+step['x']-left)*65535/(vw-1))
            y = round((origin.y+step['y']-top)*65535/(vh-1))
            event = Input(kind=0, mouse=Mouse(x, y, 0, 0xC001, 0, 0))
        elif name == 'pointer.relative': event = Input(kind=0, mouse=Mouse(step['dx'], step['dy'], 0, 1, 0, 0))
        elif name == 'pointer.wheel':
            self._cursor_guard()
            event = Input(kind=0, mouse=Mouse(0, 0, step['delta'] & 0xFFFFFFFF, 0x800, 0, 0))
        else: raise InputPlanError('not_supported', '设备后端不支持 '+name)
        self.sender.send(event)
        stage['result'] = dict(self.sender.events[-1])
        self.sender.events[:] = []

    def cleanup(self, op):
        pass

    def finished(self, op):
        if not op['released']: return
        if self.window is not None:
            self.window.close(); self.window = None
        if self.mutex is not None:
            mutex, self.mutex = self.mutex, None
            mutex.__exit__(None, None, None)
        if self.reserved:
            result = self.manager.game('_unreserve', {'operation': op['operation_id']})
            if not result.get('ok'):
                op.update(ok=False, state='unknown', unconfirmed_release_keys=['control_reservation'], released=False)
                self.manager.executor.active = op
                return
            self.reserved = False


class HostInputManager:
    def __init__(self, channel, project, session):
        self.channel, self.project, self.session = channel, project, session
        self.condition = threading.Condition()
        self.callback = self.when = None
        self.commands = []
        self.closed = False
        self.executor = InputExecutor(WindowsInputAdapter(self))
        self.thread = threading.Thread(target=self._loop, name='mcpy-input', daemon=True)
        self.thread.start()

    def schedule(self, delay, callback):
        with self.condition:
            input_require(not self.closed, 'worker_stopping', '输入 worker 已关闭')
            self.callback, self.when = callback, time.perf_counter()+delay
            self.condition.notify_all()

    def _loop(self):
        while True:
            with self.condition:
                while not self.commands and self.callback is None and not self.closed:
                    self.condition.wait()
                if self.commands:
                    operation = self.commands.pop(0)
                    callback = lambda: self.executor.cancel(operation) if operation else self.executor.stop()
                elif self.closed: break
                else:
                    remaining = self.when-time.perf_counter()
                    if remaining > 0:
                        self.condition.wait(min(.05, remaining)); continue
                    callback, self.callback = self.callback, None
            try: callback()
            except Exception as error:
                with self.executor.lock:
                    if self.executor.active: self.executor._fail(self.executor.active, error)
        self.executor.stop()

    def game(self, method, parameters):
        from .runtime_ui import call_source
        response = self.channel.execute(call_source(method, parameters, family='input'), 'client')
        value = response.get('value')
        if response.get('state') != 'completed' or response.get('side') != 'client' or not isinstance(value, dict):
            return {'ok': False, 'state': 'unknown', 'operation_id': parameters.get('request_id'),
                    'request_id': parameters.get('request_id'), 'error': response.get('error') or '游戏输入传输未确认',
                    'transport': {'state': response.get('state'), 'request_id': response.get('request_id')}}
        return dict(value, transport={'state': response.get('state'), 'request_id': response.get('request_id')})

    def dispatch(self, method, parameters):
        allowed = {'run': {'plan', 'request_id'}, 'status': {'operation', 'details'}, 'cancel': {'operation'},
                   'stop': set(), 'capabilities': set(), 'observe': {'view', 'query', 'limit', 'offset', 'details'}}
        input_require(method in allowed and isinstance(parameters, dict) and set(parameters) <= allowed[method],
                      'invalid_request', '统一输入请求字段不支持')
        if method == 'run':
            input_require('plan' in parameters, 'invalid_plan', '缺少 plan')
            if parameters['plan'].get('backend', 'game') == 'windows-sendinput':
                return self.executor.run(**parameters)
            input_require(self.executor.active is None, 'busy', 'Windows 输入正在执行或清理未确认')
        operation = parameters.get('operation')
        if method in ('status', 'cancel') and operation in self.executor.operations:
            if method == 'status': return self.executor.status(**parameters)
            with self.condition:
                self.commands.append(operation); self.condition.notify_all()
            return dict(self.executor.status(operation), cancel_requested=True)
        if method == 'stop' and self.executor.active is not None:
            with self.condition:
                self.commands.append(None); self.condition.notify_all()
            return dict(self.executor.status(), cancel_requested=True)
        result = self.game(method, parameters)
        if method == 'status' and operation is None:
            windows_status = self.executor.status(details=parameters.get('details', False))
            if result.get('code') == 'not_installed':
                result = dict(windows_status, game_installed=False)
            if windows_status.get('active') is not None:
                result['active'] = windows_status['active']
            result['windows_last_operation'] = windows_status.get('last_operation')
        if method == 'stop' and result.get('code') == 'not_installed':
            result = dict(self.executor.status(), game_installed=False)
        if method == 'capabilities':
            descriptors = {}
            for name, descriptor in INPUT_ACTIONS.items():
                supported = os.name == 'nt' and not name.startswith(('player.', 'ui.'))
                descriptors[name] = dict(descriptor, schema=input_action_schema(name), supported=supported,
                                         reason=None if supported else 'not_supported')
            windows = {'backend': 'windows-sendinput', 'actions': descriptors, 'limits': dict(INPUT_LIMITS),
                       'clock_source': 'time.perf_counter', 'foreground_required': True}
            if result.get('code') == 'not_installed':
                result = {'ok': True, 'installed': False, 'actions': {}, 'hint': '游戏后端先执行 runtime install'}
            result['backends'] = {'game': {k: v for k, v in result.items() if k != 'transport'}, 'windows-sendinput': windows}
        return result

    def close(self):
        with self.condition:
            self.closed = True; self.commands.append(None); self.condition.notify_all()
        self.thread.join(timeout=10)

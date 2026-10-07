# coding: utf-8
"""游戏内统一输入适配；复用已验证的玩家/UI 动作，不伪造设备输入。"""
try:
    InputExecutor
except NameError:
    from ..input_executor import InputExecutor
    from ..input_plan import (INPUT_ACTIONS, INPUT_LIMITS, INPUT_KEY_ALIASES, GAME_KEY_NAMES, input_action_schema, game_key_code,
                             input_require, InputPlanError, input_key_plan, normalize_input_plan)
    from .runtime_key_timeline_payload import key_timeline_clock
    from .runtime_ui_payload import as_text, operation_view


class GameInputAdapter(object):
    backend = 'game'
    input_path = 'game-keyboard'

    def __init__(self, owner):
        self.owner = owner
        self.ui, self.player = owner.ui, owner.player
        self.api, self.gui = self.ui.api, self.ui.gui
        self.clock, self.clock_source = key_timeline_clock()

    def ready(self):
        input_require(not self.owner.closed and not self.ui.closed and not self.player.closed, 'not_installed', '请重新 runtime install')
        input_require(self.clock is not None, 'not_supported', '当前运行包没有经过确认的单调时钟')
        input_require(self.owner.external_operation is None and self.ui.active is None and self.player.active is None
                      and not self.player.sequence_busy(), 'busy', '上一控制层输入尚未结束或释放')
        self.player._alive()

    def validate(self, plan):
        input_require(plan['backend'] == 'game', 'not_supported', '游戏内 Python 入口不执行 Windows 设备输入；用公开 CLI run')
        caps = self.owner.capabilities()['actions']
        state = self.player._read()
        result = {'keys': {}, 'identity': (state['player_id'], self.api.GetLevelId(), state['dimension']),
                  'top': self.api.GetTopUI(), 'generation': self.ui.generation}
        held = set()
        enum = self.api.GetMinecraftEnum().KeyBoardType
        for step in plan['steps']:
            name = step['action']
            input_require(caps[name]['supported'], 'not_supported', '当前会话不支持 '+name)
            for key in step.get('keys', []) + ([step['key']] if 'key' in step else []):
                code = game_key_code(key, enum)
                result['keys'][key] = code
            if name == 'key':
                codes = [result['keys'][k] for k in step['keys']]
                input_require(len(set(codes)) == len(codes) and not held.intersection(codes), 'invalid_plan', '键码别名冲突')
            elif name in ('key_down', 'key_up'):
                code = result['keys'][step['key']]
                input_require(code not in held if name == 'key_down' else code in held, 'invalid_plan', '键码生命周期冲突')
                if name == 'key_down': held.add(code)
                else: held.remove(code)
            if name.startswith('player.'):
                input_require(self.player._hud(), 'menu_open', '玩家语义动作需要 HUD')
            if name == 'player.move':
                movement = {getattr(enum, 'KEY_'+k, None) for k in ('W', 'A', 'S', 'D')}
                input_require(not held.intersection(movement), 'input_conflict', '方向键保持期间不能接管移动向量')
            if name.startswith('ui.'):
                # 预检目标及角色，在按修饰键之前拒绝非法快照/参数。
                role = {'ui.click': ('button', 'toggle', 'edit'), 'ui.slide': ('slider',),
                        'ui.scroll': ('scroll',), 'ui.set_control_value': ('edit', 'toggle', 'slider')}[name]
                row, scan = self.ui._target(step['node'], step['snapshot'], role)
                if name in ('ui.click', 'ui.slide'):
                    input_require(row['in_view'] and row['enabled'] is not False, 'offscreen', '目标不可见或禁用')
                if name == 'ui.set_control_value':
                    value = step['value']
                    input_require((isinstance(value, (str, type(u''))) if row['role'] == 'edit' else
                                   type(value) is bool if row['role'] == 'toggle' else type(value) in (int, float)),
                                  'invalid_plan', '控件赋值类型与角色不符')
        return result

    def prepare(self, op):
        pass

    def schedule(self, delay, callback):
        timer = self.api.GetEngineCompFactory().CreateGame(self.api.GetLevelId()).AddTimer(delay, callback)
        input_require(timer is not None, 'timer_unavailable', '无法安排输入回调，未继续提交')

    def guard(self, op):
        pid = self.player._alive()
        identity = (pid, self.api.GetLevelId(), self.api.GetEngineCompFactory().CreateGame(self.api.GetLevelId()).GetCurrentDimension())
        input_require(identity == op['_bindings']['identity'], 'world_changed', '玩家或世界已变化')
        stage = op.get('_stage')
        ui_step = stage is not None and stage['step']['action'].startswith('ui.')
        if not ui_step:
            input_require(self.api.GetTopUI() == op['_bindings']['top'] and self.ui.generation == op['_bindings']['generation'],
                          'ui_changed', '界面已变化，停止后续输入')

    def binding(self, op, kind, key):
        return op['_bindings']['keys'][key]

    @staticmethod
    def identity(kind, value):
        return (kind, value)

    def send(self, kind, binding, down):
        return bool(self.gui.simulate_keyboard_event(binding, down))

    def _calling(self, function, *args, **kwargs):
        self.owner._calling = True
        try: return function(*args, **kwargs)
        finally: self.owner._calling = False

    def begin(self, op, stage):
        step = stage['step']; name = step['action']
        parameters = {k: v for k, v in step.items() if k not in ('action', 'at_ms', 'expect', 'keys')}
        if name.startswith('player.'):
            before = self.player.snapshot()
            expect = step.get('expect', {})
            input_require('selected_slot' not in expect or expect['selected_slot'] == before['selected_slot'], 'expectation_failed', '选槽不符合断言')
            input_require('item' not in expect or expect['item'] == (before['carried'] or {}).get('name'), 'expectation_failed', '手持物品不符合断言')
            input_require(all(before['target'].get(k) == v for k, v in expect.get('target', {}).items()), 'expectation_failed', '目标不符合断言')
            method = name.split('.', 1)[1]
            if method in ('attack', 'dig', 'use_item', 'eat', 'shoot'): parameters['snapshot'] = before['snapshot']
            if method in ('use_item', 'eat', 'shoot'): parameters['hold_ms'] = parameters.pop('duration_ms')
            result = self._calling(getattr(self.player, method), **parameters)
            stage.update(kind='player', child=result['id'], input_path='game-player:'+method)
        else:
            method = name.split('.', 1)[1]
            stage['modifiers'] = list(step.get('keys', []))
            for key in stage['modifiers']:
                self.owner.edge(op, 'key', key, True)
            if method in ('click', 'slide'):
                fraction = parameters.pop('fraction', .5)
                duration = parameters.pop('duration_ms')
                result = self._calling(self.ui._pointer, fraction=fraction, action=method,
                                       request_id=None, hold_ms=duration, **parameters)
            else:
                result = self._calling(getattr(self.ui, method), **parameters)
            stage.update(kind='ui', child=result['id'], input_path=result.get('backend', 'game-ui'))

    def poll(self, op, stage):
        controller = self.player if stage['kind'] == 'player' else self.ui
        child = controller.operations[stage['child']]
        if child['state'] == 'pending': return False
        input_require(child['state'] == 'completed', child.get('code', 'step_failed'), child.get('error', '动作没有完成'))
        if stage['kind'] == 'player':
            if child['action'] == 'move' and any(abs(v) > .01 for v in self.player._read()['input_vector']):
                deadline = stage.setdefault('release_deadline', self.clock()+1.)
                input_require(self.clock() < deadline, 'input_busy', '移动解锁后输入没有归零')
                return False
            expected = child.get('expected_rotation')
            if expected:
                rotation = self.player._read()['rotation']
                input_require(abs(rotation['pitch']-expected['pitch']) <= .2 and
                              abs((rotation['yaw']-expected['yaw']+180)%360-180) <= .2, 'rotation_changed', '朝向没有保持')
        for key in reversed(stage.get('modifiers', [])):
            self.owner.edge(op, 'key', key, False)
        stage['modifiers'] = []
        # 不复制整份快捷栏到逐步日志；消费/命中仍由独立观察验证。
        stage['result'] = {k: child[k] for k in ('state', 'accepted', 'released', 'code', 'verification', 'block_removed_observed') if k in child}
        return True

    def cleanup(self, op):
        stage = op.get('_stage')
        if stage and stage.get('child'):
            controller = self.player if stage['kind'] == 'player' else self.ui
            child = controller.operations.get(stage['child'])
            if child and controller.active is child:
                self._calling(controller._release, child, 'cancelled')
                input_require(child.get('released'), 'release_failed', '子动作释放未确认')

    def finished(self, op):
        self.player.observation = self.ui.observation = None


class GameInputController(InputExecutor):
    def __init__(self, ui, player):
        self.ui, self.player = ui, player
        self.closed = False
        self._calling = self._observing = False
        self.external_operation = None
        self.external_history = {}
        InputExecutor.__init__(self, GameInputAdapter(self))

    def capabilities(self):
        player = self.player.capabilities()['capabilities']
        ui = self.ui.capabilities()['capabilities']
        actions = {}
        available = not self.closed and self.adapter.clock is not None and not self.ui.closed and self.ui.events is not None
        for name, descriptor in INPUT_ACTIONS.items():
            capability = descriptor['capability']
            supported = (not name.startswith('pointer.') and
                         (ui.get(capability, False) if name.startswith('ui.') else
                          player.get('use_air', False) or player.get('use_block', False) if capability == 'use_air_or_block' else
                          player.get(capability, False) if capability else True))
            actions[name] = dict(descriptor, schema=input_action_schema(name), supported=bool(available and supported),
                                 reason=None if available and supported else 'missing_monotonic_clock' if self.adapter.clock is None else 'not_supported')
        keys = []
        try:
            enum = self.player.api.GetMinecraftEnum().KeyBoardType
            reverse = {value: key for key, value in GAME_KEY_NAMES.items()}
            for name in dir(enum):
                if not name.startswith('KEY_'): continue
                key = reverse.get(name[4:], name[4:])
                try:
                    game_key_code(key, enum); keys.append(key)
                except InputPlanError: pass
        except Exception: pass
        return {'ok': True, 'schema_versions': [1], 'backend': 'game', 'installed': not self.closed,
                'clock_source': self.adapter.clock_source, 'actions': actions, 'limits': dict(INPUT_LIMITS),
                'key_aliases': dict(INPUT_KEY_ALIASES), 'dispatch_phase': 'unknown',
                'keys': sorted(set(keys)),
                'limitations': ['effect_requires_verification', 'pause_may_block_cleanup', 'manual_input_ownership_unknown'],
                'external_operation': self.external_operation}

    def observe(self, view='auto', query=None, limit=80, offset=0, details=False):
        input_require(view in ('auto', 'player', 'ui'), 'invalid_argument', 'view 必须为 auto/player/ui')
        if view == 'auto': view = 'player' if self.player._hud() else 'ui'
        self._observing = True
        try:
            if view == 'player': result = self.player.snapshot()
            elif as_text(self.ui.api.GetTopUI()).startswith('ui://'):
                result = {'ok': True, 'screen': self.ui.api.GetTopUI(), 'snapshot': None, 'nodes': [],
                          'observation_available': False, 'code': 'unsupported_ui', 'hint': 'HBUI 节点不可读；可使用内部键盘或后台截图观察'}
            else: result = self.ui.snapshot(query=query, limit=limit, offset=offset, details=details)
        finally:
            self._observing = False
        result.update(view=view, allowed_actions=sorted(name for name, descriptor in self.capabilities()['actions'].items()
            if descriptor['supported'] and (view == 'player' and not name.startswith('ui.') or
                view == 'ui' and not name.startswith('player.') and (not name.startswith('ui.') or result.get('snapshot') is not None))))
        return result

    def changed(self):
        if self.active is not None:
            stage = self.active.get('_stage')
            if not (stage and stage['step']['action'].startswith('ui.')):
                self._finish(self.active, 'cancelled', 'ui_changed')

    def stop(self):
        result = InputExecutor.stop(self)
        if self.external_operation is not None:
            return dict(result, ok=False, code='busy', error='设备操作仍预留输入，请通过公开 CLI input stop 查询清理')
        # 旧入口也属于同一临时控制层；统一 stop 可以释放其遗留输入。
        self._calling = True
        try:
            legacy = self.player.stop()
            if self.ui.active is not None:
                self.ui._release(self.ui.active, 'cancelled')
            result['ok'] = result['ok'] and legacy['ok'] and self.ui.active is None
        finally:
            self._calling = False
        return result

    def close(self):
        result = self.stop()
        input_require(result['ok'], 'release_failed', '统一输入释放未确认，保留控制层供 stop 重试')
        self.closed = True

    def dispatch(self, action, **parameters):
        try:
            input_require(action in ('capabilities', 'observe', 'run', 'key', 'status', 'cancel', 'stop', '_reserve', '_unreserve'), 'unknown_action', '未知统一输入操作')
            return getattr(self, action)(**parameters)
        except Exception as error:
            return {'ok': False, 'code': getattr(error, 'code', 'runtime_api_error'), 'error': as_text(error)[:512]}

    def run(self, plan, request_id=None):
        input_require(request_id not in self.external_history, 'request_conflict', '该 ID 已用于设备后端')
        return InputExecutor.run(self, plan, request_id)

    def _reserve(self, operation, signature=None):
        with self.lock:
            if self.external_operation == operation: return {'ok': True}
            input_require(self.active is None, 'busy', '游戏内输入正在执行')
            input_require(operation not in self.operations, 'request_conflict', '该 ID 已用于游戏后端')
            input_require(self.external_operation is None and self.ui.active is None and self.player.active is None
                          and not self.player.sequence_busy(), 'busy', '已有游戏内控制层输入')
            self.external_operation = operation
            self.external_history[operation] = signature
            if len(self.external_history) > 64:
                self.external_history.pop(next(iter(self.external_history)))
            return {'ok': True}

    def _unreserve(self, operation):
        with self.lock:
            input_require(self.external_operation in (None, operation), 'busy', '预留属于另一操作')
            self.external_operation = None
            return {'ok': True}

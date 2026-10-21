# coding: utf-8
"""统一计划状态机；后端负责时钟、调度和提交，状态机不直接依赖引擎。"""
from __future__ import unicode_literals
import json
import threading
import uuid

try:
    normalize_input_plan
except NameError:
    from .input_plan import (normalize_input_plan, input_signature, input_require, InputPlanError,
                             INPUT_LIMITS, INPUT_ACTIONS, input_key_plan)


class InputExecutor(object):
    def __init__(self, adapter):
        self.adapter = adapter
        self.active = None
        self.operations, self.order = {}, []
        self.lock = threading.RLock()

    def _view(self, op, details=False):
        if op is None: return None
        value = {k: v for k, v in op.items() if not k.startswith('_')}
        if not details:
            for key in ('plan', 'steps', 'events', 'cleanup_events'): value.pop(key, None)
        return json.loads(json.dumps(value, ensure_ascii=True, allow_nan=False))

    def _error(self, op, error):
        try: message = unicode(error)
        except NameError: message = str(error)
        if len(message) > 512: op['logs_truncated'] = True
        return message[:512]

    def _log(self, op, family, row):
        size = len(input_signature(row))
        op[family].append(row); op['_log_bytes'] += size
        while op['_log_bytes'] > INPUT_LIMITS['log_bytes']:
            target = next(key for key in ('cleanup_events', 'events', 'steps') if op[key])
            old = op[target].pop(0)
            op['_log_bytes'] -= len(input_signature(old))
            op[target+'_dropped'] += 1
            op['logs_truncated'] = True

    def run(self, plan, request_id=None):
        normalized = normalize_input_plan(plan)
        request_id = request_id or uuid.uuid4().hex
        input_require(isinstance(request_id, str) or isinstance(request_id, type(u'')), 'invalid_request_id', 'request_id 必须是字符串')
        input_require(len(request_id) == 32 and all(c in '0123456789abcdef' for c in request_id),
                      'invalid_request_id', 'request_id 必须是 32 位小写十六进制')
        signature = input_signature(normalized)
        with self.lock:
            previous = self.operations.get(request_id)
            if previous is not None:
                input_require(previous['_signature'] == signature, 'request_conflict', 'request_id 已用于不同计划')
                return self._view(previous, True)
            input_require(self.active is None, 'busy', '当前输入未结束或释放未确认，查询 status 或 stop')
            self.adapter.ready()
            bindings = self.adapter.validate(normalized)
            op = {'ok': True, 'operation_id': request_id, 'request_id': request_id, 'state': 'pending',
                  'backend': normalized['backend'], 'clock': 'monotonic_ms', 'clock_source': self.adapter.clock_source,
                  'effect_verified': False, 'released': False, 'started': False, 'index': 0, 'count': len(normalized['steps']),
                  'plan': normalized, 'steps': [], 'events': [], 'cleanup_events': [], 'held_keys': [],
                  'unconfirmed_release_keys': [], 'logs_truncated': False,
                  'steps_dropped': 0, 'events_dropped': 0, 'cleanup_events_dropped': 0,
                  '_signature': signature, '_bindings': bindings, '_held': [], '_stage': None,
                  '_started': None, '_deadline': self.adapter.clock()+INPUT_LIMITS['execution_ms']/1000.,
                  '_log_bytes': 0, '_finishing': False}
            self.operations[request_id] = op; self.order.append(request_id)
            while len(self.order) > INPUT_LIMITS['history']:
                self.operations.pop(self.order.pop(0), None)
            self.active = op
            self._schedule(op, 0.)
            return self._view(op, True)

    def key(self, keys, duration_ms=80, request_id=None):
        return self.run(input_key_plan(keys, duration_ms), request_id)

    def status(self, operation=None, details=False):
        with self.lock:
            if operation is None:
                return {'ok': True, 'active': self._view(self.active, details),
                        'last_operation': self._view(self.operations.get(self.order[-1]) if self.order else None, details)}
            input_require(operation in self.operations, 'operation_not_found', '记录不存在或已淘汰，不代表从未执行')
            return self._view(self.operations[operation], details)

    def cancel(self, operation):
        with self.lock:
            input_require(operation in self.operations, 'operation_not_found', '操作记录不存在')
            op = self.operations[operation]
            if self.active is op: self._finish(op, 'cancelled', 'requested_cancel')
            return self._view(op)

    def stop(self):
        with self.lock:
            if self.active is not None: self._finish(self.active, 'cancelled', 'requested_stop')
            return dict(self.status(), ok=self.active is None)

    def relative_ms(self, op):
        return None if op['_started'] is None else (self.adapter.clock()-op['_started'])*1000.

    def _schedule(self, op, seconds):
        try:
            self.adapter.schedule(seconds, lambda: self._tick(op))
        except Exception as error:
            self._fail(op, error)

    def _fail(self, op, error):
        op['error'] = self._error(op, error)
        stage = op.get('_stage')
        if stage is not None and not stage.get('failure_logged'):
            self._log(op, 'steps', dict(index=op['index'], action=stage['step']['action'],
                at_ms=stage['step']['at_ms'], started_ms=stage['started_ms'], finished_ms=self.relative_ms(op),
                result={'state': 'failed', 'code': getattr(error, 'code', 'input_error'), 'error': op['error']},
                input_path=stage.get('input_path', self.adapter.input_path)))
            stage['failure_logged'] = True
        self._finish(op, 'failed', getattr(error, 'code', 'input_error'))

    def _guard(self, op):
        input_require(self.adapter.clock() < op['_deadline'], 'input_timeout', '输入超过 125 秒执行上限')
        self.adapter.guard(op)

    def _tick(self, op):
        with self.lock:
            if self.active is not op or op['state'] != 'pending': return
            try:
                if not op['started']:
                    self.adapter.prepare(op)
                    self._guard(op)
                    op['_started'] = self.adapter.clock()
                    op.update(started=True, started_at=op['_started'])
                while self.active is op and op['state'] == 'pending':
                    self._guard(op)
                    if op['_stage'] is not None:
                        stage = op['_stage']
                        if not self._poll(op, stage):
                            self._schedule(op, .01)
                            return
                        op['_stage'] = None
                        if self.active is not op or op['state'] != 'pending': return
                        self._log(op, 'steps', dict(index=op['index'], action=stage['step']['action'],
                            at_ms=stage['step']['at_ms'], started_ms=stage['started_ms'],
                            finished_ms=self.relative_ms(op), result=stage.get('result', {}),
                            input_path=stage.get('input_path', self.adapter.input_path)))
                        op['index'] += 1
                    if op['index'] >= op['count']:
                        self._finish(op, 'completed')
                        return
                    step = op['plan']['steps'][op['index']]
                    actual = self.relative_ms(op)
                    if actual < step['at_ms']:
                        self._schedule(op, max(.001, min(.05, (step['at_ms']-actual)/1000.)))
                        return
                    maximum = op['plan']['max_lateness_ms']
                    input_require(maximum is None or actual-step['at_ms'] <= maximum,
                                  'deadline_missed', '步骤迟到超过 max_lateness_ms')
                    stage = {'step': step, 'started_ms': actual, 'started_at': self.adapter.clock(), 'kind': 'instant'}
                    op['_stage'] = stage
                    self._begin(op, stage)
            except Exception as error:
                self._fail(op, error)

    def _begin(self, op, stage):
        step = stage['step']; name = step['action']
        if name == 'wait':
            stage.update(kind='duration', until=stage['started_at']+step['duration_ms']/1000., input_path='scheduler')
        elif name == 'key':
            stage['kind'] = 'key'
            stage['keys'] = list(step['keys'])
            for key in step['keys']:
                self.edge(op, 'key', key, True)
                if self.active is not op or op['state'] != 'pending': return
            stage['until'] = stage['started_at']+step['duration_ms']/1000.
        elif name in ('key_down', 'key_up'):
            self.edge(op, 'key', step['key'], name == 'key_down')
        elif name in ('pointer.down', 'pointer.up'):
            self.edge(op, 'pointer', step['button'], name == 'pointer.down')
        else:
            self.adapter.begin(op, stage)

    def _poll(self, op, stage):
        if stage['kind'] in ('duration', 'key'):
            if self.adapter.clock() < stage['until']: return False
            if stage['kind'] == 'key':
                for key in reversed(stage['keys']): self.edge(op, 'key', key, False)
            return True
        if stage['kind'] == 'instant': return True
        return self.adapter.poll(op, stage)

    def edge(self, op, kind, key, down, cleanup=False):
        binding = self.adapter.binding(op, kind, key)
        identity = self.adapter.identity(kind, binding)
        owned = next((row for row in op['_held'] if row['identity'] == identity), None)
        input_require(owned is None if down else owned is not None, 'input_conflict', '输入边沿与本计划持有状态冲突')
        if down:
            owned = {'kind': kind, 'key': key, 'binding': binding, 'identity': identity, 'index': op['index']}
            op['_held'].append(owned)
            self._held(op)
        row = {'index': op['index'], 'action': kind+('_down' if down else '_up'), 'key': key,
               'started_ms': self.relative_ms(op), 'accepted': None, 'input_path': self.adapter.input_path}
        if cleanup: row['release_of_index'] = owned['index']
        else:
            row['at_ms'] = op['plan']['steps'][op['index']]['at_ms']
            row['lateness_ms'] = max(0., row['started_ms']-row['at_ms'])
        try:
            accepted = self.adapter.send(kind, binding, down)
            row['accepted'] = accepted
            row.update(getattr(self.adapter, 'last_send', {}))
            input_require(accepted is True, 'release_failed' if not down else 'input_rejected', '输入接口未确认提交')
            if not down and owned in op['_held']:
                op['_held'].remove(owned)
                self._held(op)
        except Exception as error:
            row['error'] = self._error(op, error)
            raise
        finally:
            row.update(finished_ms=self.relative_ms(op), held_keys=list(op['held_keys']))
            self._log(op, 'cleanup_events' if cleanup else 'events', row)

    @staticmethod
    def _held(op):
        op['held_keys'] = [row['key'] if row['kind'] == 'key' else 'pointer:'+row['key'] for row in op['_held']]

    def _finish(self, op, state, code=None):
        if op['_finishing']: return
        op['_finishing'] = True
        if op['state'] == 'pending':
            op['_terminal'] = state
            if code: op['code'] = code
        op['state'] = op.get('_terminal', state)
        failures = []
        try:
            self.adapter.cleanup(op)
        except Exception as error:
            failures.append('action')
            op['cleanup_error'] = self._error(op, error)
        for row in reversed(list(op['_held'])):
            try: self.edge(op, row['kind'], row['key'], False, cleanup=True)
            except Exception as error:
                op['cleanup_error'] = self._error(op, error)
        op['unconfirmed_release_keys'] = list(op['held_keys'])+failures
        op['released'] = not op['unconfirmed_release_keys']
        op.update(ok=op['_terminal'] in ('completed', 'cancelled') and op['released'],
                  state=op['_terminal'] if op['released'] else 'unknown', finished_ms=self.relative_ms(op), _finishing=False)
        if op['released'] and self.active is op: self.active = None
        self.adapter.finished(op)

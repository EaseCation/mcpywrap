# coding: utf-8
"""临时客户端按键边沿时间线；不以脚本回调次数模拟游戏 tick。"""
import json
import sys
import time

try:
    UIError
except NameError:
    from .runtime_ui_payload import UIError, require, as_text, operation_view, integer_types


def key_timeline_clock():
    clock = getattr(time, 'monotonic', None)
    if callable(clock):
        return clock, 'time.monotonic'
    # 新原生运行包可提供主线程内可调用的 steady_clock，不依赖每次 RPC。
    try:
        import _mcpy_launcher
        clock = getattr(_mcpy_launcher, 'monotonic', None)
        if callable(clock):
            return clock, 'launcher.steady_clock'
    except ImportError:
        pass
    # Python 2 Windows 的 clock 使用性能计数器；其他平台可能是 CPU 时间。
    clock = getattr(time, 'clock', None)
    if sys.platform == 'win32' and callable(clock):
        return clock, 'windows.time.clock'
    return None, None


class KeyTimelineMixin(object):
    def _timeline_available(self):
        if self.closed or self.ui.closed or self.timeline_clock is None or self.ui.events is None:
            return False
        try:
            return (callable(getattr(self.gui, 'simulate_keyboard_event', None)) and
                    callable(getattr(self._factory().CreateGame(self.api.GetLevelId()), 'AddTimer', None)))
        except Exception:
            return False

    def _validate_key_timeline(self, plan):
        require(isinstance(plan, dict) and set(plan) <= {'schema_version', 'clock', 'events', 'max_lateness'}
                and {'schema_version', 'clock', 'events'} <= set(plan), 'invalid_plan', '时间线字段缺失或不支持')
        require(type(plan['schema_version']) in integer_types and plan['schema_version'] == 1,
                'invalid_plan', '时间线 schema_version 必须为 1')
        require(plan['clock'] == 'monotonic_ms', 'not_supported', '时间线仅支持 monotonic_ms，不支持 tick 时钟')
        lateness = plan.get('max_lateness')
        require(lateness is None or type(lateness) in integer_types and lateness >= 0,
                'invalid_plan', 'max_lateness 必须为非负整数毫秒或 null')
        events = plan['events']
        require(isinstance(events, list) and 1 <= len(events) <= 256,
                'invalid_plan', '时间线必须包含 1–256 个事件')
        normalized, codes, held, previous = [], [], set(), 0
        for event in events:
            require(isinstance(event, dict) and set(event) == {'at', 'action', 'key'},
                    'invalid_plan', '事件只接受 at/action/key')
            at, action, key = event['at'], event['action'], event['key']
            require(type(at) in integer_types and previous <= at <= 120000,
                    'invalid_plan', '事件时间必须为有序的非负整数，最大 120000ms')
            require(action in ('key_down', 'key_up'), 'invalid_plan', '事件只支持 key_down/key_up')
            require(isinstance(key, (str, type(u''))) and '+' not in key,
                    'invalid_plan', '每个事件只能操作一个键')
            code = self._key_codes(key)[0]
            require((code not in held) if action == 'key_down' else (code in held),
                    'invalid_plan', '按键重复按下或没有对应按下；按键别名按同一键校验')
            if action == 'key_down':
                held.add(code)
            else:
                held.remove(code)
            normalized.append({'at': at, 'action': action, 'key': key.strip().upper()})
            codes.append(code)
            previous = at
        require(not held, 'invalid_plan', '计划结尾必须释放全部按键')
        return {'schema_version': 1, 'clock': 'monotonic_ms', 'max_lateness': lateness,
                'events': normalized}, codes

    def timeline(self, plan, request_id=None):
        normalized, codes = self._validate_key_timeline(plan)
        op, repeated = self._operation(request_id, ['timeline', normalized])
        if repeated:
            return self._view(op)
        require(self._timeline_available(), 'not_supported', '当前会话缺少单调时钟、按键或定时器/生命周期能力')
        self._ready('timeline')
        before = self._read()
        op.update(action='timeline', state='pending', backend='game-client-keyboard',
                  clock='monotonic_ms', clock_source=self.timeline_clock_source,
                  plan=normalized, count=len(codes), index=0, events=[], cleanup_events=[],
                  events_dropped=0, cleanup_events_dropped=0, logs_truncated=False,
                  held_keys=[], unconfirmed_release_keys=[], released=False, effect_verified=False,
                  started=False, _codes=codes, _held=[], _started=None, _log_bytes=0,
                  _deadline=self.timeline_clock()+125., _identity=(before['player_id'], self.api.GetLevelId(), before['dimension']))
        self._save(op)
        self.active = op
        self._schedule_key_timeline(op, 0.)
        return self._view(op)

    def _timeline_relative_ms(self, op):
        return None if op['_started'] is None else (self.timeline_clock()-op['_started'])*1000.

    @staticmethod
    def _timeline_held(op):
        op['held_keys'] = [row['key'] for row in op['_held']]

    def _timeline_guard(self, op):
        require(self.timeline_clock() < op['_deadline'], 'timeline_timeout', '时间线超过 125 秒墙钟上限')
        pid = self._alive()
        require((pid, self.api.GetLevelId(), self._factory().CreateGame(self.api.GetLevelId()).GetCurrentDimension())
                == op['_identity'], 'world_changed', '时间线所在玩家或世界已变化')
        require(self._hud(), 'menu_open', '界面已离开游戏 HUD')

    def _schedule_key_timeline(self, op, delay):
        try:
            timer = self._factory().CreateGame(self.api.GetLevelId()).AddTimer(delay, lambda: self._key_timeline_tick(op))
            require(timer is not None, 'timer_unavailable', '无法安排时间线回调')
        except Exception as exc:
            self._timeline_fail(op, exc)

    def _timeline_fail(self, op, exc):
        op.update(code=getattr(exc, 'code', 'input_error'), error=self._timeline_error(op, exc))
        self._release_key_timeline(op, 'failed')

    @staticmethod
    def _timeline_error(op, exc):
        message = as_text(exc)
        if len(message) > 512:
            op['logs_truncated'] = op['error_truncated'] = True
        return message[:512]

    @staticmethod
    def _timeline_log(op, family, record):
        # 留出 JSON 编码和计划的空间，避免有界条数日志仍超过运行时结果上限。
        size = len(json.dumps(record, ensure_ascii=True, separators=(',', ':')))
        op[family].append(record)
        op['_log_bytes'] += size
        while op['_log_bytes'] > 96*1024 or len(op['cleanup_events']) > 512:
            target = 'cleanup_events' if op['cleanup_events'] else 'events'
            removed = op[target].pop(0)
            op['_log_bytes'] -= len(json.dumps(removed, ensure_ascii=True, separators=(',', ':')))
            op[target+'_dropped'] += 1
            op['logs_truncated'] = True

    def _key_timeline_tick(self, op):
        if self.active is not op or op['state'] != 'pending':
            return
        try:
            self._timeline_guard(op)
            if op['_started'] is None:
                op['_started'] = self.timeline_clock()
                op['started'] = True
                op['started_at'] = op['_started']
            while op['index'] < op['count'] and self.active is op and op['state'] == 'pending':
                self._timeline_guard(op)
                index = op['index']
                event = op['plan']['events'][index]
                actual = self._timeline_relative_ms(op)
                remaining = event['at']-actual
                if remaining > 0:
                    # 有界巡检用于检查超时与世界状态，不把回调称为模拟 tick。
                    self._schedule_key_timeline(op, max(.001, min(.05, remaining/1000.)))
                    return
                lateness = max(0., actual-event['at'])
                maximum = op['plan']['max_lateness']
                require(maximum is None or lateness <= maximum, 'deadline_missed', '事件迟到超过 max_lateness')
                code = op['_codes'][index]
                down = event['action'] == 'key_down'
                if down:
                    # 原生调用异常也可能已经产生输入，因此先登记清理责任。
                    op['_held'].append({'code': code, 'key': event['key'], 'index': index})
                    self._timeline_held(op)
                record = dict(event, index=index, keycode=code, started_ms=actual,
                              lateness_ms=lateness, accepted=None, result='unknown')
                try:
                    accepted = bool(self.gui.simulate_keyboard_event(code, down))
                    record.update(accepted=accepted, result='accepted' if accepted else 'rejected')
                    require(accepted, 'input_rejected', '引擎拒绝按键边沿')
                    if not down:
                        op['_held'] = [row for row in op['_held'] if row['code'] != code]
                        self._timeline_held(op)
                except Exception as exc:
                    record['error'] = self._timeline_error(op, exc)
                    raise
                finally:
                    record.update(finished_ms=self._timeline_relative_ms(op), held_keys=list(op['held_keys']))
                    self._timeline_log(op, 'events', record)
                    op['index'] += 1
                    self.observation = self.ui.observation = None
            if self.active is op and op['state'] == 'pending':
                self._release_key_timeline(op, 'completed')
        except Exception as exc:
            self._timeline_fail(op, exc)

    def _release_key_timeline(self, op, state='completed'):
        if op.get('released') or op.get('_releasing'):
            return
        if op['state'] == 'pending':
            op['_terminal'] = state
        op['_releasing'] = True
        # 先使排队回调失效；释放失败也绝不能继续计划。
        op['state'] = op.get('_terminal', state)
        failures = []
        for row in reversed(op['_held']):
            record = dict(action='key_up', key=row['key'], keycode=row['code'], release_of_index=row['index'],
                          started_ms=self._timeline_relative_ms(op), accepted=None, result='unknown')
            try:
                accepted = bool(self.gui.simulate_keyboard_event(row['code'], False))
                record.update(accepted=accepted, result='accepted' if accepted else 'rejected')
                require(accepted, 'release_failed', '按键释放未确认')
                op['_held'] = [held for held in op['_held'] if held['code'] != row['code']]
                self._timeline_held(op)
            except Exception as exc:
                failures.append(row)
                record['error'] = self._timeline_error(op, exc)
                op['cleanup_error'] = record['error']
            record['finished_ms'] = self._timeline_relative_ms(op)
            record['held_keys'] = list(op['held_keys'])
            self._timeline_log(op, 'cleanup_events', record)
        op['_held'] = list(reversed(failures))
        self._timeline_held(op)
        op.update(_releasing=False, released=not failures, unconfirmed_release_keys=list(op['held_keys']),
                  state='unknown' if failures else op.get('_terminal', state), finished_ms=self._timeline_relative_ms(op))
        if not failures and self.active is op:
            self.active = None
        self.observation = self.ui.observation = None

    def _timeline_unload(self):
        if self.active and self.active.get('action') == 'timeline':
            self.active.update(code='world_unloaded', end_reason='world_unloaded')
            self._release_key_timeline(self.active, 'cancelled')

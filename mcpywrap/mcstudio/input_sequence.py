"""Bounded Windows input timelines; timestamps describe SendInput, not game receipt."""
import ctypes as C
from ctypes import wintypes as W
import time

from .window import Input, InputSender, Mouse, MODIFIERS, keyboard_input, parse_keys
from ..timeline import compile_timeline


MAX_EVENTS = 256
MAX_DURATION_MS = 10000
BUTTONS = {'left': (1, 2, 4), 'right': (2, 8, 16), 'middle': (4, 32, 64)}
FIELDS = {'key_down': {'key'}, 'key_up': {'key'},
          'mouse_down': {'button'}, 'mouse_up': {'button'},
          'move': {'x', 'y'}, 'relative': {'dx', 'dy'}, 'wheel': {'delta'}}


def validate_events(events, width=None, height=None, max_lateness_ms=None):
    """Validate the whole plan before focus changes or input; never sort user events."""
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_EVENTS:
        raise ValueError('events 必须包含 1–256 个事件')
    if max_lateness_ms is not None and (type(max_lateness_ms) is not int or not 0 <= max_lateness_ms <= MAX_DURATION_MS):
        raise ValueError('max_lateness_ms 必须为 0–10000 整数')
    if (width is not None or height is not None) and (type(width) is not int or type(height) is not int or
                                                   not 1 <= width * height <= 32000000 or min(width, height) < 1):
        raise ValueError('width/height 必须同时提供有效客户区尺寸')
    if not all(isinstance(event, dict) for event in events):
        raise ValueError('每个事件必须是对象')
    events = compile_timeline(events, [0] * len(events), MAX_DURATION_MS)
    plan, held = [], set()
    for source in events:
        if not isinstance(source.get('type'), str) or source['type'] not in FIELDS:
            raise ValueError('未知输入事件类型')
        kind = source['type']
        if set(source) != {'at_ms', 'type'} | FIELDS[kind]:
            raise ValueError('事件字段缺失或多余：' + kind)
        row = dict(source)
        identity = None
        if kind.startswith('key_'):
            if not isinstance(source['key'], str) or len(source['key']) > 40:
                raise ValueError('key 必须为单个键名或 VK/SC/E0 代码')
            keys = parse_keys(source['key'])
            if len(keys) != 1:
                raise ValueError('每个事件只能包含一个键；组合键请列出各自的 down/up')
            key = keys[0]
            row['_key'] = key
            identity = ('key', key.vk, key.scan, key.extended)
        else:
            if width is None:
                raise ValueError('含鼠标事件的序列必须提供 --width/--height')
            if kind.startswith('mouse_'):
                if not isinstance(source['button'], str) or source['button'] not in BUTTONS:
                    raise ValueError('button 必须为 left/right/middle')
                identity = ('mouse', source['button'])
            for field in FIELDS[kind] - {'button'}:
                value = source[field]
                if type(value) is not int or abs(value) > 100000:
                    raise ValueError('鼠标坐标、位移或滚轮值必须为有限范围整数')
            if kind == 'move' and not (0 <= source['x'] < width and 0 <= source['y'] < height):
                raise ValueError('鼠标坐标不在参考客户区内')
        if identity:
            down = kind.endswith('_down')
            if down == (identity in held):
                raise ValueError('重复按下或释放未按下的输入')
            if down:
                held.add(identity)
            else:
                held.remove(identity)
            row['_identity'] = identity
        plan.append(row)
    if held:
        raise ValueError('序列必须显式配对所有 down/up，不能跨请求保持按下')
    return plan


def run_sequence(window, events, width=None, height=None, max_lateness_ms=None):
    plan = validate_events(events, width, height, max_lateness_ms)
    # Resolve scan-code aliases before any input. Mixing representations of the
    # same physical key makes release ownership ambiguous, so reject that plan.
    virtual, identities = set(), {}
    for row in plan:
        if '_key' not in row:
            continue
        key = row['_key']
        vk = key.vk or window.user.MapVirtualKeyW(key.scan | (0xE000 if key.extended else 0), 3)
        if not vk:
            raise ValueError('无法解析扫描码对应的虚拟键')
        resolved = (vk, key.extended)
        if resolved in identities and identities[resolved] != row['_identity']:
            raise ValueError('同一键不能混用 VK、扫描码或别名表示')
        identities[resolved] = row['_identity']
        virtual.add(vk)
    window.foreground()
    mouse = any(not r['type'].startswith('key_') for r in plan)
    area = window.client_area() if mouse else None
    if area and (area[0], area[1]) != (width, height):
        raise ValueError('客户区尺寸与参考尺寸不一致，请重新截图')
    for vk in MODIFIERS | virtual | (set(v[0] for v in BUTTONS.values()) if mouse else set()):
        if window.user.GetAsyncKeyState(vk) & 0x8000:
            raise ValueError('目标键、鼠标按钮或修饰键已被按住，请松开后重试')

    def guard(row=None):
        window.check_foreground(validate_identity=False)
        if area:
            aw, ah, origin = window._client_area(require_foreground=False, require_uncovered=False)
            if (aw, ah, origin.x, origin.y) != (area[0], area[1], area[2].x, area[2].y):
                raise ValueError('操作期间窗口位置或尺寸变化')
            if row and row['type'] in ('mouse_down', 'wheel'):
                point = W.POINT()
                if not window.user.GetCursorPos(C.byref(point)):
                    raise ValueError('无法读取鼠标位置')
                if not (origin.x <= point.x < origin.x + aw and origin.y <= point.y < origin.y + ah):
                    raise ValueError('当前鼠标不在游戏客户区内')
                if window.owner(window.user.WindowFromPoint(point)) != window.game['pid']:
                    raise ValueError('当前鼠标位置被其他窗口遮挡')

    def event_for(row, release=False):
        kind = row['type']
        if '_key' in row:
            return keyboard_input(row['_key'], release or kind == 'key_up')
        if kind.startswith('mouse_'):
            flags = BUTTONS[row['button']][2 if release or kind == 'mouse_up' else 1]
            return Input(kind=0, mouse=Mouse(0, 0, 0, flags, 0, 0))
        if kind == 'move':
            left, top = window.user.GetSystemMetrics(76), window.user.GetSystemMetrics(77)
            vw, vh = window.user.GetSystemMetrics(78), window.user.GetSystemMetrics(79)
            if min(vw, vh) <= 1:
                raise ValueError('无效的虚拟桌面尺寸')
            x = round((area[2].x + row['x'] - left) * 65535 / (vw - 1))
            y = round((area[2].y + row['y'] - top) * 65535 / (vh - 1))
            return Input(kind=0, mouse=Mouse(x, y, 0, 0xC001, 0, 0))
        if kind == 'relative':
            return Input(kind=0, mouse=Mouse(row['dx'], row['dy'], 0, 1, 0, 0))
        return Input(kind=0, mouse=Mouse(0, 0, row['delta'] & 0xFFFFFFFF, 0x800, 0, 0))

    # Compilation and focus setup are outside the timeline.
    prepared = [(row, event_for(row), event_for(row, True) if row['type'].endswith('_down') else None)
                for row in plan]
    batches = []
    for index, entry in enumerate(prepared):
        row = entry[0]
        button_or_key = row['type'].endswith(('_down', '_up'))
        if (batches and button_or_key and batches[-1][-1][1][0]['type'].endswith(('_down', '_up'))
                and batches[-1][0][1][0]['at_ms'] == row['at_ms']):
            batches[-1].append((index, entry))
        else:
            # Cursor movement/wheel is a boundary so the next click can check
            # the actual new cursor location before submitting its batch.
            batches.append([(index, entry)])
    sender = InputSender(window.user, trace=True)
    records, cleanup = sender.events, sender.cleanup_events
    started = time.perf_counter_ns()
    state, error, code = 'completed', None, None

    try:
        for batch in batches:
            at = batch[0][1][0]['at_ms']
            deadline = started + at * 1000000
            # Coarse sleeping plus a bounded final spin: no timer-resolution or
            # process-priority changes, no forced spacing between events.
            while True:
                remaining = deadline - time.perf_counter_ns()
                if remaining <= 0:
                    break
                if remaining > 2000000:
                    guard()
                    time.sleep(min(.005, (remaining - 1000000) / 1e9))
            guard(next((row for _, (row, _, _) in batch if row['type'] in ('mouse_down', 'wheel')), None))
            if max_lateness_ms is not None and time.perf_counter_ns() - deadline > max_lateness_ms * 1000000:
                state, code = 'cancelled', 'deadline_missed'
                raise ValueError('事件迟到超过 max_lateness_ms，停止剩余输入')
            entries = []
            for index, (row, event, release) in batch:
                metadata = {k: v for k, v in row.items() if not k.startswith('_')}
                metadata.update(index=index, scheduled_ns=deadline)
                entries.append((event, row.get('_identity'), release, metadata))
            sender.send_batch(entries)
        guard()
    except (Exception, KeyboardInterrupt) as exc:
        error = str(exc) or '输入序列已中断'
        if code is None:
            code, state = 'input_sequence_failed', 'unknown' if records else 'cancelled'
    finally:
        failures = sender.release_all()
        if failures:
            error = (error or '') + '; release: ' + '; '.join(failures)
            code, state = 'release_failed', 'unknown'
    for record in records + cleanup:
        record['actual_ms'] = (record['send_started_ns'] - started) / 1000000.
        record['lateness_ms'] = (None if record['cleanup'] else
                                 (record['send_started_ns'] - record['scheduled_ns']) / 1000000.)
    previous = None
    for record in records:
        record['interval_ms'] = None if previous is None else (record['send_started_ns'] - previous) / 1000000.
        previous = record['send_started_ns']
    return {'ok': state == 'completed', 'state': state, 'code': code, 'error': error,
            'schema_version': 1, 'backend': 'windows-sendinput', 'clock': 'perf_counter_ns',
            'timestamp_semantics': 'sendinput_call_bounds_not_game_receipt',
            'started_ns': started, 'finished_ns': time.perf_counter_ns(),
            'plan': [{k: v for k, v in row.items() if not k.startswith('_')} for row in plan],
            'planned_events': len(plan), 'accepted_events': sum(r.get('accepted') is True for r in records),
            'events': records, 'cleanup_events': cleanup, 'released': not sender.held,
            'effect_verified': False, 'max_lateness_ms': max_lateness_ms,
            'hint': None if state == 'completed' else '可能已有部分输入生效；检查事件记录和游戏状态，不自动重放整段序列'}

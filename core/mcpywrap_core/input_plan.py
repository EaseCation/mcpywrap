# coding: utf-8
"""统一输入注册表与计划编译；纯数据契约，可注入游戏 Python 2。"""
from __future__ import unicode_literals
import json
import math

try:
    text_types = (str, unicode)
    input_integer_types = (int, long)
except NameError:
    text_types = (str,)
    input_integer_types = (int,)

try:
    compile_timeline
except NameError:
    from .timeline import compile_timeline

INPUT_LIMITS = {'steps': 256, 'plan_ms': 120000, 'execution_ms': 125000,
                'plan_bytes': 16384, 'log_bytes': 64*1024, 'history': 64}


class InputPlanError(ValueError):
    def __init__(self, code, message):
        self.code = code
        ValueError.__init__(self, message)


def input_require(condition, code, message):
    if not condition:
        raise InputPlanError(code, message)


def field(kind, minimum=None, maximum=None):
    value = {'type': kind}
    if minimum is not None: value['minimum'] = minimum
    if maximum is not None: value['maximum'] = maximum
    return value


def action(fields, required=(), defaults=None, completion='instant', capability=None, description=''):
    return {'parameters': fields, 'required': list(required), 'defaults': defaults or {},
            'completion': completion, 'capability': capability, 'description': description}


_duration = field('integer', 20, 60000)
_keys = {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 8}
_key = {'type': 'string', 'maxLength': 40}
_expect = {'type': 'object', 'properties': {'selected_slot': field('integer', 1, 9),
    'item': {'type': 'string', 'maxLength': 256},
    'target': {'type': 'object', 'properties': {'type': {'type': 'string', 'enum': ['Block', 'Entity', 'None']},
        'x': field('integer'), 'y': field('integer'), 'z': field('integer'), 'entityId': {'type': 'string', 'maxLength': 128}},
        'additionalProperties': False}}, 'additionalProperties': False}
_node = field('integer', 1, 40000)
_snapshot = {'type': 'string', 'maxLength': 64}
INPUT_ACTIONS = {
    'key': action({'keys': _keys, 'duration_ms': _duration}, ('keys',), {'duration_ms': 80}, 'duration', 'key', '按列表顺序按下组合，实际保持后逆序释放'),
    'key_down': action({'key': _key}, ('key',), capability='key', description='按下单键，由计划持续持有'),
    'key_up': action({'key': _key}, ('key',), capability='key', description='释放本计划持有的单键'),
    'wait': action({'duration_ms': field('integer', 0, 10000)}, ('duration_ms',), completion='duration', description='实际执行到此步骤后等待'),
    'player.move': action({'forward': field('number', -1, 1), 'right': field('number', -1, 1), 'sprint': field('boolean'), 'duration_ms': _duration, 'expect': _expect}, defaults={'forward': 0., 'right': 0., 'sprint': False, 'duration_ms': 500}, completion='operation', capability='move'),
    'player.look': action({'pitch': field('number', -90, 90), 'yaw': field('number'), 'expect': _expect}, ('pitch', 'yaw'), completion='operation', capability='look'),
    'player.look_at': action(dict({k: field('number') for k in ('x', 'y', 'z')}, expect=_expect), ('x', 'y', 'z'), completion='operation', capability='look_at'),
    'player.select_slot': action({'slot': field('integer', 1, 9), 'expect': _expect}, ('slot',), completion='operation', capability='select_slot'),
    'player.jump': action({'expect': _expect}, completion='operation', capability='jump'),
    'player.sneak': action({'duration_ms': _duration, 'expect': _expect}, defaults={'duration_ms': 500}, completion='operation', capability='sneak'),
    'player.attack': action({'expect': _expect}, completion='operation', capability='attack'),
    'player.use_item': action({'mode': {'type': 'string', 'enum': ['auto', 'air', 'block']}, 'duration_ms': _duration, 'expect': _expect}, defaults={'mode': 'auto', 'duration_ms': 200}, completion='operation', capability='use_air_or_block'),
    'player.dig': action({'duration_ms': _duration, 'expect': _expect}, defaults={'duration_ms': 1500}, completion='operation', capability='dig'),
    'player.eat': action({'duration_ms': _duration, 'expect': _expect}, defaults={'duration_ms': 2000}, completion='operation', capability='eat'),
    'player.shoot': action({'duration_ms': _duration, 'expect': _expect}, defaults={'duration_ms': 1200}, completion='operation', capability='shoot'),
    'ui.click': action({'node': _node, 'snapshot': _snapshot, 'keys': _keys, 'duration_ms': _duration}, ('node', 'snapshot'), {'duration_ms': 80}, 'operation', 'click'),
    'ui.slide': action({'node': _node, 'snapshot': _snapshot, 'fraction': field('number', 0, 1), 'duration_ms': _duration}, ('node', 'snapshot', 'fraction'), {'duration_ms': 80}, 'operation', 'slide'),
    'ui.scroll': action({'node': _node, 'snapshot': _snapshot, 'percent': field('integer', 0, 100)}, ('node', 'snapshot', 'percent'), completion='operation', capability='scroll'),
    'ui.set_control_value': action({'node': _node, 'snapshot': _snapshot, 'value': {'type': ['string', 'boolean', 'number']}}, ('node', 'snapshot', 'value'), completion='operation', capability='set_control_value', description='仅赋值控件，不代表键入或提交'),
    'pointer.down': action({'button': {'type': 'string', 'enum': ['left', 'right', 'middle']}}, ('button',), capability='pointer'),
    'pointer.up': action({'button': {'type': 'string', 'enum': ['left', 'right', 'middle']}}, ('button',), capability='pointer'),
    'pointer.move': action({'x': field('integer', 0, 100000), 'y': field('integer', 0, 100000)}, ('x', 'y'), capability='pointer'),
    'pointer.relative': action({'dx': field('integer', -100000, 100000), 'dy': field('integer', -100000, 100000)}, ('dx', 'dy'), capability='pointer'),
    'pointer.wheel': action({'delta': field('integer', -100000, 100000)}, ('delta',), capability='pointer'),
}

# 语义说明随注册表暴露，Agent无需再查旧命令文档来推断坐标/值的单位。
for _action_name, _description in {
    'player.move': 'forward>0向前、right>0向右；范围-1到1表示方向不是速度；sprint仅向前；实际保持后解锁',
    'player.look': '角度单位度；pitch负值向上、正值向下；yaw 0南/+Z、90西/-X、-90东/+X',
    'player.look_at': '看向世界坐标x/y/z；方块中心可用整数坐标加0.5',
    'player.select_slot': '快捷栏槽位为1–9，直接选槽，不依赖数字键绑定',
    'player.jump': '执行一次引擎跳跃，不是SPACE按键边沿',
    'player.sneak': '潜行保持duration_ms后恢复原姿态，不是SHIFT按键边沿',
    'player.attack': '攻击当前准星可达实体一次；执行时重新观察目标，不以挥手证明伤害',
    'player.use_item': 'mode auto依据准星目标选择block或air；实体交互尚不支持；duration_ms只控制对空使用',
    'player.dig': '使用当前工具挖掘准星方块；目标变化、破坏或时限结束后停止并释放',
    'player.eat': '使用当前手持食物；默认2000ms，仍需观察饥饿值和物品消费',
    'player.shoot': '普通弓蓄力后释放；默认1200ms，弩尚不支持，需观察箭数/伤害',
    'ui.click': '点击当前快照的button/toggle/edit；node必须来自该快照；keys仅CTRL/SHIFT/ALT',
    'ui.slide': '点击水平滑轨fraction比例0–1；不是业务数值，不代表通用拖拽',
    'ui.scroll': '滚动当前快照容器到percent百分比0–100；不产生原始滚轮事件',
    'pointer.down': 'Windows当前指针位置按下按钮，计划必须有对应up；需要width/height',
    'pointer.up': '释放本计划持有的鼠标按钮',
    'pointer.move': 'Windows参考客户区像素坐标x/y；需要width/height核验',
    'pointer.relative': 'Windows原始相对位移dx/dy；不是角度，实际视角受输入模式影响',
    'pointer.wheel': 'Windows原始滚轮delta，常用正120向上、负120向下；不是直接选槽',
}.items():
    INPUT_ACTIONS[_action_name]['description'] = _description

INPUT_KEY_ALIASES = {'CONTROL': 'CTRL', 'MENU': 'ALT', 'RETURN': 'ENTER', 'ESCAPE': 'ESC',
    'CAPS_LOCK': 'CAPSLOCK', 'PG_UP': 'PAGEUP', 'PGUP': 'PAGEUP', 'PG_DOWN': 'PAGEDOWN', 'PGDN': 'PAGEDOWN',
    'NUM_LOCK': 'NUMLOCK', 'SCROLL': 'SCROLLLOCK', 'GRAVE': 'BACKTICK', 'APOSTRAPHE': 'QUOTE',
    'INS': 'INSERT', 'DEL': 'DELETE', 'BACK': 'BACKSPACE', 'PRTSC': 'PRINTSCREEN',
    'NUMPAD_ADD': 'ADD', 'NUMPAD_SUBTRACT': 'SUBTRACT', 'NUMPAD_MULTIPLY': 'MULTIPLY',
    'NUMPAD_DIVIDE': 'DIVIDE', 'NUMPAD_DECIMAL': 'DECIMAL', 'PLUS': 'EQUALS'}
GAME_KEY_NAMES = {'CTRL': 'CONTROL', 'SHIFT': 'LSHIFT', 'ALT': 'MENU', 'ENTER': 'RETURN',
    'ESC': 'ESCAPE', 'CAPSLOCK': 'CAPS_LOCK', 'PAGEUP': 'PG_UP', 'PAGEDOWN': 'PG_DOWN',
    'NUMLOCK': 'NUM_LOCK', 'SCROLLLOCK': 'SCROLL', 'BACKTICK': 'GRAVE', 'QUOTE': 'APOSTRAPHE'}


def canonical_key(key):
    input_require(isinstance(key, text_types) and 0 < len(key) <= 40 and '+' not in key,
                  'invalid_key', '键必须是非空单键名称，不在 JSON 单键字段使用 +')
    key = key.strip().upper()
    if key.startswith('KEY_'): key = key[4:]
    input_require(bool(key), 'invalid_key', '键名为空')
    return INPUT_KEY_ALIASES.get(key, key)


def game_key_code(key, enum):
    key = canonical_key(key)
    input_require(key not in ('LSHIFT', 'RSHIFT', 'LCTRL', 'RCTRL', 'LALT', 'RALT', 'NUMPAD_ENTER')
                  and not key.startswith(('VK:', 'SC:', 'E0:')), 'not_supported', '游戏键盘不能保留该设备键的左右/扩展/扫描码语义：'+key)
    code = getattr(enum, 'KEY_'+GAME_KEY_NAMES.get(key, key), None)
    input_require(type(code) in input_integer_types and 0 < code < 256,
                  'not_supported', '当前引擎没有该键：'+key)
    return code


def check_field(value, schema, name):
    kind = schema['type']
    if isinstance(kind, list):
        valid = (isinstance(value, text_types) or type(value) is bool or
                 type(value) in input_integer_types+(float,))
    else:
        valid = {'string': isinstance(value, text_types), 'integer': type(value) in input_integer_types,
                 'number': type(value) in input_integer_types+(float,), 'boolean': type(value) is bool,
                 'array': isinstance(value, list), 'object': isinstance(value, dict)}[kind]
    input_require(valid, 'invalid_plan', name+' 类型不合法')
    if type(value) in input_integer_types+(float,):
        input_require(type(value) is not float or not math.isnan(value) and not math.isinf(value), 'invalid_plan', name+' 必须有限')
        input_require(('minimum' not in schema or value >= schema['minimum']) and
                      ('maximum' not in schema or value <= schema['maximum']), 'invalid_plan', name+' 超出范围')
    if isinstance(value, text_types):
        input_require(len(value) <= schema.get('maxLength', 1024), 'invalid_plan', name+' 太长')
    if 'enum' in schema:
        input_require(value in schema['enum'], 'invalid_plan', name+' 值不支持')
    if kind == 'array':
        input_require(schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 256), 'invalid_plan', name+' 数量不合法')
        for item in value: check_field(item, schema['items'], name)


def input_signature(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(',', ':'))


def normalize_input_plan(plan):
    input_require(isinstance(plan, dict) and set(plan) <= {'schema_version', 'backend', 'steps', 'max_lateness_ms', 'width', 'height'}
                  and {'schema_version', 'steps'} <= set(plan), 'invalid_plan', '计划字段缺失或不支持')
    input_require(type(plan['schema_version']) in input_integer_types and plan['schema_version'] == 1,
                  'invalid_plan', 'schema_version 必须为 1')
    backend = plan.get('backend', 'game')
    input_require(backend in ('game', 'windows-sendinput'), 'not_supported', '未知输入后端')
    maximum = plan.get('max_lateness_ms')
    input_require(maximum is None or type(maximum) in input_integer_types and maximum >= 0,
                  'invalid_plan', 'max_lateness_ms 必须是非负整数或 null')
    steps = plan['steps']
    input_require(isinstance(steps, list) and 1 <= len(steps) <= INPUT_LIMITS['steps'], 'invalid_plan', '计划需要 1–256 个步骤')
    normalized, durations, held = [], [], set()
    for source in steps:
        input_require(isinstance(source, dict) and isinstance(source.get('action'), text_types) and source['action'] in INPUT_ACTIONS,
                      'invalid_plan', '未知输入动作')
        name = source['action']; descriptor = INPUT_ACTIONS[name]
        input_require(set(source) <= set(descriptor['parameters']) | {'action', 'at_ms', 'delay_ms'} and
                      set(descriptor['required']) <= set(source), 'invalid_plan', '动作字段缺失或不支持：'+name)
        step = dict(descriptor['defaults']); step.update(source)
        for key, schema in descriptor['parameters'].items():
            if key in step: check_field(step[key], schema, name+'.'+key)
        if 'keys' in step:
            step['keys'] = [canonical_key(k) for k in step['keys']]
            input_require(len(set(step['keys'])) == len(step['keys']), 'invalid_plan', '组合中键重复')
        if 'key' in step: step['key'] = canonical_key(step['key'])
        if name == 'key':
            input_require(not held.intersection(('key', k) for k in step['keys']), 'invalid_plan', '组合键与本计划已持有的键冲突')
        if name in ('key_down', 'key_up', 'pointer.down', 'pointer.up'):
            identity = ('key', step['key']) if 'key' in step else ('pointer', step['button'])
            down = name.endswith(('down', '_down'))
            input_require(identity not in held if down else identity in held, 'invalid_plan', '重复按下或释放未持有的输入')
            if down: held.add(identity)
            else: held.remove(identity)
        if name.startswith('player.'):
            input_require(backend == 'game', 'not_supported', 'Windows 设备后端不执行玩家语义动作')
            if 'expect' in step: validate_input_expect(step['expect'])
        if name.startswith('ui.'):
            input_require(backend == 'game' and len(steps) == 1, 'invalid_plan', 'UI 节点计划每次一个动作，页面变化后重新观察')
            if 'keys' in step:
                input_require(all(k in ('CTRL', 'SHIFT', 'ALT') for k in step['keys']), 'not_supported', 'UI 点击只支持通用 CTRL/SHIFT/ALT 修饰键')
        if name.startswith('pointer.'):
            input_require(backend == 'windows-sendinput', 'not_supported', '当前游戏后端没有经过验证的原始指针能力')
        if name == 'player.move':
            input_require(bool(step['forward'] or step['right']) and (not step['sprint'] or step['forward'] > 0),
                          'invalid_plan', '移动方向或疾跑条件不合法')
        if backend == 'game' and 'duration_ms' in step and name != 'wait':
            input_require(step['duration_ms'] <= 10000, 'invalid_plan', '游戏持续动作最多 10000ms')
        normalized.append(step)
        durations.append(step.get('duration_ms', 0))
    input_require(not held, 'invalid_plan', '计划结束必须配对全部 down/up')
    try:
        normalized = compile_timeline(normalized, durations, INPUT_LIMITS['plan_ms'])
    except ValueError as exc:
            raise InputPlanError('invalid_plan', str(exc))
    result = {'schema_version': 1, 'backend': backend, 'max_lateness_ms': maximum, 'steps': normalized}
    if 'width' in plan or 'height' in plan:
        for key in ('width', 'height'):
            check_field(plan.get(key), field('integer', 1, 32000000), key)
            result[key] = plan[key]
        input_require(result['width']*result['height'] <= 32000000, 'invalid_plan', '参考客户区过大')
    if any(s['action'].startswith('pointer.') for s in normalized):
        input_require('width' in result and 'height' in result, 'invalid_plan', '原始指针输入需要 width/height')
        for step in normalized:
            if step['action'] == 'pointer.move':
                input_require(step['x'] < result['width'] and step['y'] < result['height'], 'invalid_plan', '指针位置在参考客户区之外')
    serialized = input_signature(result)
    input_require(len(serialized.encode('ascii')) <= INPUT_LIMITS['plan_bytes'], 'plan_too_large', '规范化计划超过 16 KiB')
    # 包括 expect 在内全部克隆，调用者不能在提交后改变计划或幂等签名。
    return json.loads(serialized)


def validate_input_expect(expect):
    input_require(set(expect) <= {'selected_slot', 'item', 'target'}, 'invalid_plan', 'expect 字段不支持')
    if 'selected_slot' in expect: check_field(expect['selected_slot'], field('integer', 1, 9), 'expect.selected_slot')
    if 'item' in expect: check_field(expect['item'], {'type': 'string', 'maxLength': 256}, 'expect.item')
    if 'target' in expect:
        target = expect['target']
        input_require(isinstance(target, dict) and set(target) <= {'type', 'x', 'y', 'z', 'entityId'}, 'invalid_plan', '目标断言不合法')
        for key, value in target.items():
            check_field(value, {'type': 'string', 'enum': ['Block', 'Entity', 'None']} if key == 'type' else
                        field('integer') if key in ('x', 'y', 'z') else {'type': 'string', 'maxLength': 128}, 'expect.target.'+key)


def input_key_plan(keys, duration_ms=80):
    if isinstance(keys, text_types): keys = keys.split('+')
    return normalize_input_plan({'schema_version': 1, 'steps': [{'action': 'key', 'keys': keys, 'duration_ms': duration_ms}]})


def input_action_schema(name):
    descriptor = INPUT_ACTIONS[name]
    return {'type': 'object', 'properties': dict(descriptor['parameters'], action={'const': name},
        at_ms=field('integer', 0, 120000), delay_ms=field('integer', 0, 10000)),
        'required': ['action']+descriptor['required'], 'additionalProperties': False}

# coding: utf-8
"""注入游戏 Python 2 的 UI 控制层；也可在 Python 3 中注入适配器测试。"""
from __future__ import unicode_literals
import json
import math
import time
import uuid

try:
    text_type = unicode
    integer_types = (int, long)
except NameError:
    text_type = str
    integer_types = (int,)

VERSION = 1
VERIFIED_POINTER_BUILDS = ('3.10.0.420447',)
ROLES = {0: 'button', 4: 'edit', 9: 'label', 14: 'scroll', 16: 'slider', 19: 'toggle'}
EVENTS = ('PushScreenEvent', 'PopScreenEvent', 'PopScreenAfterClientEvent',
          'ScreenSizeChangedClientEvent', 'UiInitFinished')


def as_text(value):
    if isinstance(value, text_type):
        return value
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    return text_type(value)


def operation_view(op):
    if op is None:
        return None
    # 直接 Python 调用的返回值也不能暴露内部可变输入状态。
    value = {k: v for k, v in op.items() if k != 'signature' and not k.startswith('_')}
    return json.loads(json.dumps(value, ensure_ascii=True, allow_nan=False))


class UIError(ValueError):
    def __init__(self, code, message):
        self.code = code
        ValueError.__init__(self, message)


def require(condition, code, message):
    if not condition:
        raise UIError(code, message)


def intersection(a, b):
    return (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))


def rect(position, size):
    return (float(position[0]), float(position[1]),
            float(position[0] + size[0]), float(position[1] + size[1]))


def nonempty(box):
    return box[2] > box[0] and box[3] > box[1]


def fingerprint(value):
    # 引擎内置 hashlib 并不完整；比较规范序列化值也避免散列碰撞。
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


class UIController(object):
    """单会话控制器；不调用 Win32，不主动更改前台或系统鼠标。"""
    def __init__(self, api, gui, engine, clock=None):
        self.api, self.gui, self.engine = api, gui, engine
        self.clock = clock or getattr(time, 'monotonic', getattr(time, 'clock', time.time))
        self.generation = 0
        self.observation = None
        self.operations = {}
        self.operation_order = []
        self.active = None
        self.last_action = None
        self.events = None
        self.closed = False

    def capabilities(self):
        pointer = not self.closed and self.engine in VERIFIED_POINTER_BUILDS and callable(
            getattr(self.gui, 'simulate_button_event', None)) and self.events is not None
        return {'ok': True, 'version': VERSION, 'engine': self.engine,
                'backend': 'game-runtime', 'installed': not self.closed,
                'capabilities': {'snapshot': True, 'scroll': True, 'click': pointer,
                                 'slide': pointer, 'set_control_value': True,
                                 'type_text': False, 'drag': False},
                'pointer_backend': 'engine-touch' if pointer else None,
                'lifecycle_guard': self.events is not None,
                'limitations': ['private_engine_api', 'enabled_may_be_unknown',
                                'overlap_not_hit_tested', 'effect_requires_verification']}

    def _changed(self, args=None):
        self.generation += 1
        self.observation = None
        player = getattr(self, 'player', None)
        if player is not None:
            player._changed()

    def _ready(self):
        require(not self.closed, 'not_installed', 'UI 控制层已卸载，请重新 install')
        require(self.active is None, 'busy', '交互尚未释放，请查询 status 或 cancel')
        player = getattr(self, 'player', None)
        require(player is None or player.active is None, 'busy', '玩家动作尚未释放，请查询 player status 或 stop')
        require(player is None or not player.sequence_busy(), 'busy', '连续玩家动作正在执行，请查询 player status 或 stop')

    def _top(self):
        node = self.api.GetTopUINode()
        require(node is not None, 'ui_unavailable', '当前没有可读取的 UI 节点')
        return node, [node.GetScreenName(), self.api.GetTopUI(), self.generation]

    def _scan(self, root):
        node, identity = self._top()
        logical = tuple(self.gui.get_client_ui_screen_size())
        physical = tuple(self.gui.get_client_screen_size())
        require(all(x > 0 and not math.isnan(x) and not math.isinf(x)
                    for x in logical + physical), 'invalid_size', '游戏画布尺寸无效')
        if root is None:
            for candidate in ('/variables_button_mappings_and_controls', '/main'):
                if node.GetChildrenName(candidate) is not None:
                    root = candidate
                    break
        require(isinstance(root, (str, text_type)) and root.startswith('/'),
                'unsupported_root', '无法识别根控件，请通过 root 指定实际 UI 根路径')
        require(node.GetChildrenName(root) is not None, 'unsupported_root', '指定的根控件不存在')
        # 原始坐标来自 UI。根以外的祖先仍参与可见性和裁剪检查。
        viewport = (0., 0., float(logical[0]), float(logical[1]))
        ancestor_clip = viewport
        parent = ''
        for segment in root.strip('/').split('/')[:-1]:
            parent += '/' + segment
            c = node.GetBaseUIControl(parent)
            require(c is not None and c.GetVisible(), 'root_hidden', '根控件的祖先已隐藏')
            if c.GetClipsChildren():
                ancestor_clip = intersection(ancestor_clip, rect(c.GetGlobalPosition(), c.GetSize()))
        stack = [(root, ancestor_clip, None)]
        rows, examined, seen, ambiguous = [], 0, set(), set()
        while stack:
            path, clip, semantic_parent = stack.pop()
            if path in seen:
                # 原版集合模板可能产生多个同名路径。能读，但不能唯一定位动作。
                ambiguous.add(path)
                continue
            seen.add(path)
            examined += 1
            require(examined <= 40000 and path.count('/') <= 100,
                    'tree_limit', 'UI 树过大，请通过 root 缩小查询范围')
            c = node.GetBaseUIControl(path)
            if c is None or not c.GetVisible():
                continue
            kind = self.gui.get_control_def_type(identity[0], path)
            bounds = rect(c.GetGlobalPosition(), c.GetSize())
            require(all(not math.isnan(v) and not math.isinf(v) for v in bounds),
                    'invalid_geometry', '控件位置无效')
            shown = intersection(bounds, clip)
            child_clip = intersection(clip, bounds) if c.GetClipsChildren() or kind == 14 else clip
            next_parent = semantic_parent
            if kind in ROLES and nonempty(bounds):
                row = {'path': path, 'role': ROLES[kind], 'bounds': bounds,
                       'visible_bounds': shown, 'in_view': nonempty(shown),
                       'parent_path': semantic_parent, 'enabled': None}
                if kind == 9:
                    row['text'] = as_text(c.asLabel().GetText() or '')[:512]
                elif kind == 4:
                    row['value'] = as_text(c.asTextEditBox().GetEditText() or '')[:1024]
                elif kind == 16:
                    row['value'] = c.asSlider().GetSliderValue()
                elif kind == 19:
                    row['value'] = c.asSwitchToggle().GetToggleState(toggle_path='')
                elif kind == 14:
                    container = path.rsplit('/scroll_touch/scroll_view', 1)[0]
                    container = container.rsplit('/scroll_mouse/scroll_view', 1)[0]
                    control = node.GetBaseUIControl(container)
                    scroll = control.asScrollView() if control is not None else None
                    if scroll is not None and scroll.GetScrollViewContentPath():
                        row['container'] = container
                        row['value'] = scroll.GetScrollViewPercentValue()
                if kind != 9 or row['text']:
                    rows.append(row)
                    if kind != 9:
                        next_parent = path
            children = node.GetChildrenName(path) or []
            for child in reversed(children):
                require(isinstance(child, (str, text_type)) and '/' not in child,
                        'invalid_tree', 'UI 子节点名称无效')
                stack.append((path.rstrip('/') + '/' + child, child_clip, next_parent))
        # 名称来自当前真实文字，避免把隐藏的 hover/pressed 标签重复输出。
        labels = [r for r in rows if r['role'] == 'label']
        for row in rows:
            row['ambiguous'] = any(row['path'] == p or row['path'].startswith(p + '/') for p in ambiguous)
            if row['role'] == 'label':
                row['name'] = row['text']
                continue
            if row['role'] == 'scroll':
                row['name'] = '/'.join(row.get('container', row['path']).split('/')[-3:])
                continue
            names = [r['text'] for r in labels if r['path'].startswith(row['path'] + '/')]
            if '/option_generic_core/' in row['path']:
                group = row['path'].rsplit('/option_generic_core/', 1)[0] + '/option_generic_core/'
                captions = [r['text'] for r in labels if r['path'].startswith(group)
                            and r['path'].endswith('/option_label')]
                names = captions or names
            unique = []
            for name in names:
                if name not in unique:
                    unique.append(name)
            row['name'] = ' / '.join(unique)[:256] if names else path_name(row['path'])
        # identity 包含当前 tab；生命周期事件另外使“同名界面重新打开”失效。
        signature = fingerprint([identity, root, logical, physical, rows])
        return {'root': root, 'identity': identity, 'rows': rows, 'signature': signature,
                'logical': logical, 'physical': physical, 'examined': examined,
                'ambiguous_paths': len(ambiguous)}

    def snapshot(self, root=None, query=None, include_offscreen=False, limit=80, offset=0, details=False):
        self._ready()
        require(type(limit) is int and 1 <= limit <= 160 and type(offset) is int and offset >= 0,
                'invalid_argument', 'limit 必须是 1–160，offset 必须非负')
        require(query is None or isinstance(query, (str, text_type)), 'invalid_argument', 'query 必须是文本')
        started = self.clock()
        scan = self._scan(root)
        token = uuid.uuid4().hex
        try:
            prepare, render = prepare_ui_outline, render_ui_outline
        except NameError:
            from .runtime_ui_outline import prepare_ui_outline as prepare, render_ui_outline as render
        model = prepare(scan['rows'])
        meaningful = model['rows']
        matched = [r for r in meaningful if (include_offscreen or r['in_view']) and
                   (query is None or query.lower() in (r['name'] + ' ' + r['path'] + ' ' +
                       ' '.join(r['outline_context']) + ' ' + as_text(r.get('value','')) + ' ' + r.get('description','')).lower())]
        selected = matched[offset:offset+limit]
        stored, output = {}, []
        budget = 0
        for index, row in enumerate(selected, offset+1):
            record = {'id': index, 'role': row['role'], 'name': row['name'],
                      'in_view': row['in_view'], 'enabled': row['enabled'],
                      'ambiguous': row['ambiguous'], 'actions': [],
                      'parent': row['outline_parent'], 'depth': row['outline_depth']}
            if row.get('outline_group'):
                record['group'] = row['outline_group']
                record['presentation'] = 'region' if row['role']=='scroll' else 'heading'
            elif row.get('_page_title') or row.get('_region_title'):
                record['presentation'] = 'title'
            if row.get('description'):
                record['description'] = row['description']
            if row.get('readonly_field'):
                record['readonly'] = True
            if 'value' in row:
                record['value'] = row['value']
            if row['role'] in ('button', 'toggle', 'edit') and row['in_view'] and self.capabilities()['capabilities']['click']:
                record['actions'].append('click')
            if (row['role'] == 'slider' and row['in_view'] and
                    row['bounds'][2]-row['bounds'][0] >= row['bounds'][3]-row['bounds'][1] and
                    self.capabilities()['capabilities']['slide']):
                record['actions'].append('slide')
            if row['role'] == 'scroll' and 'container' in row:
                record['actions'].append('scroll')
            if row['role'] in ('edit', 'slider', 'toggle'):
                record['actions'].append('set_control_value')
            if row['ambiguous']:
                record['actions'] = []
            if details:
                record.update(path=row['path'], bounds=row['bounds'], visible_bounds=row['visible_bounds'])
                if row.get('related_paths'):
                    record['related_paths'] = row['related_paths']
            cost = len(json.dumps(record, ensure_ascii=True))
            if budget + cost > 75000:
                break
            budget += cost
            stored[index] = row
            output.append(record)
        tree, groups = render(model, output, stored)
        # 把祖先分组也计入返回上限；移除末尾节点后同时重建分页上下文。
        while output and len(json.dumps({'nodes':output,'tree':tree,'groups':groups},ensure_ascii=True)) > 75000:
            stored.pop(output.pop()['id'])
            tree, groups = render(model, output, stored)
        require(bool(output) or not selected, 'output_limit', '单个节点及分组超过输出上限，请关闭 details 或缩小查询范围')
        self.observation = dict(scan, token=token, created=self.clock(), selected=stored)
        next_offset = offset + len(output)
        return {'ok': True, 'snapshot': token, 'screen': scan['identity'][0],
                'top': scan['identity'][1], 'generation': self.generation, 'root': scan['root'],
                'tree': tree, 'tree_format':'semantic-v1', 'title':model['title'], 'groups':groups,
                'nodes': output, 'matched': len(matched),
                'examined': scan['examined'], 'offset': offset,
                'ambiguous_paths': scan['ambiguous_paths'],
                'truncated': next_offset < len(matched),
                'next_offset': next_offset if next_offset < len(matched) else None,
                'elapsed_ms': int((self.clock()-started)*1000),
                'last_action': operation_view(self.last_action)}

    def _target(self, node, snapshot, roles):
        self._ready()
        old = self.observation
        require(old is not None and snapshot == old['token'], 'stale_snapshot', '快照已失效，请重新 snapshot')
        require(self.clock()-old['created'] <= 120, 'stale_snapshot', '快照超过 120 秒，请重新观察')
        require(type(node) is int and node in old['selected'], 'unknown_node', '编号不属于此快照的已返回节点')
        row = old['selected'][node]
        require(not row['ambiguous'], 'ambiguous_node', '引擎返回同名控件路径，无法唯一定位；未执行动作')
        require(row['role'] in roles, 'unsupported_action', '该控件不支持此操作')
        current = self._scan(old['root'])
        if current['signature'] != old['signature']:
            self.observation = None
            raise UIError('stale_snapshot', '界面、值或布局已变化；未发送输入，请重新观察')
        return row, current

    def _operation(self, request_id, signature):
        if request_id is None:
            request_id = uuid.uuid4().hex
        require(isinstance(request_id, (str, text_type)) and len(request_id) == 32 and
                all(c in '0123456789abcdef' for c in request_id), 'invalid_argument', 'request_id 必须是 32 位小写十六进制')
        previous = self.operations.get(request_id)
        if previous:
            require(previous['signature'] == signature, 'request_conflict', 'request_id 已用于其他动作')
            return previous, True
        return {'id': request_id, 'signature': signature}, False

    def _save_operation(self, op):
        self.operations[op['id']] = op
        self.operation_order.append(op['id'])
        if len(self.operation_order) > 64:
            self.operations.pop(self.operation_order.pop(0), None)
        self.last_action = op
        self.observation = None

    def _pointer(self, node, snapshot, fraction, request_id, action):
        require(self.capabilities()['capabilities']['click'], 'unsupported_engine',
                '当前引擎或生命周期适配未通过内部触控验证；不回退到桌面输入')
        op, repeated = self._operation(request_id, [action, node, snapshot, fraction])
        if repeated:
            return dict(operation_view(op), ok=op.get('state') not in ('failed', 'unknown'))
        row, scan = self._target(node, snapshot, ('slider',) if action == 'slide' else ('button', 'toggle', 'edit'))
        require(row['in_view'], 'offscreen', '节点不在当前可视区域，请先滚动并刷新')
        require(row['enabled'] is not False, 'disabled', '控件已禁用')
        box, visible = row['bounds'], row['visible_bounds']
        require(action != 'slide' or box[2]-box[0] >= box[3]-box[1],
                'unsupported_control', '当前仅验证了水平滑轨，不对竖直滑轨猜测方向')
        x = box[0] + (box[2]-box[0]) * fraction
        y = (box[1]+box[3])/2
        if action == 'click':
            x, y = (visible[0]+visible[2])/2, (visible[1]+visible[3])/2
        require(visible[0] <= x < visible[2] and visible[1] <= y < visible[3],
                'clipped_target', '目标位置已被裁剪，请先滚动至完整可见')
        # API 接收客户端像素坐标，绝不传给操作系统鼠标。
        px = int(x * scan['physical'][0] / scan['logical'][0])
        py = int(y * scan['physical'][1] / scan['logical'][1])
        op.update(state='pending', action=action, backend='engine-touch', sent=False,
                  released=False, effect_verified=False, point=[px, py])
        self._save_operation(op)
        self.active = op
        try:
            # 先注册自动抬起；调用方断连也不依赖下一条请求释放。
            game = self.api.GetEngineCompFactory().CreateGame(self.api.GetLevelId())
            timer = game.AddTimer(.08, lambda: self._release(op))
            require(timer is not None, 'timer_unavailable', '无法安排自动释放，未发送输入')
            op['sent'] = bool(self.gui.simulate_button_event(px, py, 0))
            if not op['sent']:
                raise UIError('input_rejected', '引擎拒绝按下事件')
        except Exception as exc:
            self._release(op, 'failed')
            op['error'] = as_text(exc)
            op['code'] = getattr(exc, 'code', 'input_failed')
        return dict(operation_view(op), ok=op['state'] not in ('failed', 'unknown'))

    def _release(self, op, state='completed'):
        if op.get('released'):
            return
        if state != 'completed':
            op['_release_state'] = state
        # 先标记，防止抬起过程中同步发出 Push/Pop 事件导致重入。
        op['released'] = True
        try:
            require(bool(self.gui.simulate_button_event(op['point'][0], op['point'][1], 1)),
                    'release_failed', '引擎拒绝抬起事件')
            op['state'] = op.get('_release_state', state)
        except Exception as exc:
            op.update(state='unknown', released=False, error=as_text(exc), code='release_failed')
        finally:
            if self.active is op and op['released']:
                self.active = None
            self.observation = None

    def click(self, node, snapshot, request_id=None):
        return self._pointer(node, snapshot, .5, request_id, 'click')

    def slide(self, node, fraction, snapshot, request_id=None):
        require(type(fraction) in (int, float) and 0 <= fraction <= 1,
                'invalid_argument', 'fraction 必须在 0–1；这是滑轨比例，不是业务数值')
        # 两端向内取样，避免落到相邻控件；最终值以刷新结果为准。
        return self._pointer(node, snapshot, max(.001, min(.999, float(fraction))), request_id, 'slide')

    def scroll(self, node, percent, snapshot, request_id=None):
        require(type(percent) is int and 0 <= percent <= 100, 'invalid_argument', 'percent 必须是 0–100 整数')
        op, repeated = self._operation(request_id, ['scroll', node, snapshot, percent])
        if repeated:
            return dict(operation_view(op), ok=op.get('state') == 'completed')
        row, scan = self._target(node, snapshot, ('scroll',))
        require('container' in row, 'unsupported_control', '滚动容器结构不受支持')
        control = self.api.GetTopUINode().GetBaseUIControl(row['container']).asScrollView()
        require(control is not None and control.GetScrollViewContentPath(), 'stale_snapshot', '滚动容器已变化')
        op.update(state='pending', action='scroll', backend='modsdk', effect_verified=False,
                  before=control.GetScrollViewPercentValue(), requested=percent)
        self._save_operation(op)
        try:
            control.SetScrollViewPercentValue(percent)
            op.update(state='completed', after=control.GetScrollViewPercentValue(),
                      position=control.GetScrollViewPos(), verification='control_readback')
        except Exception as exc:
            op.update(state='unknown', error=as_text(exc))
        return dict(operation_view(op), ok=op['state'] == 'completed')

    def set_control_value(self, node, value, snapshot, request_id=None):
        op, repeated = self._operation(request_id, ['set_control_value', node, snapshot, value])
        if repeated:
            return dict(operation_view(op), ok=op.get('state') == 'completed')
        row, scan = self._target(node, snapshot, ('edit', 'slider', 'toggle'))
        if row['role'] == 'edit':
            require(isinstance(value, (str, text_type)) and len(value) <= 1024,
                    'invalid_argument', '文本必须不超过 1024 字符')
        elif row['role'] == 'toggle':
            require(type(value) is bool, 'invalid_argument', '开关值必须是布尔值')
        else:
            require(type(value) in (int, float) and not math.isnan(value) and not math.isinf(value),
                    'invalid_argument', '滑块值必须是有限数值')
        c = self.api.GetTopUINode().GetBaseUIControl(row['path'])
        op.update(state='pending', action='set_control_value', backend='modsdk',
                  before=row.get('value'), requested=value, effect_verified=False,
                  verification='control_only', hint='只修改控件状态，不保证触发业务回调；请刷新核对')
        self._save_operation(op)
        try:
            if row['role'] == 'edit':
                c.asTextEditBox().SetEditText(value)
                op['after'] = as_text(c.asTextEditBox().GetEditText())
            elif row['role'] == 'toggle':
                c.asSwitchToggle().SetToggleState(value, toggle_path='')
                op['after'] = c.asSwitchToggle().GetToggleState(toggle_path='')
            else:
                c.asSlider().SetSliderValue(value)
                op['after'] = c.asSlider().GetSliderValue()
            op['state'] = 'completed'
        except Exception as exc:
            op.update(state='unknown', error=as_text(exc))
        return dict(operation_view(op), ok=op['state'] == 'completed')

    def status(self, operation=None):
        if operation is None:
            return dict(self.capabilities(), active=operation_view(self.active),
                        last_action=operation_view(self.last_action))
        require(operation in self.operations, 'operation_not_found', '动作记录不存在或已淘汰；不要自动重发')
        op = self.operations[operation]
        return dict(operation_view(op), ok=op['state'] not in ('failed', 'unknown'))

    def cancel(self, operation):
        require(operation in self.operations, 'operation_not_found', '动作记录不存在')
        op = self.operations[operation]
        if self.active is op:
            self._release(op, 'cancelled')
        return self.status(operation)

    def close(self):
        player = getattr(self, 'player', None)
        if player is not None:
            player.close()
        if self.active:
            self._release(self.active, 'cancelled')
        require(self.active is None, 'release_failed', '输入释放结果未知，保留控制层以便 cancel 重试')
        if self.events is not None:
            self.events.bind(None)
        self.closed = True
        self.observation = None
        return {'ok': True, 'installed': False, 'last_action': operation_view(self.last_action)}

    def dispatch(self, action, **parameters):
        try:
            require(action in ('snapshot', 'click', 'slide', 'scroll', 'set_control_value',
                               'status', 'cancel', 'close'), 'unknown_action', '未知 UI 动作')
            return getattr(self, action)(**parameters)
        except (UIError, TypeError, ValueError) as exc:
            return {'ok': False, 'code': getattr(exc, 'code', 'invalid_argument'),
                    'error': as_text(exc), 'refresh_required': True}


def path_name(path):
    return path.rsplit('/', 1)[-1]


def attach_events(controller, module_name):
    """复用单个注册系统，升级和卸载都显式解绑监听。"""
    import sys
    api = controller.api
    base = api.GetClientSystemCls()

    class RuntimeEvents(base):
        def __init__(self, namespace, system):
            base.__init__(self, namespace, system)
            self.owner = None

        def changed(self, args):
            if self.owner is not None:
                self.owner._changed(args)

        def bind(self, owner):
            ns, system = api.GetEngineNamespace(), api.GetEngineSystemName()
            if self.owner is not None:
                for event in EVENTS:
                    self.UnListenForEvent(ns, system, event, self, self.changed)
            self.owner = owner
            if owner is not None:
                for event in EVENTS:
                    self.ListenForEvent(ns, system, event, self, self.changed)

    setattr(sys.modules[module_name], 'RuntimeEvents', RuntimeEvents)
    events = api.GetSystem('mcpywrap_runtime', 'ui_events')
    if events is None:
        events = api.RegisterSystem('mcpywrap_runtime', 'ui_events', module_name + '.RuntimeEvents')
    require(events is not None and hasattr(events, 'bind'), 'lifecycle_unavailable', '无法建立 UI 生命周期监听')
    events.bind(controller)
    controller.events = events

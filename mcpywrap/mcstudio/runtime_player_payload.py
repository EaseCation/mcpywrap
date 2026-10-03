# coding: utf-8
"""与 UI 源码一起注入的客户端玩家控制层；不执行服务端作弊操作。"""
import math
import uuid

try:
    UIController
except NameError:
    from .runtime_ui_payload import UIController, UIError, require, as_text, operation_view


PLAYER_BUILDS = ('3.10.0.420447',)
HUD_TOPS = ('hud_screen', 'ui://./hbui/gameplay.html')


def finite(value):
    return type(value) in (int, float) and not math.isnan(value) and not math.isinf(value)


class PlayerController(UIController):
    def __init__(self, ui, native=None):
        self.ui, self.api, self.gui, self.native = ui, ui.api, ui.gui, native
        self.engine, self.clock = ui.engine, ui.clock
        self.closed = False
        self.active = self.last_action = self.observation = None
        self.operations, self.operation_order = {}, []
        self.sequence_job = None
        self._in_sequence = False

    def capabilities(self):
        known = not self.closed and not self.ui.closed and self.engine in PLAYER_BUILDS
        def has(*names):
            return known and all(callable(getattr(self.native, n, None)) for n in names)
        return {'ok': True, 'installed': not self.closed and not self.ui.closed,
                'engine': self.engine, 'backend': 'game-client', 'version': 1,
                'capabilities': {'snapshot': True, 'look': known, 'look_at': known,
                    'move': known, 'jump': known,
                    'key': known and callable(getattr(self.gui, 'simulate_keyboard_event', None)),
                    'sneak': known and callable(getattr(self.api,'ChangeSneakState',None)), 'select_slot': has('local_player_select_slot'),
                    'attack': has('local_player_attack_entity'),
                    'dig': has('local_player_start_destroy_block', 'local_player_continue_destroy_block', 'local_player_stop_destroy_block'),
                    'use_block': has('local_player_build_block'),
                    'use_air': has('local_player_use_item', 'local_player_release_using_item', 'local_player_is_using_item'),
                    'eat': has('local_player_use_item', 'local_player_release_using_item', 'local_player_is_using_item'),
                    'shoot': has('local_player_use_item', 'local_player_release_using_item', 'local_player_is_using_item'),
                    'sequence': known,
                    'interact_entity': False},
                'limits': {'duration_ms': [20, 10000], 'slot': [1, 9], 'snapshot_seconds': 30,
                           'sequence_steps':32, 'sequence_ms':120000},
                'limitations': ['private_client_api', 'effect_requires_verification', 'hud_only']}

    def _alive(self):
        require(not self.closed and not self.ui.closed, 'not_installed', '请重新执行 runtime install')
        pid = self.api.GetLocalPlayerId()
        require(pid is not None and as_text(pid) not in ('', '-1'), 'player_unavailable', '本地玩家尚未就绪')
        return pid

    def _ready(self, capability):
        pid = self._alive()
        require(self.active is None and self.ui.active is None, 'busy', '上一动作尚未释放，请查询 status 或 stop')
        require(not self.sequence_busy() or self._in_sequence, 'busy', '连续动作正在执行，请查询 status 或 stop')
        require(self._hud(), 'menu_open', '请先关闭菜单并重新观察玩家状态')
        require(self.capabilities()['capabilities'].get(capability, False),
                'unsupported_capability', '当前引擎没有已验证的玩家能力：' + capability)
        return pid

    def _hud(self):
        node=self.api.GetTopUINode()
        return self.api.GetTopUI() in HUD_TOPS and node is not None and node.GetScreenName()=='hud.hud_screen'

    def _factory(self):
        return self.api.GetEngineCompFactory()

    @staticmethod
    def _item(item):
        if not item:
            return None
        return {'name': item.get('newItemName', item.get('itemName')),
                'aux': item.get('newAuxValue', item.get('auxValue', 0)), 'count': item.get('count', 0)}

    def _read(self):
        pid = self._alive()
        f = self._factory()
        player, item = f.CreatePlayer(pid), f.CreateItem(pid)
        camera = f.CreateCamera(self.api.GetLevelId())
        # 第三人称相机在身后，交互距离/瞄准必须以玩家视点为准。
        eye, rotation = f.CreatePos(pid).GetPos(), f.CreateRot(pid).GetRot()
        target = dict(camera.PickFacing() or {'type': 'None'})
        reach = player.GetPickRange()
        if all(k in target for k in ('hitPosX', 'hitPosY', 'hitPosZ')):
            target['distance'] = math.sqrt(sum((target[k]-eye[i])**2 for i, k in enumerate(('hitPosX', 'hitPosY', 'hitPosZ'))))
        else:
            target['distance'] = None
        target['in_reach'] = (finite(reach) and reach > 0 and target['distance'] is not None
                              and target['distance'] <= reach + .05)
        if target.get('type') == 'Block':
            target['block'] = f.CreateBlockInfo(self.api.GetLevelId()).GetBlock((target['x'], target['y'], target['z']))
        elif target.get('type') == 'Entity':
            try:
                target['health'] = f.CreateAttr(target['entityId']).GetAttrValue(self.api.GetMinecraftEnum().AttrType.HEALTH)
            except Exception:
                target['health'] = None
        hotbar = []
        for slot in range(9):
            hotbar.append({'slot': slot+1, 'item': self._item(item.GetPlayerItem(self.api.GetMinecraftEnum().ItemPosType.INVENTORY, slot))})
        carried = self._item(item.GetCarriedItem())
        if carried:
            info = item.GetItemBasicInfo(carried['name'],carried['aux']) or {}
            carried['edible'] = info.get('itemType')=='food' or info.get('foodNutrition',0)>0 or 'minecraft:is_food' in info.get('tags',[])
        inventory = item.GetPlayerAllItems(self.api.GetMinecraftEnum().ItemPosType.INVENTORY) or []
        arrows = sum(it.get('count',0) for it in inventory if it and it.get('newItemName',it.get('itemName')) in ('minecraft:arrow','minecraft:tipped_arrow'))
        return {'player_id': pid, 'dimension': f.CreateGame(self.api.GetLevelId()).GetCurrentDimension(),
                'screen': self.api.GetTopUI(), 'position': f.CreatePos(pid).GetFootPos(), 'eye': eye, 'camera':camera.GetPosition(),
                'rotation': {'pitch': rotation[0], 'yaw': rotation[1]},
                'selected_slot': item.GetSlotId()+1, 'carried': carried, 'hunger':player.GetPlayerHunger(), 'arrows':arrows,
                'hotbar': hotbar, 'target': target, 'reach': reach,
                'input_vector': f.CreateActorMotion(pid).GetInputVector(),
                'sneaking': bool(player.isSneaking()), 'sprinting': bool(player.isSprinting())}

    def snapshot(self):
        state = self._read()
        token = uuid.uuid4().hex
        self.observation = {'token': token, 'created': self.clock(), 'generation': self.ui.generation, 'state': state}
        return dict(state, ok=True, snapshot=token, active=operation_view(self.active), last_action=operation_view(self.last_action),
                    sequence=self._summary(self.sequence_job))

    @staticmethod
    def _target_id(target):
        if target.get('type') == 'Entity':
            return ('Entity', target.get('entityId'))
        if target.get('type') == 'Block':
            return ('Block', target.get('x'), target.get('y'), target.get('z'), target.get('face'), target.get('block'))
        return ('None',)

    def _observed(self, snapshot, in_reach=True):
        old = self.observation
        require(old is not None and old['token'] == snapshot and self.clock()-old['created'] <= 30
                and old['generation'] == self.ui.generation, 'stale_snapshot', '玩家快照已失效，请重新 snapshot')
        current, previous = self._read(), old['state']
        stable = all(current[k] == previous[k] for k in ('player_id', 'dimension', 'selected_slot', 'carried'))
        stable = stable and self._target_id(current['target']) == self._target_id(previous['target'])
        require(stable, 'stale_snapshot', '瞄准目标、手持物品或槽位已变化；未执行动作')
        if in_reach and current['target'].get('type') != 'None':
            require(current['target']['in_reach'], 'out_of_reach', '目标超出当前交互距离，请先移动并重新观察')
        return current

    def _save(self, op):
        UIController._save_operation(self, op)
        self.ui.observation = None

    def _prepare(self, action, args, request_id, capability):
        op, repeated = self._operation(request_id, [action, args])
        if repeated:
            return op, True
        self._ready(capability)
        return op, False

    def _view(self, op):
        return dict(operation_view(op), ok=op.get('state') not in ('failed', 'unknown'))

    def _instant(self, op, action, function, before=None):
        op.update(action=action, state='pending', backend='game-client', effect_verified=False, before=before or self._read())
        self._save(op)
        try:
            op['accepted'] = function() is not False
            op['state'] = 'completed' if op['accepted'] else 'failed'
            if not op['accepted']:op.update(code='input_rejected',error='引擎拒绝了该动作；请重新观察目标与物品')
            op['after'] = self._read()
        except Exception as exc:
            op.update(state='unknown', error=as_text(exc))
        return self._view(op)

    def _lease(self, op, action, duration_ms, before=None):
        require(type(duration_ms) is int and 20 <= duration_ms <= 10000,
                'invalid_argument', 'duration_ms/hold_ms 必须是 20–10000 整数')
        op.update(action=action, state='pending', backend='game-client', released=False, effect_verified=False,
                  before=before or self._read(), duration_ms=duration_ms, _release=[])
        self._save(op)
        self.active = op
        try:
            timer=self._factory().CreateGame(self.api.GetLevelId()).AddTimer(duration_ms/1000., lambda: self._release(op))
            require(timer is not None,'timer_unavailable','无法安排自动释放，未发送输入')
        except Exception as exc:
            op['error'] = as_text(exc)
            self._release(op, 'failed')
        return op['state'] == 'pending'

    def _release(self, op, state='completed'):
        if op.get('released') or op.get('_releasing'):
            return
        if state != 'completed':
            op['_terminal'] = state
        op['_releasing'] = True
        failures = []
        for kind, value in reversed(op.get('_release', [])):
            try:
                if kind == 'key':
                    require(bool(self.gui.simulate_keyboard_event(value, False)), 'release_failed', '按键释放失败')
                elif kind == 'move':
                    require(self._factory().CreateActorMotion(value).UnlockInputVector() is not False, 'release_failed', '移动解锁失败')
                elif kind == 'sprint':
                    self._factory().CreateActorMotion(value).EndSprinting()
                elif kind == 'sneak':
                    if self._factory().CreatePlayer(self.api.GetLocalPlayerId()).isSneaking()!=value:
                        self.api.ChangeSneakState()
                elif kind == 'use':
                    self.native.local_player_release_using_item()
                elif kind == 'dig':
                    self.native.local_player_stop_destroy_block(*value)
            except Exception as exc:
                failures.append((kind, value))
                op['error'] = as_text(exc)
        op['_release'] = list(reversed(failures))
        op['_releasing'] = False
        op['released'] = not failures
        op['state'] = 'unknown' if failures else op.get('_terminal', state)
        if not failures:
            if self.active is op:
                self.active = None
            try:
                op['after'] = self._read()
            except Exception as exc:
                op['observation_error'] = as_text(exc)
        self.observation = self.ui.observation = None

    def _failed(self, op, exc):
        op['error'] = as_text(exc)
        op['code'] = getattr(exc,'code','action_failed')
        self._release(op, 'failed')
        return self._view(op)

    def _changed(self):
        self.observation = None
        if self.active:
            self.active['end_reason'] = 'ui_changed'
            self._release(self.active, 'completed' if self.active['action']=='key' else 'cancelled')
        if self.sequence_busy():
            self.sequence_job.update(state='cancelled',end_reason='ui_changed')

    def look(self, pitch, yaw, request_id=None):
        require(finite(pitch) and -90 <= pitch <= 90 and finite(yaw), 'invalid_argument', 'pitch 必须在 -90–90，yaw 必须为有限角度')
        op, repeated = self._prepare('look', [pitch, yaw], request_id, 'look')
        if repeated: return self._view(op)
        rotation = (float(pitch), (float(yaw)+180.) % 360.-180.)
        op['expected_rotation']={'pitch':rotation[0],'yaw':rotation[1]}
        return self._instant(op, 'look', lambda: self._factory().CreateRot(self.api.GetLocalPlayerId()).SetRot(rotation))

    def look_at(self, x, y, z, request_id=None):
        require(all(finite(v) for v in (x, y, z)), 'invalid_argument', '目标坐标必须是有限数值')
        op, repeated = self._prepare('look_at', [x,y,z], request_id, 'look_at')
        if repeated: return self._view(op)
        before = self._read()
        dx, dy, dz = [v-before['eye'][i] for i,v in enumerate((x,y,z))]
        require(dx*dx+dy*dy+dz*dz > .000001, 'invalid_argument', '目标不能与当前相机位置重合')
        rotation = (-math.degrees(math.atan2(dy, math.sqrt(dx*dx+dz*dz))), math.degrees(math.atan2(-dx, dz)))
        op['expected_rotation']={'pitch':rotation[0],'yaw':rotation[1]}
        return self._instant(op, 'look_at', lambda: self._factory().CreateRot(before['player_id']).SetRot(rotation), before)

    def select_slot(self, slot, request_id=None):
        require(type(slot) is int and 1 <= slot <= 9, 'invalid_argument', '快捷栏槽位为 1–9')
        op, repeated = self._prepare('select_slot', [slot], request_id, 'select_slot')
        if repeated: return self._view(op)
        return self._instant(op, 'select_slot', lambda: self.native.local_player_select_slot(slot-1))

    def jump(self, request_id=None):
        op, repeated = self._prepare('jump', [], request_id, 'jump')
        if repeated: return self._view(op)
        return self._instant(op, 'jump', self.api.SimulateJump)

    def move(self, forward=0., right=0., duration_ms=500, sprint=False, request_id=None):
        require(finite(forward) and finite(right) and -1 <= forward <= 1 and -1 <= right <= 1
                and (forward or right), 'invalid_argument', 'forward/right 必须在 -1–1，且不能同时为零')
        require(type(sprint) is bool and (not sprint or forward > 0), 'invalid_argument', '疾跑只能配合向前移动')
        op, repeated = self._prepare('move', [forward,right,duration_ms,sprint], request_id, 'move')
        if repeated: return self._view(op)
        pid = self.api.GetLocalPlayerId()
        before = self._read()
        require(not any(abs(v) > .01 for v in before['input_vector']), 'input_busy', '已有其他移动输入，未接管它')
        if not self._lease(op, 'move', duration_ms, before): return self._view(op)
        try:
            motion = self._factory().CreateActorMotion(pid)
            op['_release'].append(('move', pid))
            require(motion.LockInputVector((-float(right),float(forward))) is not False, 'input_rejected', '引擎拒绝移动')
            if sprint and not before['sprinting']:
                op['_release'].append(('sprint', pid))
                motion.BeginSprinting()
        except Exception as exc: return self._failed(op, exc)
        return self._view(op)

    def sneak(self, duration_ms=500, request_id=None):
        op, repeated = self._prepare('sneak', [duration_ms], request_id, 'sneak')
        if repeated: return self._view(op)
        before = self._read()
        if not self._lease(op, 'sneak', duration_ms, before): return self._view(op)
        try:
            if not before['sneaking']:
                op['_release'].append(('sneak', False))
                self.api.ChangeSneakState()
        except Exception as exc: return self._failed(op, exc)
        return self._view(op)

    def _key_codes(self,keys):
        require(isinstance(keys, (str, type(u''))) and len(keys) <= 100, 'invalid_argument', 'keys 必须是键名或组合键')
        aliases = {'CTRL':'CONTROL','SHIFT':'LSHIFT','ALT':'MENU','ENTER':'RETURN','ESC':'ESCAPE'}
        enum = self.api.GetMinecraftEnum().KeyBoardType
        codes = []
        for token in keys.upper().split('+'):
            token = token.strip()
            if token.startswith('KEY_'): token=token[4:]
            code = getattr(enum, 'KEY_'+aliases.get(token,token), None)
            require(type(code) is int and 0 < code < 256 and code not in codes, 'invalid_key', '未知或重复键名；鼠标动作请使用 attack/use_item')
            codes.append(code)
        require(1 <= len(codes) <= 8, 'invalid_key', '一次最多 8 个键')
        codes.sort(key=lambda value: value not in (16,17,18))
        return codes

    def key(self, keys, hold_ms=80, request_id=None):
        codes=self._key_codes(keys)
        op, repeated = self._prepare('key', [keys,hold_ms], request_id, 'key')
        if repeated: return self._view(op)
        if not self._lease(op, 'key', hold_ms): return self._view(op)
        try:
            for code in codes:
                if op['state'] != 'pending': break
                op['_release'].append(('key', code))
                require(bool(self.gui.simulate_keyboard_event(code, True)), 'input_rejected', '引擎拒绝按键')
        except Exception as exc: return self._failed(op, exc)
        return self._view(op)

    def attack(self, snapshot, request_id=None):
        op, repeated = self._prepare('attack', [snapshot], request_id, 'attack')
        if repeated: return self._view(op)
        before = self._observed(snapshot)
        target = before['target']
        require(target.get('type') == 'Entity', 'wrong_target', 'attack 需要瞄准实体；方块请用 dig')
        return self._instant(op, 'attack', lambda: self.native.local_player_attack_entity(target['entityId']), before)

    def use_item(self, snapshot, mode='auto', hold_ms=200, request_id=None):
        require(mode in ('auto','air','block'), 'invalid_argument', 'mode 为 auto/air/block')
        capability = 'use_air' if mode=='air' else 'use_block' if mode=='block' else None
        op, repeated = self._operation(request_id, ['use_item',[snapshot,mode,hold_ms]])
        if repeated: return self._view(op)
        before = self._observed(snapshot, in_reach=mode!='air')
        target = before['target']
        if mode=='auto': mode='air' if target.get('type')=='None' else 'block'
        self._ready(capability or ('use_air' if mode=='air' else 'use_block'))
        require(before['carried'] is not None or mode=='block', 'empty_hand', '当前没有手持物品')
        if mode=='block':
            require(target.get('type')=='Block', 'unsupported_target', '实体交互尚未适配；对空使用请显式 mode=air')
            args = [target[k] for k in ('x','y','z','face')]
            return self._instant(op, 'use_item', lambda: self.native.local_player_build_block(*args), before)
        if not self._lease(op, 'use_item', hold_ms, before): return self._view(op)
        try:
            op['_release'].append(('use', None))
            self._begin_use(op)
        except Exception as exc: return self._failed(op, exc)
        return self._view(op)

    def _consume(self, action, snapshot, hold_ms, request_id):
        op, repeated = self._prepare(action,[snapshot,hold_ms],request_id,action)
        if repeated: return self._view(op)
        before=self._observed(snapshot,in_reach=False)
        item=before['carried']
        require(item is not None,'empty_hand','当前没有手持物品')
        if action=='eat':
            require(item.get('edible',False),'wrong_item','手持物品不是引擎识别的食物')
        else:
            require(item['name']=='minecraft:bow','unsupported_item','shoot 当前支持普通弓；弩的装填/发射流程尚未适配')
        if not self._lease(op,action,hold_ms,before): return self._view(op)
        try:
            op['_release'].append(('use',None))
            self._begin_use(op)
        except Exception as exc: return self._failed(op,exc)
        return self._view(op)

    def _begin_use(self,op):
        # 原生 useItem 对食物/弓可返回 False，但已进入使用状态；不能立刻松开。
        accepted=self.native.local_player_use_item()
        using=bool(self.native.local_player_is_using_item())
        op.update(native_return=accepted,using_item=using)
        require(accepted is not False or using,'input_rejected','引擎没有接受或开始使用手持物品')

    def eat(self,snapshot,hold_ms=2000,request_id=None):
        return self._consume('eat',snapshot,hold_ms,request_id)

    def shoot(self,snapshot,hold_ms=1200,request_id=None):
        return self._consume('shoot',snapshot,hold_ms,request_id)

    def dig(self, snapshot, duration_ms=1500, request_id=None):
        op, repeated = self._prepare('dig', [snapshot,duration_ms], request_id, 'dig')
        if repeated: return self._view(op)
        before = self._observed(snapshot)
        target = before['target']
        require(target.get('type')=='Block', 'wrong_target', 'dig 需要瞄准方块')
        args = [target[k] for k in ('x','y','z','face')]
        if not self._lease(op, 'dig', duration_ms, before): return self._view(op)
        def tick():
            if self.active is not op or op.get('released'): return
            try:
                current = self._read()
                require(current['player_id']==before['player_id'] and current['dimension']==before['dimension']
                        and self._hud(), 'scene_changed', '玩家或界面已变化')
                require(self._target_id(current['target']) == self._target_id(target) and current['target']['in_reach'],
                        'target_changed', '挖掘目标已变化或超出距离')
                progressing, destroyed = self.native.local_player_continue_destroy_block(*args)
                op['block_destroyed_reported'] = bool(destroyed)
                if destroyed or not progressing:
                    self._release(op, 'completed' if destroyed else 'cancelled')
                else:
                    self._factory().CreateGame(self.api.GetLevelId()).AddTimer(.05,tick)
            except Exception as exc:
                op['end_reason']=as_text(exc)
                self._release(op,'cancelled')
        try:
            op['_release'].append(('dig', args[:3]))
            accepted, destroyed = self.native.local_player_start_destroy_block(*args)
            op['block_destroyed_reported'] = bool(destroyed)
            require(accepted or destroyed, 'input_rejected', '引擎拒绝开始挖掘')
            if destroyed: self._release(op)
            else: self._factory().CreateGame(self.api.GetLevelId()).AddTimer(.05,tick)
        except Exception as exc: return self._failed(op, exc)
        return self._view(op)

    def stop(self):
        if self.active: self._release(self.active,'cancelled')
        if self.sequence_busy(): self.sequence_job.update(state='cancelled',end_reason='requested_stop')
        return {'ok': self.active is None, 'active':operation_view(self.active), 'last_action':operation_view(self.last_action),
                'sequence':self._summary(self.sequence_job)}

    def sequence_busy(self):
        return self.sequence_job is not None and self.sequence_job.get('state')=='pending'

    @staticmethod
    def _brief(state):
        if not state: return None
        value={k:state.get(k) for k in ('position','rotation','selected_slot','carried','hunger','arrows')}
        target=state.get('target') or {}
        value['target']={k:target[k] for k in ('type','entityId','x','y','z','face','block','health','in_reach') if k in target}
        return value

    @staticmethod
    def _summary(op,details=False):
        value=operation_view(op)
        if value is None or details:return value
        records=value.get('results',[value])
        for record in records:
            before=record.pop('before',None) or {}
            after=record.pop('after',None) or {}
            changes={k:{'before':before.get(k),'after':v} for k,v in after.items() if before.get(k)!=v}
            if changes:record['changes']=changes
            if record.get('error') is None:record.pop('error',None)
        return value

    def status(self,operation=None,details=False):
        result=UIController.status(self,operation)
        if operation is None:
            result['sequence']=self._summary(self.sequence_job,details)
            result['active']=self._summary(self.active,details)
            result['last_action']=self._summary(self.last_action,details)
            return result
        return self._summary(result,details)

    def cancel(self,operation):
        if self.sequence_job and self.sequence_job['id']==operation and self.sequence_busy():
            self.stop()
        return UIController.cancel(self,operation)

    def _validate_steps(self,steps):
        require(isinstance(steps,list) and 1<=len(steps)<=32,'invalid_plan','连续动作必须包含 1–32 个步骤')
        schema={'move':({'forward','right','duration_ms','sprint'},set()),
                'look':({'pitch','yaw'},{'pitch','yaw'}),'look_at':({'x','y','z'},{'x','y','z'}),
                'select_slot':({'slot'},{'slot'}),'key':({'keys','hold_ms'},{'keys'}),
                'jump':(set(),set()),'sneak':({'duration_ms'},set()),'attack':(set(),set()),
                'use_item':({'mode','hold_ms'},set()),'dig':({'duration_ms'},set()),
                'eat':({'hold_ms'},set()),'shoot':({'hold_ms'},set()),'wait':({'duration_ms'},{'duration_ms'})}
        total=0
        for step in steps:
            require(isinstance(step,dict) and step.get('action') in schema,'invalid_plan','步骤含未知动作')
            name=step['action']; allowed,required=schema[name]
            require(set(step)<=allowed|{'action','delay_ms','expect'} and required<=set(step),'invalid_plan','步骤参数缺失或不支持：'+name)
            caps=self.capabilities()['capabilities']
            if name=='use_item':
                mode=step.get('mode','auto')
                require(caps.get('use_air') if mode=='air' else caps.get('use_block') if mode=='block' else caps.get('use_air') or caps.get('use_block'),
                        'unsupported_capability','当前引擎不支持计划中的物品使用')
            elif name!='wait': require(caps.get(name,False),'unsupported_capability','当前引擎不支持步骤：'+name)
            delay=step.get('delay_ms',0)
            require(type(delay) is int and 0<=delay<=10000,'invalid_plan','delay_ms 必须是 0–10000')
            duration=step.get('duration_ms',step.get('hold_ms',{'move':500,'sneak':500,'key':80,'use_item':200,'dig':1500,'eat':2000,'shoot':1200}.get(name,0)))
            require(type(duration) is int and (0<=duration<=10000 if name=='wait' else duration==0 or 20<=duration<=10000),
                    'invalid_plan','步骤持续时间不合法')
            if name in ('move','sneak','key','use_item','dig','eat','shoot'):
                require(duration>=20,'invalid_plan','持续动作至少 20ms')
            for key in ('forward','right','pitch','yaw','x','y','z'):
                if key in step: require(finite(step[key]),'invalid_plan','坐标或方向必须是有限数值')
            if name=='look': require(-90<=step['pitch']<=90,'invalid_plan','pitch 超出范围')
            if name=='move':
                require(-1<=step.get('forward',0)<=1 and -1<=step.get('right',0)<=1 and (step.get('forward',0) or step.get('right',0)),
                        'invalid_plan','移动方向无效')
                require(type(step.get('sprint',False)) is bool and (not step.get('sprint') or step.get('forward',0)>0),'invalid_plan','疾跑参数无效')
            if name=='select_slot': require(type(step['slot']) is int and 1<=step['slot']<=9,'invalid_plan','slot 必须为 1–9')
            if name=='key': self._key_codes(step['keys'])
            if name=='use_item': require(step.get('mode','auto') in ('auto','air','block'),'invalid_plan','mode 无效')
            expect=step.get('expect',{})
            require(isinstance(expect,dict) and set(expect)<={'selected_slot','item','target'},'invalid_plan','expect 只支持 selected_slot/item/target')
            if 'selected_slot' in expect: require(type(expect['selected_slot']) is int and 1<=expect['selected_slot']<=9,'invalid_plan','断言槽位必须是 1–9')
            if 'item' in expect: require(isinstance(expect['item'],(str,type(u''))) and 0<len(expect['item'])<=256,'invalid_plan','断言物品必须是标识符文本')
            if 'target' in expect:
                require(isinstance(expect['target'],dict) and set(expect['target'])<={'type','x','y','z','entityId'},'invalid_plan','目标断言参数无效')
                for k in ('x','y','z'):
                    if k in expect['target']:require(type(expect['target'][k]) is int,'invalid_plan','方块断言坐标必须是整数')
                if 'type' in expect['target']:require(expect['target']['type'] in ('Block','Entity','None'),'invalid_plan','目标类型无效')
                if 'entityId' in expect['target']:require(isinstance(expect['target']['entityId'],(str,type(u''))),'invalid_plan','实体 ID 必须为文本')
            total+=delay+duration+100
        require(total<=120000,'invalid_plan','连续动作的计划时间不能超过 120 秒')

    def sequence(self,steps,request_id=None):
        self._validate_steps(steps)
        import json
        plan=json.loads(json.dumps(steps))
        op,repeated=self._operation(request_id,['sequence',plan])
        if repeated:return self._view(op)
        self._ready('sequence')
        # JSON 克隆，调用者随后修改原列表不能改变已提交计划。
        op.update(action='sequence',state='pending',index=0,count=len(steps),results=[],effect_verified=False,
                  _steps=plan,_deadline=self.clock()+120,_waiting=None,_delay_done=False,_wait_started=False)
        self._save(op);self.sequence_job=op
        self._schedule_sequence(op,.01)
        return self._view(op)

    def _schedule_sequence(self,job,delay):
        try:
            timer=self._factory().CreateGame(self.api.GetLevelId()).AddTimer(delay,lambda:self._sequence_tick(job))
            require(timer is not None,'timer_unavailable','无法安排下一步')
        except Exception as exc:
            job.update(state='failed',error=as_text(exc))
            if self.active:self._release(self.active,'cancelled')

    def _sequence_tick(self,job):
        if self.sequence_job is not job or job['state']!='pending':return
        try:
            require(self.clock()<job['_deadline'],'sequence_timeout','连续动作超过 120 秒')
            require(self._hud(),'menu_open','界面已经切换')
            if job['_waiting']:
                child=self.operations[job['_waiting']]
                if child['state']=='pending':self._schedule_sequence(job,.05);return
                if child.get('expected_rotation') and child['state']=='completed':
                    current=self._read()['rotation'];expected=child['expected_rotation']
                    require(abs(current['pitch']-expected['pitch'])<=.2 and abs((current['yaw']-expected['yaw']+180)%360-180)<=.2,
                            'rotation_changed','朝向没有保持在指定方向，停止后续动作')
                job['results'].append({'step':job['index']+1,'action':child['action'],'operation':child['id'],
                    'state':child['state'],'before':self._brief(child.get('before')),'after':self._brief(child.get('after')),
                    'error':child.get('error'),'effect_verified':False})
                require(child['state']=='completed','step_failed','步骤未完成，后续动作已停止')
                job['index']+=1;job['_waiting']=None;job['_delay_done']=False
                self._schedule_sequence(job,.1);return
            if job['index']>=len(job['_steps']):job['state']='completed';return
            step=job['_steps'][job['index']]
            if not job['_delay_done']:
                job['_delay_done']=True
                if step.get('delay_ms',0):self._schedule_sequence(job,step['delay_ms']/1000.);return
            if step['action']=='wait':
                if not job['_wait_started']:
                    job['_wait_started']=True
                    self._schedule_sequence(job,max(.01,step['duration_ms']/1000.));return
                job['results'].append({'step':job['index']+1,'action':'wait','state':'completed','duration_ms':step['duration_ms']})
                job['index']+=1;job['_delay_done']=False
                job['_wait_started']=False
                self._schedule_sequence(job,.01);return
            before=self.snapshot()
            expected=step.get('expect',{})
            require('selected_slot' not in expected or before['selected_slot']==expected['selected_slot'],'expectation_failed','快捷栏槽位与计划不符')
            require('item' not in expected or (before['carried'] or {}).get('name')==expected['item'],'expectation_failed','手持物品与计划不符')
            require(all(before['target'].get(k)==v for k,v in expected.get('target',{}).items()),'expectation_failed','瞄准目标与计划不符')
            parameters={k:v for k,v in step.items() if k not in ('action','delay_ms','expect')}
            if step['action'] in ('attack','use_item','dig','eat','shoot'):parameters['snapshot']=before['snapshot']
            self._in_sequence=True
            try:result=getattr(self,step['action'])(**parameters)
            finally:self._in_sequence=False
            job['_waiting']=result['id']
            job['active_operation']=result['id']
            self._schedule_sequence(job,.05)
        except Exception as exc:
            job.update(state='failed',error=as_text(exc),code=getattr(exc,'code','step_failed'))
            if self.active:self._release(self.active,'cancelled')

    def close(self):
        result=self.stop()
        require(result['ok'], 'release_failed', '玩家输入释放结果未知，保留控制层以便 stop 重试')
        self.closed=True
        self.observation=None
        return result

    def dispatch(self, action, **parameters):
        try:
            require(action in ('snapshot','look','look_at','select_slot','move','jump','sneak','key','attack','use_item','dig','eat','shoot','sequence','status','cancel','stop'),
                    'unknown_action','未知玩家动作')
            return getattr(self,action)(**parameters)
        except (UIError,TypeError,ValueError) as exc:
            return {'ok':False,'code':getattr(exc,'code','invalid_argument'),'error':as_text(exc),'refresh_required':True}

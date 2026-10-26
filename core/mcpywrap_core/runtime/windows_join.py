"""Windows 本地组的受控自动加入；独占本次客机的初始化阶段。"""
from pathlib import Path
import json
import socket
import threading
import time
import uuid

from ..engines.host import EngineError
from ..mcstudio import sessions
from ..mcstudio.processes import checked_process
from . import storage
from .lan_menu import choose


PROBE = '''import mod.client.extraClientApi as api, clientlevel, gui
_player = api.GetLocalPlayerId()
_name = api.GetEngineCompFactory().CreateName(_player) if _player not in (None,-1,'-1') else None
_result = {'network_id': str(clientlevel.get_nethernet_id()), 'level': str(api.GetLevelId()),
 'player': _player, 'screen': gui.get_top_screen(),
 'name': _name.GetName() if _name else None}
'''


def target(host):
    from ..mcstudio.runtime_debug import control_request
    process = checked_process(host['game'])
    if not process or not host.get('world_ready'):
        raise EngineError('本地主机尚未就绪。', 'host_not_ready')
    probe = control_request(host['project'], host['session'], 'execute', code=PROBE, side='client')
    value = probe.get('value')
    if probe.get('state') != 'completed' or not isinstance(value,dict) or value.get('network_id') in (None,'0','-1','None'):
        raise EngineError('未能取得主机的本地联机身份。', 'lan_target_unavailable')
    if value.get('screen') != 'hud_screen' or not isinstance(value.get('name'), str) or not value['name']:
        raise EngineError('主机玩家资料尚未就绪。', 'host_not_ready')
    if value.get('level') != str(host.get('level_id')):
        raise EngineError('主机已切换世界，未启动客机。', 'world_changed')
    query = getattr(process, 'net_connections', None) or process.connections
    ports = {item.laddr.port for item in query(kind='udp')
             if item.family == socket.AF_INET6 and item.laddr and item.laddr.ip == '::'}
    # 不从日志里猜端口，也不把 Safaia/OreUI 或多个候选中的第一个当 LAN。
    if len(ports) != 1:
        raise EngineError('无法唯一确认本地主机的 LAN 监听端口。', 'lan_target_ambiguous',
                          '请保留会话和日志；不会猜测端口或修改其他游戏。', ports=sorted(ports))
    return dict(value, port=ports.pop(), game=host['game'], session=host['session'])


def bootstrap(data, engine, directory):
    from ..mcstudio.runtime_cppconfig import gen_runtime_config, write_cppconfig
    # 每个角色只保留一个独立的工具引导世界，不把用户世界用于初始化。
    level = str(uuid.uuid5(uuid.NAMESPACE_URL, 'mcpy-local-join/'+data['group']+'/'+data['role']))
    config = gen_runtime_config(engine.version, 'mcpy connection setup', level, engine.download_dir, '', [], [])
    config['world_info']['world_type'] = 2
    config['player_info'] = dict(data['network']['player'], urs='')
    path = directory/'bootstrap.cppconfig'
    write_cppconfig(path, config)
    data['network']['bootstrap_level'] = level
    return path


TOUCH = '''import sys, gui, notify
class _McpyLanTouch(object):
    def __init__(self, x, y):
        self.x, self.y, self.ticks, self.released = x, y, 0, False
    def tick(self, *args):
        self.ticks += 1
        if self.ticks < 5: return
        try:
            self.released = bool(gui.simulate_button_event(self.x, self.y, 1))
        finally:
            notify.unregist_handle('on_tick_update', self, self.tick)
previous = getattr(sys, '_mcpy_lan_touch', None)
if previous is not None and not previous.released:
    raise RuntimeError('previous_menu_input_not_released')
sys._mcpy_lan_touch = _McpyLanTouch(%d, %d)
notify.register_handle('on_tick_update', sys._mcpy_lan_touch, sys._mcpy_lan_touch.tick)
_result = bool(gui.simulate_button_event(%d, %d, 0))
'''


class AutoJoin:
    def __init__(self, data, channel, timeout=300):
        self.data, self.channel = data, channel
        self.directory = sessions.session_path(data['project'], data['session'])
        self.target = data['network']['lan_target']
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.value = {'state':'initializing','automatic':True,'target_port':self.target['port']}
        self.timeout = timeout
        self.thread = threading.Thread(target=self.run,daemon=True)
        self.channel.joining = True

    def start(self):
        self.thread.start()
        return self

    def status(self):
        with self.lock:
            return dict(self.value)

    def update(self, **values):
        with self.lock:
            self.value.update(values)
            storage.write(self.directory/'local-join.json', self.value)

    def cancelled(self):
        return self.stop.is_set() or (self.directory/'stop').exists()

    def host_valid(self):
        from .groups import is_local_guest
        if not is_local_guest(self.data['project'], self.data) or not checked_process(self.target['game']):
            raise ValueError('原主机或组成员已变化，自动加入已停止。')

    def execute(self, code):
        result = self.channel.execute(code, 'client')
        if result.get('state') != 'completed':
            raise ValueError('自动加入脚本未完成：'+str(result.get('error') or result.get('state')))
        return result.get('value')

    def run(self):
        from ..mcstudio.lan_window import observe
        deadline = time.monotonic()+self.timeout
        phase, selected, last = 'initializing', False, None
        last_time = 0
        try:
            while not self.cancelled() and time.monotonic()<deadline:
                self.host_valid()
                if not self.channel.connected.is_set() or not self.channel.ready():
                    self.stop.wait(.5)
                    continue
                probe = self.execute(PROBE)
                if probe.get('screen') == 'hud_screen' and probe.get('network_id') == self.target['network_id']:
                    if probe.get('level') != self.target['level']:
                        raise ValueError('已进入其他世界，自动加入已停止。')
                    self.update(state='joined', joined_at=time.time())
                    return
                if (phase != 'initializing' and probe.get('screen') == 'hud_screen' and
                        probe.get('level') != self.data['network']['bootstrap_level']):
                    raise ValueError('客机进入了非目标世界，自动加入已停止。')
                if phase == 'initializing':
                    if probe.get('level') != self.data['network']['bootstrap_level']:
                        raise ValueError('初始化世界身份不匹配，未发送菜单输入。')
                    self.execute('import mod.client.extraClientApi as api\napi.OpenPauseGui()')
                    phase = 'leaving_setup'
                    self.update(state=phase)
                    self.stop.wait(.5)
                view = observe(self.data['game'])
                storage.write(self.directory/'local-join-menu.json', view)
                action = choose(view, self.target['name'], selected, phase=='leaving_setup')
                if not action:
                    if last and time.monotonic()-last_time>45 and phase=='leaving_setup':
                        raise ValueError('无法确认引导世界已退出。')
                    self.stop.wait(1)
                    continue
                key = action.kind
                if key == last:
                    if time.monotonic()-last_time>30:
                        raise ValueError('菜单操作后界面未变化，未重复点击：'+action.kind)
                    self.stop.wait(1)
                    continue
                # 再取一次实时观测，拒绝布局切换期间的旧位置。
                fresh = observe(self.data['game'])
                checked = choose(fresh,self.target['name'],selected,phase=='leaving_setup')
                if not checked or checked.kind!=action.kind or any(abs(a-b)>6 for a,b in zip(checked.point,action.point)):
                    self.stop.wait(.5)
                    continue
                self.host_valid()
                x,y = map(int,checked.point)
                if not self.execute(TOUCH % (x,y,x,y)):
                    raise ValueError('引擎拒绝后台菜单输入。')
                last,last_time = key,time.monotonic()
                if action.kind=='leave_bootstrap':
                    phase='finding_host'
                elif action.kind=='host':
                    selected=True
                    phase='joining'
                self.update(state=phase,last_action=action.kind,last_action_at=time.time())
                self.stop.wait(1.2)
            if self.cancelled():
                self.update(state='cancelled')
            else:
                self.update(state='failed',code='local_join_timeout',error='自动加入超时，请检查客机画面和 local-join-menu.json。')
        except Exception as exc:
            if self.cancelled():
                self.update(state='cancelled')
            else:
                self.update(state='failed',code='local_join_failed',error=str(exc))
        finally:
            self.channel.joining = False

    def close(self):
        self.stop.set()
        self.thread.join(timeout=15)

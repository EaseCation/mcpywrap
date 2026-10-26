"""Two-player development groups coordinate existing, independently addressable sessions."""
from dataclasses import asdict
from pathlib import Path
import time
import uuid

from . import storage, occupancy
from ..engines.backend import get_backend
from ..engines.host import EngineError
from ..mcstudio import sessions
from ..utils.locks import directory_lock, LockBusy

PLAYER_PROBE = '''import mod.client.extraClientApi as api
import gui
players = api.GetPlayerList()
factory = api.GetEngineCompFactory()
_result = {'player': api.GetLocalPlayerId(), 'players': players,
           'player_names': dict((str(p), factory.CreateName(p).GetName()) for p in players),
           'level': api.GetLevelId(), 'screen': gui.get_top_screen()}
'''


class ObservationBusy(Exception):
    """明确未发送的只读探针争用，不代表原连接已断开。"""


def path(project, group):
    return Path(project).resolve()/'.runtime/groups'/storage.identifier(group, '联调组 ID')/'group.json'


def read(project, group):
    value = storage.read(path(project, group))
    if value is None or value.get('project') != str(Path(project).resolve()):
        raise EngineError('联调组不存在或不属于当前项目。', 'group_not_found')
    for member in value['members']:
        member.pop('owned', None)
    return value


def save(record):
    storage.write(path(record['project'], record['group']), record)


def membership(project, session):
    for candidate in (Path(project)/'.runtime/groups').glob('*/group.json'):
        record = storage.read(candidate)
        if any(member.get('session') == session for member in record['members']):
            return record
    return None


def is_local_guest(project, data):
    group = data.get('group')
    if not group or not (data.get('network') or {}).get('local_host'):
        return False
    try:
        record = read(project, group)
        return (record['kind'] == 'local' and record['members'][1].get('session') == data['session']
                and record['members'][0].get('session') == data['network']['local_host']
                and occupancy.live(sessions.read(project, data['network']['local_host'])))
    except (OSError, ValueError):
        return False


def capabilities(project, group):
    from ..mcstudio.session_capabilities import inspect_session
    record = read(project, group)
    current = status(project, group)
    members = []
    for member in record['members']:
        try:
            info = inspect_session(project, member['session']) if member.get('session') else {}
        except (OSError, ValueError):
            info = {}
        members.append({'role': member['role'], 'session': member.get('session'), 'capabilities': info})
    return {'group': group, 'kind': record['kind'], 'members': members,
            'state': current['state'], 'connection_verified': current['connection_verified'],
            'coordinated_reload': record['kind'] == 'local',
            'join': record.get('recipe', {}).get('join_mode','manual') if record['kind'] == 'local' else 'automatic',
            'resource_reload': False,
            'hint': '外部服务器的代码和资源由服务器管理。' if record['kind'] == 'network' else
                    '确认两名玩家加入后可协调 Python 更新；客机资源缓存尚不支持组资源热更。'}


def reload(project, group, kind, target=None, source=None, side='client'):
    from ..mcstudio.hot_reload import reload_session, module_source, reload_code
    from .deployment import refresh
    if side not in ('client', 'server', 'both') or (kind != 'python' and side != 'client'):
        raise EngineError('资源仅在客户端重载；Python 可选择 client/server/both。', 'invalid_reload_target')
    record = read(project, group)
    if record['kind'] != 'local':
        raise EngineError('外服组不管理服务器提供的代码和资源。', 'unsupported_reload')
    with directory_lock(path(project, group).parent/'lock'):
        record = read(project, group)
        if _cancelled(record):
            raise EngineError('联调组正在停止，未更新运行文件。', 'cancelled')
        host = sessions.read(project, record['members'][0]['session'])
        member_data = [sessions.read(project, m['session']) for m in record['members']]
        if any(data['state'] != 'running' or not data.get('world_ready') or not occupancy.live(data)
               for data in member_data):
            raise EngineError('联调组成员尚未全部就绪，未更新任何运行文件。', 'group_not_ready')
        record.update(connection_verified=False, connection_checked_at=time.time())
        try:
            if not _verify_once(record):
                raise EngineError('未确认两名玩家仍在同一世界，未更新运行文件。', 'group_not_ready')
        except (OSError, ValueError):
            save(record)
            raise
        record.update(connection_verified=True, connection_verified_at=time.time())
        save(record)
        actions = []
        if side in ('server', 'both'):
            actions.append((record['members'][0], host, 'server'))
        if side in ('client', 'both'):
            actions.extend((m, data, 'client') for m, data in zip(record['members'], member_data))
        for member, data, selected in actions:
            reason = get_backend(data['backend']).reload_restriction(data, kind)
            if reason:
                raise EngineError(reason, 'unsupported_reload', session=data['session'])
        # Resource packs received from a host may live in a guest download
        # cache. Do not claim that changing the host's directory updates it.
        if kind != 'python':
            raise EngineError('客机使用下载的资源缓存，尚不支持组资源热更；未修改任何文件。',
                              'resource_sync_unverified', '停止并重新运行联调组，再从卡片加入。')
        resolved_source = module_source(project, target)
        source = resolved_source if source is None else source
        if not isinstance(source, bytes) or len(source) > 24000:
            raise ValueError('热更模块源码必须是字节内容且不超过 24 KiB')
        reload_code(kind, target, source)
        allowed = tuple(data['session'] for data in member_data)
        pack = refresh(project, host, allowed_sessions=allowed)
        if host['backend'] == 'macos-arm64':
            get_backend(host['backend']).sync_runtime_packs(host, pack)
        results = []
        for member, data, selected in actions:
            try:
                result = reload_session(project, data['session'], kind, target, source, selected, deployed=True)
            except (OSError, ValueError) as error:
                result = {'state': 'failed', 'error': str(error)}
            result.update(role=member['role'], session=data['session'], side=selected)
            results.append(result)
        success = all(r.get('state') in ('completed', 'triggered') and
                      not (isinstance(r.get('value'), dict) and r['value'].get('ok') is False) for r in results)
        record['last_update'] = {'kind': kind, 'side': side, 'results': results, 'ok': success}
        save(record)
        return {'ok': success, 'group': group, 'state': 'completed' if success else 'partial',
                'results': results, 'effect_verified': False,
                'hint': None if success else '部分端侧未确认更新，请检查结果；不会自动重复执行。'}


def status(project, group):
    record = read(project, group)
    members = []
    for item in record['members']:
        member = dict(item)
        if member.get('session'):
            try:
                if not sessions.session_path(project, member['session']).joinpath('session.json').exists():
                    member['state'] = 'failed' if record.get('error') else member['state']
                    members.append(member)
                    continue
                current = sessions.read(project, member['session'])
                member.update(state=current['state'], world_ready=current.get('world_ready', False),
                              game=current.get('game'), error=current.get('error'),
                              log_path=current.get('log_path'))
                if current.get('local_join'):
                    member['local_join'] = current['local_join']
            except (ValueError, OSError) as error:
                member.update(state='failed', error=str(error))
        else:
            member.setdefault('state', 'pending')
        members.append(member)
    running = [member for member in members if member['state'] == 'running']
    manual = record['kind'] == 'local'
    automatic = manual and record.get('recipe', {}).get('join_mode') == 'auto'
    state = ('ready' if len(running) == 2 and record.get('connection_verified') else
             'waiting_for_join' if manual and len(running) == 2 and not record.get('error') else
             'running' if len(running) == 2 else 'partial' if running else
             'starting' if any(m['state'] in ('starting', 'pending') for m in members) else 'exited')
    join_problem = (members[1].get('local_join') or {}) if automatic and len(members)>1 else {}
    if automatic and state == 'waiting_for_join':
        state = 'partial' if join_problem.get('state') == 'failed' else 'joining'
    if record.get('kind') == 'local' and members[0]['state'] != 'running' and len(members) > 1 and members[1]['state'] == 'running':
        members[1]['connection_state'] = 'host_disconnected'
    elif manual and len(members) > 1 and members[1]['state'] == 'running':
        members[1]['connection_state'] = ('verified' if state == 'ready' else
                                          join_problem.get('state','joining') if automatic else
                                          record.get('join_state', 'waiting_for_join'))
    instruction = record.get('join_instruction') if manual and state not in ('ready', 'exited') else None
    if automatic and state not in ('ready','exited'):
        instruction = (join_problem.get('error') if join_problem.get('state') == 'failed' else
                       '正在自动加入目标主机；完成后将校验双方玩家与服务端名单。')
    if manual and members[0]['state'] not in ('running', 'starting') and running:
        instruction = '主机已退出，客户端仍保留；请明确重启联调组或停止客户端。'
    elif manual and members[1]['state'] in ('exited', 'failed') and running:
        instruction = ('客户端 2 已退出，主机仍在运行。使用 restart --session ' +
                       members[1]['session'] + ' 重新打开客户端。')
    elif manual and record.get('join_state') == 'wrong_world':
        instruction = '客户端 2 未加入指定主机，请退出当前世界后重新选择目标局域网卡片。'
    if manual and state != 'exited' and record.get('source_matches') is False:
        instruction = ((instruction + ' ') if instruction else '') + '主机继续使用已加载版本；源码改动尚未应用，应用改动请重启联调组。'
    return {'ok': not record.get('error') and join_problem.get('state') != 'failed', 'group': group, 'session': members[0].get('session'),
            'kind': record['kind'], 'backend': record['backend'],
            'state': state, 'members': members, 'connection_verified': state == 'ready',
            'connection_verified_at': record.get('connection_verified_at'),
            'connection_checked_at': record.get('connection_checked_at'),
            'error': record.get('error') or join_problem.get('error'), 'code': record.get('code') or join_problem.get('code'), 'hint': record.get('hint') or instruction,
            'details': record.get('details', {}), 'actions': record.get('actions', []), 'operation_id':record.get('operation_id'),
            'join_instruction': instruction, 'world_name': record.get('world_name'),
            'source_matches': record.get('source_matches')}


def list_groups(project):
    return [status(project, p.parent.name) for p in (Path(project)/'.runtime/groups').glob('*/group.json')]


def _new(project, backend, kind, recipe):
    record = {'schema_version': 1, 'group': uuid.uuid4().hex, 'project': str(Path(project).resolve()),
              'backend': backend.id, 'kind': kind, 'recipe': recipe, 'created_at': time.time(),
              'members': [{'role': role, 'session': uuid.uuid4().hex, 'state': 'pending'}
                          for role in (('host', 'guest') if kind == 'local' else ('client1', 'client2'))],
              'connection_verified': False, 'error': None}
    save(record)
    return record


def _cancelled(record):
    return path(record['project'], record['group']).with_name('stop').exists()


def _set_failure(record, error):
    from .diagnostics import diagnostic
    record.update(diagnostic(error))
    for action in record.get('actions', []):
        if action.get('kind') in ('migrate', 'inspect'):
            argv=list(action['argv'])
            if '--session' in argv:
                index=argv.index('--session')
                del argv[index:index+2]
            action['argv']=argv+['--group',record['group']]
    for member in record['members']:
        if (member.get('state') in ('pending', 'starting') and
                not sessions.session_path(record['project'], member['session']).joinpath('session.json').exists()):
            member['error'] = str(error) if member['state'] == 'starting' else '上一成员尚未就绪，此客户端未启动。'
            member['state'] = 'failed'
    record.update(connection_verified=False, error=str(error), code=getattr(error, 'code', 'group_failed'),
                  hint=((getattr(error, 'hint', None) or '') + ' 使用 status --group ' + record['group'] +
                        ' 查询；通过 restart --session 重试失败成员。').strip())


def _failure(record, error):
    _set_failure(record, error)
    save(record)
    result = status(record['project'], record['group'])
    result['ok'] = False
    return result


def _observe(record, member):
    from ..mcstudio.runtime_debug import control_request
    data = sessions.read(record['project'], member['session'])
    if data['state'] not in ('starting', 'running'):
        raise EngineError('客户端提前退出：' + member['role'], 'client_exited')
    if data['state'] != 'running' or not data.get('world_ready'):
        return None
    code = PLAYER_PROBE
    if record['kind'] == 'local':
        code += "\nimport clientlevel\n_result['host_network_id'] = str(clientlevel.get_nethernet_id())\n"
    result = control_request(record['project'], member['session'], 'execute', code=code, side='client')
    if result.get('error') == '已有游戏脚本正在执行':
        raise ObservationBusy()
    if result.get('state') == 'unknown':
        raise EngineError('客户端就绪探针结果未知，请检查会话后重试。', 'verification_unknown')
    if result.get('state') != 'completed' or not isinstance(result.get('value'), dict):
        return None
    value = result['value']
    if value.get('player') in (None, -1, '-1') or value.get('level') in (None, -1, '-1'):
        return None
    if data.get('mode') == 'local' and str(value['level']) != str(data.get('level_id')):
        raise EngineError('主机已切换到其他世界，未对其进行部署或更新。', 'world_changed',
                          '请重新运行原世界或明确选择新的操作目标。', session=member['session'])
    member.update(player_id=str(value['player']), observed_players=[str(x) for x in value.get('players', [])],
                  player_name=(value.get('player_names') or {}).get(str(value['player'])),
                  observed_player_names=value.get('player_names', {}), observed_level=str(value['level']))
    return value


def _ready(record, member, timeout=300):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _cancelled(record):
            raise EngineError('联调启动已取消。', 'cancelled')
        try:
            value = _observe(record, member)
        except ObservationBusy:
            value = None
        if value is not None:
            save(record)
            return value
        time.sleep(.5)
    raise EngineError('未能在时限内确认客户端进入世界：' + member['role'], 'world_ready_timeout')


def _verify_once(record):
    observations = [_observe(record, member) for member in record['members']]
    if all(observations):
        names = [(value.get('player_names') or {}).get(str(value['player'])) for value in observations]
        if all(names) and len(set(names)) == 2:
            expected = set(names)
            if record['kind'] == 'local':
                host_id, guest_id = (value.get('host_network_id') for value in observations)
                if not host_id or host_id in ('0', '-1', 'None') or host_id != guest_id:
                    record['join_state'] = 'wrong_world'
                    return False
                from ..mcstudio.runtime_debug import control_request
                result = control_request(record['project'], record['members'][0]['session'], 'execute',
                                         code='import mod.server.extraServerApi as api\n'
                                              '_result = dict((str(p), api.GetEngineCompFactory().CreateName(p).GetName()) '
                                              'for p in api.GetPlayerList())', side='server')
                if result.get('error') == '已有游戏脚本正在执行':
                    raise ObservationBusy()
                rosters = [result.get('value')] if result.get('state') == 'completed' else []
            else:
                rosters = [value.get('player_names') for value in observations]
            # Actor IDs are scoped to each client: some servers map every
            # local player to 1. Require each view to identify both named
            # players unambiguously instead of comparing those actor IDs.
            return bool(rosters) and all(isinstance(roster, dict) and all(
                list(roster.values()).count(name) == 1 for name in expected) for roster in rosters)
    return False


def refresh_status(project, group):
    """Probe outside the group lock; commit only to the observed generation."""
    from copy import deepcopy
    try:
        with directory_lock(path(project, group).parent/'lock'):
            original = read(project, group)
            current = status(project, group)
        record = deepcopy(original)
        record.update(connection_verified=False, connection_checked_at=time.time())
        if record['kind'] == 'local':
            record['join_state'] = 'waiting_for_join'
        if all(m['state'] == 'running' and m.get('world_ready') for m in current['members']):
            try:
                if _verify_once(record):
                    record.update(connection_verified=True, connection_verified_at=time.time(), join_state='verified')
                    if record.get('code') in (None, 'world_ready_timeout', 'players_not_verified',
                                              'client_exited', 'verification_unknown'):
                        record.update(error=None, code=None, hint=None)
            except ObservationBusy:
                return current
            except (ValueError, OSError) as error:
                if not any((sessions.session_path(project, m['session'])/'stop').exists()
                           for m in record['members']):
                    _set_failure(record, error)
        if record.get('code') in ('group_failed', 'client_exited', 'verification_unknown') and any(
                (sessions.session_path(project, m['session'])/'stop').exists() for m in record['members']):
            record.update(error=None, code=None, hint=None)
        with directory_lock(path(project, group).parent/'lock'):
            if read(project, group) == original and not _cancelled(record):
                save(record)
    except LockBusy:
        pass  # The active launch/update owns the observations until it finishes.
    return status(project, group)


def verify(record, timeout=60):
    # A previous success does not describe the members after a reconnect or
    # failed probe. Persist invalidation before making any blocking requests.
    record['connection_verified'] = False
    save(record)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _cancelled(record):
            raise EngineError('联调验证已取消。', 'cancelled')
        try:
            verified = _verify_once(record)
        except ObservationBusy:
            verified = False
        if verified:
            record.update(connection_verified=True, connection_verified_at=time.time(), connection_checked_at=time.time(),
                          error=None, code=None, hint=None)
            save(record)
            return status(record['project'], record['group'])
        time.sleep(.5)
    raise EngineError('未确认两个不同玩家进入同一个世界；游戏进程已保留。', 'players_not_verified')


def _connect_member(record, index, target=None, local_host=None, created=None):
    member = record['members'][index]
    sid = (member['session'] if member.get('state') == 'pending' and
           not sessions.session_path(record['project'], member['session']).joinpath('session.json').exists()
           else uuid.uuid4().hex)
    member.update(session=sid, state='starting', error=None)
    for key in ('player_id', 'player_name', 'observed_players', 'observed_player_names', 'observed_level'):
        member.pop(key, None)
    record.update(connection_verified=False, connection_verified_at=None, connection_checked_at=None,
                  error=None, code=None, hint=None)
    save(record)
    if _cancelled(record):
        raise EngineError('联调启动已取消。', 'cancelled')
    if created is not None:
        created.append(sid)
    backend = get_backend(record['backend'])
    # Stable anonymous identities belong to roles, not processes. Keep names
    # within the game's player-name limit and IDs within the verified int range.
    member.setdefault('player', {'user_name': 'mcpy_' + record['group'][:8] + '_' + str(index+1),
                                 'user_id': (int(record['group'][:8], 16) % (2**30-1) + 1)*2 + index})
    save(record)
    overrides = record['recipe'].get('overrides') or {}
    if local_host:
        host = sessions.read(record['project'], local_host)
    options = dict(project_dir=record['project'], session_id=sid, group=record['group'],
                   role=member['role'], player=member['player'],
                   background=record['recipe'].get('background',
                              record['recipe'].get('options', {}).get('background', False)))
    if local_host:
        if record['backend'] == 'windows':
            options['join_mode'] = record.get('recipe', {}).get('join_mode', 'manual')
        result = backend.start_guest(host, **options)
    else:
        result = backend.connect(target, engine_overrides=overrides, detach=True, **options)
    if result.get('engine_version'):
        record['recipe']['overrides'] = dict(overrides, engine_version=result['engine_version'])
    member.update(session=result['session'], state=result['state'])
    save(record)
    if not local_host:
        _ready(record, member)


def _prepare_local(record):
    host = sessions.read(record['project'], record['members'][0]['session'])
    get_backend(record['backend']).prepare_guest(host)
    from ..mcstudio.runtime_cppconfig import read_cppconfig
    config = read_cppconfig(host['config_path'])
    from .deployment import matches_source
    record['source_matches'] = matches_source(record['project'], host)
    record['world_name'] = host.get('world_name') or config['world_info'].get('name') or host['level_id']
    record['join_instruction'] = ('在客户端 2 选择“开始游戏”，点击标有“局域网世界”的“' +
                                  record['world_name'] + '”卡片加入；不要打开同名本地存档。')
    record.pop('target', None)
    save(record)


def _local_result(record, created):
    # Human input has no startup deadline. The guest worker verifies joining.
    return dict(status(record['project'], record['group']), owned_sessions=created)


class GroupMonitor:
    """One monitor owned by the second member's worker, independent of any view."""

    def __init__(self, data):
        import threading
        self.data = data
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _run(self):
        while not self.stopped.wait(2):
            try:
                record = read(self.data['project'], self.data['group'])
                if (record['members'][1]['session'] != self.data['session'] or _cancelled(record)):
                    return
                refresh_status(self.data['project'], self.data['group'])
                host = sessions.read(self.data['project'], record['members'][0]['session'])
                if not occupancy.live(host):
                    return
            except (OSError, ValueError):
                # State remains unverified; a later successful observation can recover.
                continue

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=15)


def start_local(project, backend, options, join_mode=None):
    requested_join = join_mode
    join_mode = join_mode or ('auto' if 'local-dual-client-auto' in backend.capabilities else 'manual')
    if join_mode not in ('auto', 'manual') or (join_mode == 'auto' and backend.id != 'windows'):
        raise EngineError('当前平台不支持所选的本地加入方式。', 'unsupported_feature')
    if options.get('mcs_auth') or options.get('auth_context'):
        raise EngineError('双客户端联调目前使用无认证开发身份。', 'unsupported_auth')
    backend.prepare_guest(None)
    options = dict(options, detach=True, no_gui=True)
    # Start/reuse the host before creating a new group; failures remain normal
    # world failures and cannot leave a synthetic successful group behind.
    result = backend.run(project, **options)
    created = [] if result.get('already_running') else [result['session']]
    with directory_lock(Path(project)/'.runtime/group-registry-lock'):
        existing = membership(project, result['session'])
        record = existing or _new(project, backend, 'local', {'options': options, 'overrides': options.get('overrides') or {}, 'join_mode': join_mode})
        if not existing:
            record['members'][0].update(session=result['session'], state='running')
            save(record)
    with directory_lock(path(project, record['group']).parent/'lock'):
        # Another caller may have finished the guest between locks. Always use
        # the latest member reservation.
        record = read(project, record['group'])
        try:
            if requested_join and requested_join != record['recipe'].get('join_mode','manual'):
                guest_id = record['members'][1].get('session')
                if guest_id and occupancy.live(sessions.read(project,guest_id)):
                    raise EngineError('已有客机使用不同的加入方式。', 'session_conflict',
                                      '请先停止该客机，再用 run --clients 2 --join-mode '+requested_join+' 启动。')
                record['recipe']['join_mode'] = requested_join
                save(record)
            _ready(record, record['members'][0])
            _prepare_local(record)
            guest = record['members'][1]
            if guest.get('session') and sessions.session_path(project, guest['session']).joinpath('session.json').exists():
                current = sessions.read(project, guest['session'])
                if occupancy.live(current):
                    if record.get('code') in ('world_ready_timeout', 'players_not_verified'):
                        record.update(error=None, code=None, hint=None)
                        save(record)
                    return _local_result(record, created)
            _connect_member(record, 1, local_host=result['session'], created=created)
            return _local_result(record, created)
        except KeyboardInterrupt:
            _failure(record, EngineError('本次联调启动已中断。', 'cancelled'))
            stop_owned(project, record['group'], created)
            raise
        except (ValueError, OSError) as error:
            return dict(_failure(record, error), owned_sessions=created)


def start_network(project, backend, target, overrides=None, *, background=False):
    if target.auth != 'none':
        raise EngineError('双客户端进服尚不支持双账号认证。', 'unsupported_auth')
    record = _new(project, backend, 'network', {'target': asdict(target), 'overrides': overrides or {},
                                             'background': background})
    created = []
    with directory_lock(path(project, record['group']).parent/'lock'):
        try:
            for index in range(2):
                _connect_member(record, index, target, created=created)
            return dict(verify(record), owned_sessions=created)
        except KeyboardInterrupt:
            _failure(record, EngineError('本次联调启动已中断。', 'cancelled'))
            stop_owned(project, record['group'], created)
            raise
        except (ValueError, OSError) as error:
            return dict(_failure(record, error), owned_sessions=created)


def stop_owned(project, group, created):
    """Cancel one invocation, never infer ownership from a persisted group."""
    from ..command_context import report_warning
    owned = set(created)
    for member in reversed(read(project, group)['members']):
        sid = member.get('session')
        if sid not in owned or not sessions.session_path(project, sid).joinpath('session.json').exists():
            continue
        try:
            # Keep the host guard: a different caller may have added a guest.
            sessions.stop(project, sid)
        except (OSError, ValueError) as error:
            report_warning('会话 ' + sid + ' 未确认退出：' + str(error))


def guard_single_stop(project, session):
    record = membership(project, session)
    if not record or record['kind'] != 'local' or record['members'][0].get('session') != session:
        return
    guest = record['members'][1].get('session')
    if guest and sessions.session_path(project, guest).joinpath('session.json').exists():
        alive = occupancy.live(sessions.read(project, guest))
        if alive:
            raise EngineError('主机仍有关联客户端，请停止或重启整个联调组。', 'group_required',
                              '使用 stop --group ' + record['group'], group=record['group'])


def stop(project, group):
    read(project, group)  # Validate the target before creating a cancellation marker.
    path(project, group).with_name('stop').touch()
    with directory_lock(path(project, group).parent/'lock'):
        return _stop_members(read(project, group))


def _stop_members(record):
    project, group = record['project'], record['group']
    results = []
    for member in reversed(record['members']):
        sid = member.get('session')
        if not sid or not sessions.session_path(project, sid).joinpath('session.json').exists():
            continue
        try:
            result = dict(role=member['role'], **sessions.stop(project, sid, group_operation=True))
            results.append(result)
            if result.get('state') != 'exited' and record['kind'] == 'local':
                break
        except (ValueError, OSError) as error:
            results.append({'role': member['role'], 'session': sid, 'state': 'failed', 'error': str(error)})
            if record['kind'] == 'local':
                break  # Never stop the host while the guest's exit is uncertain.
    return {'ok': all(r['state'] == 'exited' for r in results), 'group': group, 'members': results}


def logs(project, group, tail=100, source='game'):
    record = read(project, group)
    result = []
    for member in record['members']:
        if member.get('session'):
            try:
                text = sessions.logs(project, member['session'], tail, source)
            except ValueError:
                text = ''
            result.append({'role': member['role'], 'session': member['session'], 'text': text})
    return {'group': group, 'logs': result}


def restart(project, *, session=None, group=None, migration=None):
    if group:
        created = []
        with directory_lock(path(project, group).parent/'lock'):
            record = read(project, group)
            if migration and (record['kind']!='local' or record['backend']!='windows'):
                raise EngineError('仅支持 Windows 本地联调组迁移。', 'unsupported_feature')
            if migration and migration.get('group_expect'):
                from .deployment_inspection import digest
                if digest(record) != migration['group_expect']:
                    raise EngineError('联调组配置已变化，请重新预览迁移。', 'plan_stale')
            path(project, group).with_name('stop').touch()
            outcome = _stop_members(record)
            if not outcome['ok']:
                return outcome
            backend = get_backend(record['backend'])
            path(project, group).with_name('stop').unlink(missing_ok=True)
            record.update(error=None, code=None, hint=None, connection_verified=False)
            try:
                if record['kind'] == 'network':
                    from ..mcstudio.network import ServerTarget
                    for index in range(2):
                        _connect_member(record, index, ServerTarget(**record['recipe']['target']), created=created)
                else:
                    host = sessions.read(project, record['members'][0]['session'])
                    options = dict(record['recipe']['options'], new=False, world_config=None, instance_prefix=host['level_id'])
                    if migration:
                        options['migration'] = migration
                    result = backend.run(project, **options)
                    if not result.get('already_running'):
                        created.append(result['session'])
                    record['members'][0].update(session=result['session'], state='running')
                    save(record)
                    _ready(record, record['members'][0])
                    _prepare_local(record)
                    _connect_member(record, 1, local_host=result['session'], created=created)
                    return _local_result(record, created)
                return dict(verify(record), owned_sessions=created)
            except KeyboardInterrupt:
                _failure(record, EngineError('本次联调重启已中断。', 'cancelled'))
                stop_owned(project, group, created)
                raise
            except (OSError, ValueError) as error:
                return dict(_failure(record, error), owned_sessions=created)
    record = membership(project, session)
    if record:
        index = next(i for i, member in enumerate(record['members']) if member.get('session') == session)
        if record['kind'] == 'local' and index == 0:
            guard_single_stop(project, session)
            return restart(project, group=record['group'])
        with directory_lock(path(project, record['group']).parent/'lock'):
            record = read(project, record['group'])
            if record['members'][index].get('session') != session:
                raise EngineError('此成员已由另一次操作重启，请查询当前会话后再操作。',
                                  'group_changed', '使用 status --group ' + record['group'])
            created = []
            if sessions.session_path(project, session).joinpath('session.json').exists():
                outcome = sessions.stop(project, session, group_operation=True)
                if outcome.get('state') != 'exited':
                    return dict(outcome, ok=False, group=record['group'])
            path(project, record['group']).with_name('stop').unlink(missing_ok=True)
            try:
                host = record['members'][0]['session'] if record['kind'] == 'local' else None
                if host:
                    _ready(record, record['members'][0])
                    _prepare_local(record)
                    _connect_member(record, index, local_host=host, created=created)
                    return dict(_local_result(record, created), replacement_session=record['members'][index]['session'])
                else:
                    from ..mcstudio.network import ServerTarget
                    target = ServerTarget(**record['recipe']['target'])
                _connect_member(record, index, target, host, created)
                return dict(verify(record), owned_sessions=created)
            except KeyboardInterrupt:
                _failure(record, EngineError('本次客户端重试已中断。', 'cancelled'))
                stop_owned(project, record['group'], created)
                raise
            except (ValueError, OSError) as error:
                return dict(_failure(record, error), owned_sessions=created)
    data = sessions.read(project, session)
    if data.get('mcs_auth'):
        raise EngineError('此会话需要重新提供本次 MCS 身份。', 'authentication_required')
    sessions.stop(project, session)
    backend = get_backend(data.get('backend', 'windows'))
    if data.get('mode') == 'network':
        if data['network'].get('join') in ('manual','auto'):
            raise EngineError('此客机的联调组记录缺失，不能按外服会话重启。', 'group_not_found')
        from ..mcstudio.network import ServerTarget
        return backend.connect(ServerTarget(**data['network']['target']), project_dir=project,
                               engine_overrides=data.get('engine_overrides'), detach=True,
                               background=data.get('background', False))
    return backend.run(project, instance_prefix=data['level_id'], overrides=data.get('engine_overrides'), detach=True, no_gui=True,
                       background=data.get('background', False))

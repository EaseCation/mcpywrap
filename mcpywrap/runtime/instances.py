"""World recipes and successful initialization are distinct from launch attempts."""
from pathlib import Path
import os
import shutil
import time
import uuid

from . import storage, occupancy
from ..engines.host import EngineError
from ..utils.locks import directory_lock


def world_path(project, level_id, backend='windows', config_path=None):
    if backend == 'macos-arm64':
        return Path(config_path).parent/'data/minecraftWorlds'/level_id
    from ..mcstudio.mcs import get_mcs_game_engine_data_path
    root = get_mcs_game_engine_data_path()
    if not root:
        appdata = os.environ.get('APPDATA')
        if not appdata:
            raise EngineError('无法定位游戏世界目录：缺少 APPDATA。', 'setup_required')
        root = Path(appdata)/'MinecraftPE_Netease'
    return Path(root)/'minecraftWorlds'/level_id


def record_path(project, level_id):
    if (not isinstance(level_id, str) or not level_id or len(level_id) > 128 or
            level_id in ('.', '..') or level_id.rstrip(' .') != level_id or
            any(c in level_id for c in '\\/:\x00')):
        raise ValueError('无效的世界 ID')
    return Path(project)/'.runtime/instances'/(level_id + '.json')


def list_instances(project):
    result = []
    root = Path(project)/'.runtime'
    paths = {path.stem: path for path in root.glob('*.cppconfig')}
    for meta in (root/'instances').glob('*.json'):
        paths.setdefault(meta.stem, root/(meta.stem + '.cppconfig'))
    for level_id, path in paths.items():
        try:
            meta = storage.read(record_path(project, level_id), {})
            if meta.get('backend') == 'macos-arm64':
                continue
            config = storage.read(path, {})
            info = config.get('world_info') or {}
            if info.get('level_id', level_id) != level_id:
                continue
            try:
                saved = (world_path(project, level_id)/'level.dat').is_file()
            except EngineError:
                saved = False
            state = ('ready' if meta.get('last_ready_at') else 'legacy_existing'
                     if saved and (not meta or meta.get('previously_existing')) else meta.get('state', 'unverified'))
            created = meta.get('created_at') or (path.stat().st_ctime if path.exists() else 0)
            result.append({'level_id': level_id, 'name': info.get('name', meta.get('name', '开发测试')),
                           'config_path': str(path), 'creation_time': created, 'state': state,
                           'last_ready_at': meta.get('last_ready_at'), 'last_session': meta.get('last_session')})
        except (OSError, ValueError, TypeError):
            continue
    return sorted(result, key=lambda x: x['creation_time'], reverse=True)


def match(items, prefix):
    matches = [item for item in items if item['level_id'].startswith(prefix)]
    if len(matches) != 1:
        raise EngineError('实例 ID 前缀不存在或不唯一：' + prefix, 'instance_not_found')
    return matches[0]


def select(project, *, new=False, prefix=None, name='开发测试'):
    items = list_instances(project)
    if prefix:
        return match(items, prefix)
    if not new:
        available = [item for item in items if item['state'] in ('ready', 'legacy_existing')]
        if available:
            return available[0]
        if items:
            raise EngineError('没有成功进入过世界的可用实例。', 'instance_not_ready',
                              '使用 run ' + items[0]['level_id'] + ' 显式重试，或 --new 新建世界。', instances=items)
    identity = str(uuid.uuid4())
    return {'level_id': identity, 'name': name, 'creation_time': time.time(), 'state': 'pending',
            'config_path': str(Path(project)/'.runtime'/(identity + '.cppconfig'))}


def attempt(project, item, session, settings=None):
    path = record_path(project, item['level_id'])
    previous = storage.read(path, {})
    if item.get('state') == 'legacy_existing':
        previous['previously_existing'] = True
    previous.update(schema_version=1, level_id=item['level_id'], name=item['name'],
                    created_at=previous.get('created_at', item['creation_time']),
                    state='pending', last_session=session, backend=item.get('backend', 'windows'))
    if settings is not None:
        previous['creation_settings'] = settings
    storage.write(path, previous)


def mark(data, ready=False):
    if data.get('mode') != 'local' or not data.get('level_id'):
        return
    path = record_path(data['project'], data['level_id'])
    record = storage.read(path, {'schema_version': 1, 'level_id': data['level_id'],
                                'created_at': data['created_at']})
    if record.get('last_session') not in (None, data['session']):
        return
    record.update(last_session=data['session'], state='ready' if ready else 'failed', backend=data.get('backend', 'windows'))
    if ready:
        record['last_ready_at'] = time.time()
    storage.write(path, record)


def delete(project, items):
    for item in items:
        occupancy.require_idle([data for data in occupancy.active(project) if data.get('level_id') == item['level_id']],
                               '世界正在运行，请先停止。')
        world = world_path(project, item['level_id'])
        with world_lock(world):
            if world.is_symlink() or getattr(world, 'is_junction', lambda: False)():
                raise EngineError('世界目录是链接，拒绝递归删除。', 'instance_invalid')
            if world.exists():
                shutil.rmtree(world)
            Path(item['config_path']).unlink(missing_ok=True)
            record_path(project, item['level_id']).unlink(missing_ok=True)
    return {'deleted': [item['level_id'] for item in items]}


def world_lock(world, session=None):
    import hashlib
    world = Path(world).resolve()
    key = hashlib.sha256(occupancy.path_key(world).encode()).hexdigest()
    directory = world.parent/'.mcpy-world-locks'/key
    return occupancy.session_lease(directory, world, session, '世界', 'world_in_use')

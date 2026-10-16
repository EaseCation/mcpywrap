"""A group's player keeps its own anonymous identity and client preferences."""
from pathlib import Path
import json
import os
import subprocess
import sys

from . import storage, occupancy
from ..engines.host import EngineError


ROLES = ('host', 'guest', 'client1', 'client2')
FOLDER_PROBE = '''import ctypes, json
shell = ctypes.WinDLL('shell32')
result = {}
for name, folder in (('APPDATA', 26), ('LOCALAPPDATA', 28)):
    value = ctypes.create_unicode_buffer(32768)
    status = shell.SHGetFolderPathW(None, folder | 0x4000, None, 0, value)
    if status != 0:
        raise OSError('Known folder lookup failed: ' + str(status))
    result[name] = value.value
print(json.dumps(result))
'''


def directory(project, group, role):
    if role not in ROLES:
        raise EngineError('未知的联调成员角色。', 'invalid_role')
    return Path(project).resolve()/'.runtime/groups'/storage.identifier(group)/'profiles'/role


class PlayerProfile:
    def __init__(self, data):
        self.data = data
        self.project = Path(data['project']).resolve()
        self.root = directory(self.project, data['group'], data['role'])
        self.owner = {'project': str(self.project), 'group': data['group'], 'role': data['role']}
        for path in (self.root, *self.root.parents):
            if path == self.project:
                break
            if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
                raise EngineError('客户端资料目录已被替换为链接。', 'profile_modified')

    def lease(self):
        directory = self.root.with_name(self.root.name+'.lease')
        if directory.is_symlink() or getattr(directory, 'is_junction', lambda: False)():
            raise EngineError('客户端占用记录指向了外部目录。', 'profile_modified')
        return occupancy.session_lease(directory, self.root,
                                       self.data, '客户端资料', 'profile_in_use')

    def prepare(self):
        group = storage.read(self.root.parent.parent/'group.json', {})
        if not any(m.get('role') == self.data['role'] and m.get('session') == self.data['session']
                   for m in group.get('members', ())):
            raise EngineError('联调成员已变更，取消旧会话启动。', 'group_changed')
        receipt = self.root/'owner.json'
        owner = storage.read(receipt)
        if owner != self.owner and (owner is not None or (self.root.exists() and any(self.root.iterdir()))):
            raise EngineError('客户端资料目录归属不明，已保留原内容。', 'profile_conflict')
        self.root.mkdir(parents=True, exist_ok=True)
        if owner is None:
            storage.write(receipt, self.owner)
        self.data['network']['profile'] = str(self.root)

    def windows_environment(self):
        roaming, local = self.root/'AppData/Roaming', self.root/'AppData/Local'
        for path in (roaming, local):
            if not path.resolve().is_relative_to(self.root.resolve()):
                raise EngineError('客户端系统目录指向了外部位置。', 'profile_modified')
            path.mkdir(parents=True, exist_ok=True)
        environment = dict(os.environ, USERPROFILE=str(self.root), APPDATA=str(roaming), LOCALAPPDATA=str(local))
        from ..mcstudio.processes import background_options
        try:
            probe = subprocess.run([sys.executable, '-c', FOLDER_PROBE], env=environment,
                                   capture_output=True, text=True, timeout=30, check=True, **background_options())
            folders = json.loads(probe.stdout)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            diagnostic = self.root/'profile-probe.log'
            diagnostic.write_text(str(getattr(error, 'stderr', None) or error), encoding='utf-8')
            raise EngineError('无法核实 Windows 客户端目录隔离，未启动游戏。', 'profile_unavailable',
                              '请检查诊断日志后重试：' + str(diagnostic)) from error
        if any(occupancy.path_key(folders.get(key, '')) != occupancy.path_key(environment[key])
               for key in ('APPDATA', 'LOCALAPPDATA')):
            raise EngineError('此 Windows 目录设置不支持独立客户端资料，未启动游戏。', 'profile_unavailable',
                              '单客户端仍可使用；请检查系统的 AppData 重定向设置。')
        # Seed only presentation/input preferences, never account or device IDs.
        from ..engines.preferences import game_preference, read_properties, write_properties
        target = roaming/'MinecraftPE_Netease/minecraftpe/options.txt'
        if not target.parent.resolve().is_relative_to(self.root.resolve()):
            raise EngineError('客户端游戏目录指向了外部位置。', 'profile_modified')
        if not target.exists() and os.environ.get('APPDATA'):
            source = Path(os.environ['APPDATA'])/'MinecraftPE_Netease/minecraftpe/options.txt'
            values = read_properties(source, ':') or {}
            preferences = {key: value for key, value in values.items() if game_preference(key)}
            if preferences:
                write_properties(target, preferences, ':')
        if self.data['network'].get('join') == 'manual':
            self.prepare_pack_cache(target.parent.parent, self.data['network']['deployment_fingerprint'])
            values = read_properties(target, ':') or {}
            values['mp_username'] = self.data['network']['player']['user_name']
            write_properties(target, values, ':')
        return environment

    def prepare_pack_cache(self, game_root, fingerprint):
        """Invalidate only this role's received packs when its host changes."""
        import re
        import shutil
        if storage.read(self.root/'owner.json') != self.owner:
            raise EngineError('客户端资料目录归属未确认，未更新缓存。', 'profile_conflict')
        if not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
            raise EngineError('无法确认主机部署版本，未启动客机。', 'deployment_unavailable')
        cache = Path(game_root)/'packcache'
        if (not cache.resolve().is_relative_to(self.root.resolve()) or cache.is_symlink() or
                getattr(cache, 'is_junction', lambda: False)()):
            raise EngineError('客机包缓存指向了外部目录，已保留原内容。', 'profile_modified')
        receipt = self.root/'received-packs.json'
        try:
            previous = storage.read(receipt)
        except ValueError:
            previous = None  # Derived cache metadata can be rebuilt from the host.
        if isinstance(previous, dict) and previous.get('fingerprint') == fingerprint:
            return
        if cache.exists():
            if not cache.is_dir():
                raise EngineError('客机包缓存不是目录，已保留原内容。', 'profile_modified')
            # This is the engine's reproducible download cache under an owned,
            # exclusively leased role profile, not source, identity or world data.
            shutil.rmtree(cache)
        storage.write(receipt, {'fingerprint': fingerprint})

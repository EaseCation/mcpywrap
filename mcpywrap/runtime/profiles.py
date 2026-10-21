"""A group's player keeps its own anonymous identity and client preferences."""
from pathlib import Path
from ..utils.paths import is_link
import json
import hashlib
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
            if is_link(path):
                raise EngineError('客户端资料目录已被替换为链接。', 'profile_modified')

    def lease(self):
        directory = self.root.with_name(self.root.name+'.lease')
        if is_link(directory):
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
        profile = self.windows_directory()
        roaming, local = profile/'AppData/Roaming', profile/'AppData/Local'
        for path in (roaming, local):
            if not path.resolve().is_relative_to(profile.resolve()):
                raise EngineError('客户端系统目录指向了外部位置。', 'profile_modified')
            path.mkdir(parents=True, exist_ok=True)
        environment = dict(os.environ, USERPROFILE=str(profile), APPDATA=str(roaming), LOCALAPPDATA=str(local))
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
        if not target.parent.resolve().is_relative_to(profile.resolve()):
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

    def windows_directory(self):
        """Keep real Windows profiles at the depth expected by ModPC 3.9.

        The received-pack loader strips eight path components. Known folders
        follow USERPROFILE, and the engine resolves junctions, so the profile
        itself must be a real drive:/mcpy-profiles/<id> directory. Project-local
        ownership/leases stay authoritative; previous data is copied once and
        retained as a backup. No engine or Addon import hooks are changed.
        """
        import shutil
        from ..source_files import long_path
        parent = Path(self.project.anchor)/'mcpy-profiles'
        if not self.project.drive or str(parent).startswith('\\\\') or is_link(parent):
            raise EngineError('客机需要本地磁盘上的独立资料目录。', 'profile_unavailable')
        key = occupancy.path_key(self.root) + '\n' + os.environ.get('USERPROFILE', '')
        target = parent/hashlib.sha256(key.encode('utf-8')).hexdigest()[:32]
        receipt = self.root/'windows-profile.json'
        expected = {'path': str(target), 'owner': self.owner}
        previous = storage.read(receipt)
        if previous is not None and (not isinstance(previous, dict) or
                any(previous.get(k) != v for k, v in expected.items())):
            raise EngineError('客机资料路径记录已变化，已保留原内容。', 'profile_modified')
        marker = target/'.mcpy-owner.json'
        if os.path.lexists(target):
            if (previous is None or is_link(target) or not target.is_dir() or
                    is_link(marker) or storage.read(marker) != self.owner):
                raise EngineError('客机资料目录归属不明：' + str(target), 'profile_conflict')
        else:
            if previous is not None and previous.get('ready'):
                raise EngineError('已迁移的客机资料目录缺失，未回退到旧副本。', 'recovery_required')
            staging = target.with_name(target.name + '.preparing')
            if os.path.lexists(staging):
                raise EngineError('上次客机资料迁移尚未完成：' + str(staging), 'recovery_required',
                                  '保留原目录和迁移现场，请核对后恢复；不会覆盖或删除。')
            legacy = self.root/'AppData'
            if is_link(legacy) or any(is_link(p) for p in long_path(legacy).rglob('*')):
                raise EngineError('原客机资料含目录链接，未复制。', 'profile_modified')
            storage.write(receipt, expected)
            staging.mkdir(parents=True)
            if legacy.exists():
                shutil.copytree(long_path(legacy), long_path(staging/'AppData'))
            storage.write(staging/'.mcpy-owner.json', self.owner)
            staging.rename(target)
        storage.write(receipt, dict(expected, ready=True))
        self._windows_root = target
        self.data['network']['windows_profile'] = str(target)
        return target

    def prepare_pack_cache(self, game_root, fingerprint):
        """Invalidate only this role's received packs when its host changes."""
        import re
        import shutil
        if storage.read(self.root/'owner.json') != self.owner:
            raise EngineError('客户端资料目录归属未确认，未更新缓存。', 'profile_conflict')
        if not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
            raise EngineError('无法确认主机部署版本，未启动客机。', 'deployment_unavailable')
        cache = Path(game_root)/'packcache'
        roots = [self.root.resolve()]
        windows = getattr(self, '_windows_root', None)
        if windows is not None and storage.read(windows/'.mcpy-owner.json') == self.owner:
            roots.append(windows.resolve())
        if not any(cache.resolve().is_relative_to(root) for root in roots) or is_link(cache):
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

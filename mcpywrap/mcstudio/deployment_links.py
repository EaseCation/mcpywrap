"""Owned global links. Changes are journaled; real directories are never removed."""
from pathlib import Path
import hashlib
import os

from ..runtime import storage, occupancy
from ..engines.host import EngineError
from ..utils.locks import directory_lock
from ..utils.paths import is_link
from .symlinks import _create_directory_link


def unlink(path):
    if not is_link(path):
        raise EngineError('拒绝删除不是链接的目录：' + str(path), 'link_modified')
    if Path(path).is_symlink():
        Path(path).unlink()
    else:
        os.rmdir(path)


def pack_uuid(path):
    for filename in ('manifest.json', 'pack_manifest.json'):
        file = Path(path)/filename
        if file.is_file():
            import json
            import uuid
            try:
                return str(uuid.UUID(json.loads(file.read_text(encoding='utf-8-sig'))['header']['uuid']))
            except (ValueError, KeyError, TypeError) as exc:
                raise EngineError('无效的运行包 manifest：' + str(file), 'invalid_manifest') from exc
    return None


class ManagedLinks:
    def __init__(self, root, project):
        self.root = Path(root).resolve()
        self.project = str(Path(project).resolve())
        self.store = self.root/'.mcpywrap'
        self.path = self.store/'links.json'
        self.journal_path = self.store/'links.transaction.json'

    def lock(self):
        return directory_lock(self.store, reentrant=True)

    def _validate(self, key, entry):
        parts = Path(key).parts
        if len(parts) != 2 or parts[0] not in ('behavior_packs', 'resource_packs') or parts[1] in ('.', '..'):
            raise EngineError('全局链接登记路径无效。', 'recovery_required')
        path = self.root/key
        if not is_link(path) or occupancy.path_key(path) != occupancy.path_key(entry['source']):
            raise EngineError('全局包链接已被外部修改：' + str(path), 'link_modified',
                              '请检查其他开发工具是否重新部署了全局包；不会覆盖未知内容。')

    def _legacy(self, kind, path):
        if not is_link(path):
            return False
        source = Path(path).resolve()
        try:
            source.relative_to(Path(self.project))
        except ValueError:
            return False
        for config in (Path(self.project)/'.runtime').glob('*.cppconfig'):
            try:
                data = storage.read(config, {})
            except (OSError, ValueError):
                continue  # An unrelated failed instance is not ownership evidence.
            info = data.get('world_info') if isinstance(data, dict) else None
            if not isinstance(info, dict):
                continue
            references = info.get(kind + '_packs')
            if isinstance(references, list) and path.name in references:
                return True
        return False

    def publish(self, packs, deployment, session=None, transaction=None):
        with self.lock():
            self.recover()
            registry = storage.read(self.path, {'schema_version': 1, 'links': {}})
            old = registry['links']
            desired, result = {}, {'behavior': [], 'resource': []}
            prefix = hashlib.sha256(occupancy.path_key(self.project).encode()).hexdigest()[:12]
            for pack in packs:
                for kind in result:
                    source = getattr(pack, kind + '_pack_dir', None)
                    if not source or not Path(source).is_dir():
                        continue
                    identity = pack_uuid(source)
                    if not identity:
                        continue
                    name = 'mcpy_' + prefix + '_' + kind + '_' + identity.replace('-', '')
                    key = kind + '_packs/' + name
                    desired[key] = {'project': self.project, 'source': str(Path(source).resolve()),
                                    'uuid': identity, 'deployment': deployment}
                    result[kind].append(name)
            remove = {key: value for key, value in old.items()
                      if occupancy.path_key(value['project']) == occupancy.path_key(self.project) and key not in desired}
            for key, entry in old.items():
                if key in desired and occupancy.path_key(entry['project']) != occupancy.path_key(self.project):
                    raise EngineError('全局包 UUID 已由其他项目登记：' + entry['uuid'], 'pack_conflict',
                                      '保留其他项目的运行包；请检查重复 UUID 的来源。', conflict=str(self.root/key))
                if key in desired or key in remove:
                    self._validate(key, entry)
            # Validate all UUID/name conflicts before the first mutation.
            for key, entry in desired.items():
                kind_dir = (self.root/key).parent
                target = self.root/key
                if os.path.lexists(target) and key not in old:
                    raise EngineError('运行链接名称被未登记内容占用：' + str(target), 'link_conflict')
                for existing in kind_dir.iterdir() if kind_dir.exists() else ():
                    existing_key = existing.relative_to(self.root).as_posix()
                    if existing_key == key or not existing.is_dir():
                        continue
                    if pack_uuid(existing) != entry['uuid']:
                        continue
                    if existing_key in remove:
                        continue
                    if self._legacy(kind_dir.name.removesuffix('_packs'), existing):
                        occupancy.require_idle(occupancy.active(self.project, exclude=(session,) if session else ()), '旧源码链接仍被会话使用。')
                        remove[existing_key] = {'project': self.project, 'source': str(existing.resolve()),
                                                'uuid': entry['uuid'], 'deployment': None}
                    else:
                        raise EngineError('全局包 UUID 冲突：' + entry['uuid'], 'pack_conflict',
                                          '保留其他项目或手动安装的包；请检查重复包的来源。',
                                          source=entry['source'], conflict=str(existing))
            changes = []
            for key, entry in remove.items():
                changes.append({'key': key, 'old': entry, 'new': None})
            for key, entry in desired.items():
                if key not in old or occupancy.path_key(old[key]['source']) != occupancy.path_key(entry['source']):
                    changes.append({'key': key, 'old': old.get(key), 'new': entry})
            if any(change['old'] for change in changes):
                occupancy.require_idle(occupancy.active(self.project, exclude=(session,) if session else ()),
                                       '运行链接需要更新，请先停止本项目的其他会话。')
            journal = {'id': transaction, 'project': self.project, 'previous': registry,
                       'changes': changes, 'applied': [], 'registry_keys': sorted(set(remove) | set(desired)),
                       'published': desired}
            from .processes import identity
            journal['owner'] = identity(os.getpid())
            storage.write(self.journal_path, journal)
            try:
                for change in changes:
                    journal['applied'].append(change)
                    storage.write(self.journal_path, journal)
                    path = self.root/change['key']
                    if change['old']:
                        self._validate(change['key'], change['old']); unlink(path)
                    if change['new']:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        _create_directory_link(change['new']['source'], str(path))
                links = dict(old)
                for key in remove:
                    links.pop(key, None)
                links.update(desired)
                storage.write(self.path, {'schema_version': 1, 'links': links})
                # The caller keeps the preimage in its deployment journal.
                if transaction is None:
                    self.journal_path.unlink(missing_ok=True)
                return result, journal
            except BaseException:
                self.restore(journal)
                raise

    def recover(self):
        journal = storage.read(self.journal_path)
        if journal:
            if occupancy.live({'worker': journal['owner']}):
                raise EngineError('另一个操作正在修改全局包链接。', 'busy')
            self.restore(journal)

    def finish(self, transaction):
        with self.lock():
            journal = storage.read(self.journal_path)
            if journal and journal.get('id') != transaction:
                raise EngineError('链接事务归属发生变化。', 'recovery_required')
            self.journal_path.unlink(missing_ok=True)

    def restore(self, journal):
        with self.lock():
            current = storage.read(self.path, {'schema_version': 1, 'links': {}})
            keys = journal.get('registry_keys', [change['key'] for change in journal['changes']])
            if 'published' in journal:
                for key in keys:
                    entry = current['links'].get(key)
                    if entry not in (journal['previous']['links'].get(key), journal['published'].get(key)):
                        raise EngineError('链接归属在启动后发生变化，已保留现场：' + key, 'recovery_required')
            for change in reversed(journal['applied']):
                path = self.root/change['key']
                already_restored = False
                if os.path.lexists(path):
                    if not is_link(path):
                        raise EngineError('恢复时链接已被其他程序改写：' + str(path), 'recovery_required')
                    actual = occupancy.path_key(path)
                    if change['old'] and actual == occupancy.path_key(change['old']['source']):
                        already_restored = True
                    elif change['new'] and actual == occupancy.path_key(change['new']['source']):
                        unlink(path)
                    else:
                        raise EngineError('恢复时链接目标发生变化：' + str(path), 'recovery_required')
                if change['old'] and not already_restored:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    _create_directory_link(change['old']['source'], str(path))
            # Preserve registrations made by other projects after publication.
            for key in keys:
                prior = journal['previous']['links'].get(key)
                if prior is None:
                    current['links'].pop(key, None)
                else:
                    current['links'][key] = prior
            storage.write(self.path, current)
            self.journal_path.unlink(missing_ok=True)

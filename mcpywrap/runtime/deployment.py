"""One assembly input and recoverable publication for local development sessions."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import hashlib
import json
import os
import shutil
import uuid

from . import storage, occupancy
from ..builders.AddonsPack import AddonsPack
from ..builders.assembly import pack_files
from ..builders.project_builder import AddonProjectBuilder, _replace_with_retry
from ..dependencies import DependencyService, read_project
from ..engines.host import EngineError
from ..utils.locks import directory_lock
from ..utils.paths import is_link

_writing = ContextVar('deployment_writes', default=())


@contextmanager
def writing(target):
    token = _writing.set(_writing.get() + (occupancy.path_key(target),))
    try:
        yield
    finally:
        _writing.reset(token)


def check_build_target(project, target):
    target = Path(target).resolve()
    if occupancy.path_key(target) in _writing.get():
        return
    for ancestor in (target, *target.parents):
        if ancestor.name == '.runtime' or (ancestor.name == 'runtime' and ancestor.parent.name == '.mcpy'):
            raise EngineError('构建输出属于运行目录，请通过 run 或 runtime reload/watch 更新。', 'managed_output')
    for reserved in (Path(project)/'.mcpy/runtime', Path(project)/'.runtime'):
        try:
            target.relative_to(reserved.resolve())
        except ValueError:
            continue
        raise EngineError('构建输出属于运行目录，请通过 run 或 runtime reload/watch 更新。', 'managed_output')


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def reference(record):
    return {key: record[key] for key in ('id', 'path', 'fingerprint', 'structure')}


def inventory(root):
    """Record file bytes and empty directories; ignore only reproducible Python caches."""
    root = Path(root)
    if is_link(root):
        raise EngineError('运行产物根目录已被替换为链接：' + str(root), 'deployment_modified')
    result = {}
    if not root.is_dir():
        return result
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != '__pycache__')
        for name in dirs:
            path = Path(current)/name
            if is_link(path):
                raise EngineError('运行产物中出现目录链接：' + str(path), 'deployment_modified')
            result[path.relative_to(root).as_posix() + '/'] = 'directory'
        for name in sorted(files):
            if Path(name).suffix.lower() in ('.pyc', '.pyo'):
                continue
            path = Path(current)/name
            if path.is_symlink():
                raise EngineError('运行产物中出现文件链接：' + str(path), 'deployment_modified')
            result[path.relative_to(root).as_posix()] = file_digest(path)
    return result


def _dependency_declarations(project):
    config = read_project(project)
    settings = config.get('tool', {}).get('mcpywrap', {})
    declarations = {key: settings.get(key) for key in
                    ('project_type', 'local_dependencies', 'git_dependencies', 'code_libraries')}
    declarations['packages'] = config.get('project', {}).get('dependencies', [])
    return declarations


def source_fingerprint(builder):
    sources, manifests = [], []
    for pack in builder.packs:
        for kind in ('behavior', 'resource'):
            folder = getattr(pack, kind + '_pack_dir')
            if folder and Path(folder).is_dir():
                for current, dirs, _ in os.walk(folder):
                    dirs[:] = sorted(d for d in dirs if not pack.should_exclude(str(Path(current)/d)))
                    sources.append((occupancy.path_key(pack.path), kind,
                                    Path(current).relative_to(folder).as_posix() + '/', 'directory'))
            for relative in sorted(set(pack_files(pack, kind))):
                from ..code_libraries import library_source
                path = library_source(pack, kind, relative) or Path(folder)/relative
                digest = file_digest(path)
                item = (occupancy.path_key(pack.path), kind, relative, digest)
                sources.append(item)
                if relative in ('manifest.json', 'pack_manifest.json'):
                    manifests.append(item)
    projects = {occupancy.path_key(p.path): p.path for p in builder.packs}
    projects[occupancy.path_key(builder.source_dir)] = builder.source_dir
    declarations = [(key, _dependency_declarations(project)) for key, project in sorted(projects.items())
                    if (Path(project)/'pyproject.toml').is_file()]
    layouts = [(occupancy.path_key(p.path), p.behavior_pack_dir, p.resource_pack_dir,
                [(str(lib.get('source')), lib.get('target')) for lib in getattr(p, 'code_libraries', [])])
               for p in builder.packs]
    structure = _digest([declarations, layouts, manifests])
    return _digest([structure, sources]), structure


def metadata_path(project, target):
    key = _digest(occupancy.path_key(target))[:24]
    return Path(project)/'.runtime/deployments'/(key + '.json')


def readers(project, target, exclude=()):
    found = []
    for data in occupancy.active(project, exclude=exclude):
        deployed = data.get('deployment')
        if deployed:
            selected = deployed['path']
        elif data.get('mode', 'local') == 'local':
            selected = (Path(data['config_path']).parent/'assembled' if data.get('backend') == 'macos-arm64'
                        else Path(project)/'.mcpy/runtime/assembled')
        else:
            continue
        if occupancy.path_key(selected) == occupancy.path_key(target):
            found.append(data)
    return found


def runtime_builder(project, target, resolved=None):
    if read_project(project).get('tool', {}).get('mcpywrap', {}).get('project_type', 'addon') == 'map':
        from .preparation import MapRuntimeBuilder
        return MapRuntimeBuilder(project, target, resolved=resolved)
    return AddonProjectBuilder(project, target, resolved=resolved, stable_layout=True)


def matches_source(project, data):
    try:
        target = (data.get('deployment') or {}).get('path')
        if not target:
            target = (Path(data['config_path']).parent/'assembled' if data.get('backend') == 'macos-arm64'
                      else Path(project)/'.mcpy/runtime/assembled')
        builder = runtime_builder(project, target)
        builder.initialize()
        record = storage.read(metadata_path(project, target), {})
        return source_fingerprint(builder)[0] == record.get('fingerprint')
    except (OSError, ValueError):
        return False


class Deployment:
    """Caller holds the deployment lock until publication and process identity handoff."""
    def __init__(self, project, target=None):
        self.project = Path(project).resolve()
        # Keep the requested path until ownership has been checked. Resolving
        # first would hide a replacement junction and authorize its destination.
        self.target = Path(os.path.abspath(target or self.project/'.mcpy/runtime/assembled'))
        self._validate_target()
        self.record_path = metadata_path(self.project, self.target)
        self.lock_path = self.record_path.with_suffix('.lock')
        self.journal_path = self.record_path.with_suffix('.transaction.json')
        self.journal = None

    def _validate_target(self):
        roots = (self.project/'.mcpy/runtime', self.project/'.runtime')
        if not any(self.target.is_relative_to(root) and self.target != root for root in roots):
            raise EngineError('部署目标不属于当前项目的运行目录。', 'invalid_deployment_target')
        for path in (self.target, *self.target.parents):
            if path == self.project:
                break
            if is_link(path):
                raise EngineError('运行目录已被替换为链接：' + str(path), 'deployment_modified')

    def lock(self):
        return directory_lock(self.lock_path)

    def _save_journal(self):
        storage.write(self.journal_path, self.journal)

    def recover(self):
        self._validate_target()
        journal = storage.read(self.journal_path)
        if journal is None:
            return
        if (Path(journal['directory']).resolve().parent != (self.project/'.runtime/transactions').resolve()
                or occupancy.path_key(journal['target']) != occupancy.path_key(self.target)):
            raise EngineError('恢复记录不属于当前项目或运行目录。', 'recovery_required')
        owner = journal.get('owner')
        process = journal.get('game')
        if process and occupancy.live({'game': process}):
            raise EngineError('上次启动的游戏仍在使用此部署。', 'deployment_in_use')
        if owner and occupancy.live({'worker': owner}):
            raise EngineError('此部署正在准备或等待世界就绪。', 'busy')
        if journal['phase'] == 'spawning' and not process:
            raise EngineError('上次启动在记录游戏身份前中断，请核对游戏进程后恢复。', 'recovery_required')
        # Only adopt a transaction after proving recovery is allowed. A caller's
        # exception cleanup must never roll back a transaction we just rejected.
        self.journal = journal
        if self.journal['phase'] == 'committed':
            self._cleanup()
        else:
            self.rollback()

    def preflight(self):
        self.recover()
        previous = storage.read(self.record_path)
        if previous and inventory(self.target) != previous['files']:
            raise EngineError('运行包已被外部程序改写，已保留现场。', 'deployment_modified',
                              '退出相关游戏并检查运行目录。', path=str(self.target))

    def prepare(self, session=None, allowed_sessions=()):
        self.preflight()
        manager = DependencyService(self.project).resolve()
        self.warnings = list(manager.warnings)
        self.builder = runtime_builder(self.project, self.target, resolved=manager)
        self.builder.initialize()
        fingerprint, structure = source_fingerprint(self.builder)
        previous = storage.read(self.record_path)
        using = readers(self.project, self.target, exclude=(session,) if session else ())
        if previous and inventory(self.target) != previous['files']:
            raise EngineError('运行包已被外部程序改写，已保留现场。', 'deployment_modified',
                              '退出相关游戏并检查运行目录；不要清理其他项目的包。', path=str(self.target))
        if previous and previous['fingerprint'] == fingerprint:
            self.record = previous
            return self.builder.target_addon
        unauthorized = [data for data in using if data['session'] not in allowed_sessions]
        occupancy.require_idle(unauthorized)
        if using and (not previous or previous['structure'] != structure):
            raise EngineError('依赖、包标识或目录结构发生变化，请重新运行。', 'restart_required')
        if is_link(self.target):
            raise EngineError('运行输出不能是目录链接。', 'deployment_modified')
        transaction = uuid.uuid4().hex
        directory = self.project/'.runtime/transactions'/transaction
        directory.mkdir(parents=True)
        stage = directory/'output'
        with writing(stage):
            builder = runtime_builder(self.project, stage, resolved=manager)
            ok, error = builder.build()
        if not ok:
            shutil.rmtree(directory)
            raise EngineError(error, 'build_failed')
        if source_fingerprint(self.builder) != (fingerprint, structure):
            shutil.rmtree(directory)
            raise EngineError('装配期间源码发生变化，请重试。', 'source_changed')
        files = inventory(stage)
        if using:
            before_types = {name.rstrip('/'): name.endswith('/') for name in previous['files']}
            after_types = {name.rstrip('/'): name.endswith('/') for name in files}
            if any(before_types[name] != after_types[name] for name in before_types.keys() & after_types.keys()):
                shutil.rmtree(directory)
                raise EngineError('运行包中的文件与目录类型发生变化，请先停止相关实例再运行。', 'restart_required')
        self.record = {'schema_version': 1, 'id': transaction, 'project': str(self.project),
                       'path': str(self.target), 'fingerprint': fingerprint,
                       'structure': structure, 'files': files}
        from ..mcstudio.processes import identity
        self.journal = {'id': transaction, 'directory': str(directory), 'target': str(self.target),
                        'previous': previous, 'phase': 'prepared', 'game': None,
                        'owner': identity(os.getpid()), 'incremental': bool(using),
                        'had_target': self.target.exists(), 'applied': [], 'configs': [],
                        'published_files': files}
        self._save_journal()
        try:
            self.target.parent.mkdir(parents=True, exist_ok=True)
            if using:
                self._publish_files(stage, directory/'previous', previous['files'], files)
            else:
                self.journal['phase'] = 'replacing'; self._save_journal()
                if self.target.exists():
                    _replace_with_retry(self.target, directory/'previous')
                _replace_with_retry(stage, self.target)
            storage.write(self.record_path, self.record)
            self.journal['phase'] = 'published'; self._save_journal()
        except BaseException:
            self.rollback()
            raise
        return self.builder.target_addon

    def _publish_files(self, stage, backup, old, new):
        for name in sorted(set(old) | set(new)):
            if name.endswith('/') or old.get(name) == new.get(name):
                continue
            dest = self.target/name
            prior = backup/name
            if dest.exists():
                prior.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, prior)
            self.journal['applied'].append(name); self._save_journal()
            if name in new:
                dest.parent.mkdir(parents=True, exist_ok=True)
                _replace_with_retry(stage/name, dest)
            else:
                dest.unlink(missing_ok=True)
        for name in sorted(new):
            if name.endswith('/'):
                (self.target/name).mkdir(parents=True, exist_ok=True)
        for name in sorted(set(old)-set(new), reverse=True):
            if name.endswith('/'):
                try:
                    (self.target/name).rmdir()
                except OSError:
                    pass

    def preserve_config(self, path):
        if self.journal is None:
            return
        path = Path(path)
        old = path.read_text(encoding='utf-8') if path.exists() else None
        self.journal['configs'].append({'path': str(path), 'old': old})
        self._save_journal()

    def publish_config(self, path, config):
        self.preserve_config(path)
        if self.journal:
            self.journal['configs'][-1]['expected'] = config
            self._save_journal()
        from ..mcstudio.runtime_cppconfig import write_cppconfig
        write_cppconfig(path, config)

    def begin_launch(self):
        if self.journal is None:
            from ..mcstudio.processes import identity
            transaction = uuid.uuid4().hex
            directory = self.project/'.runtime/transactions'/transaction
            directory.mkdir(parents=True)
            self.journal = {'id': transaction, 'directory': str(directory), 'target': str(self.target),
                            'previous': self.record, 'phase': 'prepared', 'game': None,
                            'owner': identity(os.getpid()), 'incremental': False, 'unchanged': True,
                            'had_target': True, 'applied': [], 'configs': []}
            self._save_journal()

    def preserve_links(self, root, journal):
        if self.journal is not None:
            self.journal['links'] = {'root': str(root), 'journal': journal}
            self._save_journal()

    def publish_links(self, root, packs, session=None):
        from ..mcstudio.deployment_links import ManagedLinks
        links = ManagedLinks(root, self.project)
        self.journal['links'] = {'root': str(root), 'transaction': self.journal['id']}
        self._save_journal()
        result, journal = links.publish(packs, self.record['id'], session, transaction=self.journal['id'])
        self.journal['links']['journal'] = journal
        self._save_journal()
        links.finish(self.journal['id'])
        return result

    def spawning(self):
        if self.journal:
            self.journal['phase'] = 'spawning'; self._save_journal()

    def spawned(self, process):
        if self.journal:
            from ..mcstudio.processes import identity
            self.journal.update(phase='spawned', game=identity(process.pid)); self._save_journal()

    def commit(self):
        if self.journal:
            self.journal['phase'] = 'committed'; self._save_journal()
            self._cleanup()

    def _cleanup(self):
        if self.journal:
            directory = Path(self.journal['directory'])
            # Legacy output has no inventory. Preserve its recovery copy rather
            # than silently deleting unknown runtime-written files.
            if self.journal['previous'] is not None or not self.journal['had_target']:
                try:
                    shutil.rmtree(directory)
                except OSError:
                    from ..command_context import report_warning
                    report_warning('恢复副本暂未清理：' + str(directory))
            self.journal_path.unlink(missing_ok=True)
            self.journal = None

    def rollback(self, confirmed_exit=False):
        if self.journal is None:
            return
        self._validate_target()
        if not confirmed_exit and self.journal.get('game') and occupancy.live({'game': self.journal['game']}):
            raise EngineError('游戏尚未退出，保留部署和恢复记录。', 'recovery_required')
        # Check every shared preimage before restoring any part of the launch.
        # A later editor/tool write is not part of this transaction to undo.
        for config in self.journal['configs']:
            current = storage.read(config['path'])
            original = json.loads(config['old']) if config['old'] is not None else None
            if 'expected' in config and current not in (original, config['expected']):
                raise EngineError('实例配置在启动期间被修改，保留用户改动与恢复记录。',
                                  'recovery_required', path=config['path'])
        if self.journal['incremental']:
            expected = self.journal.get('published_files')
            if expected is None:
                raise EngineError('旧恢复记录缺少文件版本，无法安全覆盖当前运行包。', 'recovery_required')
            current = inventory(self.target)
            previous = self.journal['previous']['files']
            applied = set(self.journal['applied'])
            for name in current.keys() | previous.keys() | expected.keys():
                permitted = ((previous.get(name), expected.get(name)) if name in applied or name.endswith('/')
                             else (previous.get(name),))
                if current.get(name) not in permitted:
                    raise EngineError('运行文件在发布后被外部修改，保留改动与恢复记录。',
                                      'recovery_required', path=str(self.target/name))
        if self.journal.get('links'):
            from ..mcstudio.deployment_links import ManagedLinks
            links = self.journal['links']
            manager = ManagedLinks(links['root'], self.project)
            journal = links.get('journal')
            if journal is None:
                pending = storage.read(manager.journal_path)
                if pending and pending.get('id') == links.get('transaction'):
                    journal = pending
            if journal:
                manager.restore(journal)
        directory = Path(self.journal['directory'])
        backup = directory/'previous'
        if self.journal.get('unchanged'):
            pass
        elif self.journal['incremental']:
            for name in reversed(self.journal['applied']):
                dest, old = self.target/name, backup/name
                if old.is_file():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(old, dest)
                else:
                    dest.unlink(missing_ok=True)
            expected_dirs = {name for name in self.journal['previous']['files'] if name.endswith('/')}
            for name in sorted(inventory(self.target), reverse=True):
                if name.endswith('/') and name not in expected_dirs:
                    try:
                        (self.target/name).rmdir()
                    except OSError:
                        pass
            for name in expected_dirs:
                (self.target/name).mkdir(parents=True, exist_ok=True)
        elif backup.exists():
            if self.target.exists():
                _replace_with_retry(self.target, directory/('failed-' + uuid.uuid4().hex))
            _replace_with_retry(backup, self.target)
        elif not self.journal['had_target'] and self.target.exists():
            _replace_with_retry(self.target, directory/('failed-' + uuid.uuid4().hex))
        for config in reversed(self.journal['configs']):
            path = Path(config['path'])
            if config['old'] is None:
                path.unlink(missing_ok=True)
            else:
                storage.write(path, json.loads(config['old']))
        if self.journal['previous'] is None:
            self.record_path.unlink(missing_ok=True)
        else:
            storage.write(self.record_path, self.journal['previous'])
        self.journal_path.unlink(missing_ok=True)
        self.journal = None


def refresh(project, data, allowed_sessions=None):
    target = (data.get('deployment') or {}).get('path')
    if target is None and data.get('backend') == 'macos-arm64':
        target = Path(data['config_path']).parent/'assembled'
    deployment = Deployment(project, target)
    with deployment.lock():
        pack = deployment.prepare(allowed_sessions=allowed_sessions or (data['session'],))
        deployment.commit()
    return pack

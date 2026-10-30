"""将 Python 包与本地目录解析为统一的 Addon 依赖图。"""
import hashlib
import json
import re
from importlib import metadata
from ..host import distribution, marker_environment
from functools import cached_property
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

from packaging.requirements import Requirement, InvalidRequirement
from packaging.utils import canonicalize_name
from ..dependencies import (DependencyError, DependencyStatus, addon_directories, canonical_path,
                            declarations, read_project, resolve_path, validate_game_files)
from .AddonsPack import AddonsPack


def _decode_direct_url(direct_url_path):
    return _local_url(json.loads(Path(direct_url_path).read_text(encoding='utf-8')).get('url', ''))


def _local_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'file':
        return None
    path = url2pathname(parsed.path)
    if parsed.netloc and parsed.netloc != 'localhost':
        path = '//' + parsed.netloc + path
    return str(Path(path).resolve())


class DependencyNode:
    def __init__(self, name, addon_pack, parent=None, *, source=None):
        self.name, self.addon_pack, self.parent = name, addon_pack, parent
        self.children = []
        self.source = source or {'kind': 'local', 'path': str(Path(addon_pack.path).resolve())}

    @cached_property
    def source_root(self):
        if self.source['kind'] == 'git':
            from ..git_cache import read_snapshot
            return read_snapshot(self.source['git'], self.source['rev'], self.source.get('source_sha256'))
        return Path(self.addon_pack.path).resolve()

    @property
    def descriptor_root(self):
        root = self.source_root
        if self.source['kind'] == 'git':
            path = (root / self.source['subdir']).resolve()
            if not path.is_relative_to(root.resolve()):
                raise DependencyError('Git描述根越界')
            from ..source_files import long_path
            return long_path(path)
        return root

    def add_child(self, node):
        if node not in self.children:
            self.children.append(node)


class DependencyManager:
    def __init__(self):
        self.dependency_map = {}
        self.root_node = None
        self.warnings = []
        self.errors = []
        self.statuses = {}
        self._nodes, self._active, self._ordered = {}, [], []
        self._git_locks = {}
        self._git_sources = {}
        self.collect_errors = False
        self.has_git_projects = False
        self.purpose = "runtime"
        self.edges = []
        self.excluded = []

    def find_dependency_path(self, package_name):
        try:
            dist = distribution(Requirement(package_name).name)
        except (metadata.PackageNotFoundError, InvalidRequirement):
            return None
        direct = dist.read_text('direct_url.json')
        return _local_url(json.loads(direct).get('url', '')) if direct else None

    def build_dependency_tree(self, project_name, project_path, dependencies=None, *, config=None, allow_missing=False, git_lock=None, collect_errors=False, purpose="runtime"):
        self.__init__()
        from ..dependencies import validate_purpose
        self.purpose = validate_purpose(purpose)
        self.collect_errors = collect_errors
        project_path = str(Path(project_path).resolve())
        if git_lock is not None:
            self._git_locks[project_path] = git_lock
        config = read_project(project_path) if config is None else config
        if dependencies is not None:
            config.setdefault('project', {})['dependencies'] = dependencies
        root_id = re.sub(r'[^\w.-]', '_', project_name)[:60] + '_' + hashlib.sha256(canonical_path(project_path).encode('utf-8')).hexdigest()[:12]
        root = DependencyNode(project_name, AddonsPack(root_id, project_path, is_origin=True))
        folders = [root.addon_pack.behavior_pack_dir, root.addon_pack.resource_pack_dir]
        if config.get('tool', {}).get('mcpywrap', {}).get('project_type') == 'map':
            folders = [Path(project_path) / name for name in ('behavior_packs', 'resource_packs')]
        validate_game_files(project_path, folders)
        self.root_node = root
        key = canonical_path(project_path)
        self._nodes[key] = root
        self._active.append(key)
        self._process(root, config)
        self._active.pop()
        self.bundled_nodes = {id(root)}
        pending = [root]
        while pending:
            current = pending.pop()
            for owner, child, unbundled in self.edges:
                if owner is current and not unbundled and id(child) not in self.bundled_nodes:
                    self.bundled_nodes.add(id(child))
                    pending.append(child)
        for node in self._ordered:
            node.unbundled = id(node) not in self.bundled_nodes
            node.addon_pack.unbundled = node.unbundled
        self.dependency_map = {canonical_path(n.addon_pack.path): n.addon_pack for n in self._ordered}
        if self.errors and not (allow_missing or collect_errors):
            raise DependencyError('\n'.join(self.errors))
        return root

    def _process(self, parent, config):
        local_paths = set()
        for entry in declarations(config):
            source = parent.addon_pack.path
            if entry.unbundled and (parent is not self.root_node or self.purpose == 'release'):
                self.excluded.append({'source': str(source), 'dependency': entry.value, 'unbundled': True,
                                      'reason': 'unbundled' if parent is self.root_node else 'dependency_unbundled'})
                self._status(source, entry, 'excluded', 'unbundled 依赖不进入 build/package，也不向消费者传递')
                continue
            try:
                if entry.kind == 'local':
                    path = str(resolve_path(source, entry.value))
                    if canonical_path(path) in local_paths:
                        raise DependencyError('同一目录重复声明: ' + entry.value)
                    local_paths.add(canonical_path(path))
                    self._visit(parent, path, Path(path).name, unbundled=entry.unbundled)
                    self._status(source, entry, 'addon')
                    continue
                try:
                    requirement = Requirement(entry.value)
                except InvalidRequirement as exc:
                    raise DependencyError(f'无效的 Python 包声明: {entry.value}') from exc
                if requirement.marker and not requirement.marker.evaluate(environment=marker_environment()):
                    self._status(source, entry, 'inactive', '当前工具 Python 环境不满足环境标记，未启用；不代表游戏兼容性。')
                    continue
                try:
                    dist = distribution(requirement.name)
                except metadata.PackageNotFoundError:
                    self._missing(source, entry.value, '尚未安装')
                    continue
                if requirement.specifier and not requirement.specifier.contains(dist.version, prereleases=True):
                    self._missing(source, entry.value, f'已安装 {dist.version}，不满足版本约束')
                    continue
                path = self.find_dependency_path(entry.value)
                if not path:
                    self._development_only(source, entry)
                    continue
                direct = dist.read_text('direct_url.json')
                if not Path(path).is_dir() and direct and 'dir_info' in json.loads(direct):
                    self._missing(source, entry.value, f'安装来源目录不存在: {path}')
                    continue
                child_config = read_project(path)
                has_mcpy = 'mcpywrap' in child_config.get('tool', {})
                looks_like_addon = Path(path).is_dir() and any(
                    p.is_dir() and p.name.startswith(('behavior_pack', 'BehaviorPack', 'resource_pack', 'ResourcePack'))
                    for p in Path(path).iterdir())
                if has_mcpy or looks_like_addon:
                    self._visit(parent, path, canonicalize_name(requirement.name), source_kind='package')
                    self._status(source, entry, 'addon')
                else:
                    self._development_only(source, entry)
            except (DependencyError, OSError, ValueError) as exc:
                message = f'来源 {source}\n依赖 {entry.value!r}: {exc}'
                if not self.collect_errors:
                    raise DependencyError(message) from exc
                self.errors.append(message)
        from ..git_projects import resolve_projects, declarations as git_declarations
        for entry in git_declarations(parent.addon_pack.path, config):
            if entry.get('unbundled', False) and (parent is not self.root_node or self.purpose == 'release'):
                self.excluded.append({'source': str(parent.addon_pack.path), 'dependency': entry['name'], 'unbundled': True,
                                      'reason': 'unbundled' if parent is self.root_node else 'dependency_unbundled'})
        try:
            projects = resolve_projects(parent.addon_pack.path, config,
                                        self._git_locks.get(str(Path(parent.addon_pack.path).resolve())),
                                        source_records=self._git_sources, purpose=self.purpose if parent is self.root_node else "release")
            for entry, path, info in projects:
                self.has_git_projects = True
                self._visit(parent, str(path), entry['name'], unbundled=entry.get('unbundled', False))
        except (DependencyError, OSError, ValueError) as exc:
            if not self.collect_errors:
                raise
            self.errors.append(str(exc))

    def _missing(self, source, value, reason):
        from ..dependencies import DependencyDeclaration
        message = f'{source}: {value} {reason}；请显式执行 mcpy add "{value}"'
        self.errors.append(message)
        self.warnings.append(message)
        self._status(source, DependencyDeclaration('package', value), 'unavailable', message)

    def _status(self, source, entry, state, message=''):
        self.statuses[(canonical_path(source), entry.kind, entry.value)] = DependencyStatus(state, message)

    def status_for(self, source, entry):
        return self.statuses[(canonical_path(source), entry.kind, entry.value)]

    def _development_only(self, source, entry):
        message = (f'来源 {source}，依赖 {entry.value!r}: 未识别到可组装内容；'
                   '仅安装于工具环境，不会被打包或供游戏导入。')
        self.warnings.append(message)
        self._status(source, entry, 'development_only', message)

    def _visit(self, parent, path, name, source_kind='local', unbundled=False):
        key = canonical_path(path)
        if key in self._active:
            raise DependencyError('循环依赖: ' + ' -> '.join(self._active + [key]))
        if key in self._nodes:
            if source_kind == 'local' and self._nodes[key].source['kind'] == 'package':
                self._nodes[key].source['kind'] = 'local'
            parent.add_child(self._nodes[key])
            self.edges.append((parent, self._nodes[key], unbundled))
            return
        config = read_project(path)
        if config.get('tool', {}).get('mcpywrap', {}).get('project_type', 'addon') != 'addon':
            raise DependencyError(f'仅支持 Addon 目录依赖: {path}')
        folders = addon_directories(path)
        validate_game_files(path, folders.values())
        suffix = hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]
        safe_name = re.sub(r'[^\w.-]', '_', name)[:60] or 'addon'
        addon = AddonsPack(f'{safe_name}_{suffix}', path)
        addon.behavior_pack_dir, addon.resource_pack_dir = folders.get('behavior'), folders.get('resource')
        addon.code_target = config.get('tool', {}).get('mcpywrap', {}).get('_registered_code_target')
        record = self._git_sources.get(key)
        source = ({'kind': 'git', 'git': record['source']['git'], 'rev': record['source']['rev'],
                   'subdir': record['source'].get('subdir', '.'), 'source_sha256': record.get('source_sha256')}
                  if record else {'kind': source_kind, 'path': str(Path(path).resolve())})
        node = DependencyNode(name, addon, parent, source=source)
        self._nodes[key] = node
        parent.add_child(node)
        self.edges.append((parent, node, unbundled))
        self._active.append(key)
        config = read_project(path)
        try:
            if 'mcpywrap' in config.get('tool', {}):
                self._process(node, config)
        finally:
            self._active.pop()
        self._ordered.append(node)

    def selection(self):
        from collections import deque
        paths = {(id(self.root_node), False): [self.root_node.name]}
        pending = deque([(self.root_node, False)])
        outgoing = {}
        for parent, child, unbundled in self.edges:
            outgoing.setdefault(id(parent), []).append((child, unbundled))
        while pending:
            parent, inherited = pending.popleft()
            for child, unbundled in outgoing.get(id(parent), []):
                effective = inherited or unbundled
                key = (id(child), effective)
                if key not in paths:
                    paths[key] = paths[(id(parent), inherited)] + [child.name]
                    pending.append((child, effective))
        return {'purpose': self.purpose, 'includes_unbundled': self.purpose == 'runtime',
                'dependencies': [{'name': node.name, 'path': str(node.addon_pack.path),
                                  'unbundled': node.unbundled, 'included_in_release': not node.unbundled,
                                  'via': [paths[(id(node), value)] for value in (False, True) if (id(node), value) in paths]} for node in self._ordered],
                'excluded': self.excluded}

    def get_all_dependencies(self):
        return self.dependency_map

    def get_dependency_tree(self):
        return self.root_node


def find_all_mcpywrap_packages():
    packages = []
    for dist in metadata.distributions():
        try:
            direct = dist.read_text('direct_url.json')
            path = _local_url(json.loads(direct).get('url', '')) if direct else None
            if path and 'mcpywrap' in read_project(path).get('tool', {}):
                packages.append(dist.metadata['Name'])
        except (ValueError, OSError):
            continue
    return sorted(set(packages))

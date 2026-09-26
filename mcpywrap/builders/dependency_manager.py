"""将 Python 包与本地目录解析为统一的 Addon 依赖图。"""
import hashlib
import json
import re
from importlib import metadata
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

from packaging.requirements import Requirement, InvalidRequirement
from packaging.utils import canonicalize_name
from ..dependencies import DependencyError, addon_directories, canonical_path, declarations, read_project, resolve_path
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
    def __init__(self, name, addon_pack, parent=None):
        self.name, self.addon_pack, self.parent = name, addon_pack, parent
        self.children = []

    def add_child(self, node):
        if node not in self.children:
            self.children.append(node)


class DependencyManager:
    def __init__(self):
        self.dependency_map = {}
        self.root_node = None
        self.warnings = []
        self._nodes, self._active, self._ordered = {}, [], []

    def find_dependency_path(self, package_name):
        try:
            dist = metadata.distribution(Requirement(package_name).name)
        except (metadata.PackageNotFoundError, InvalidRequirement):
            return None
        direct = dist.read_text('direct_url.json')
        return _local_url(json.loads(direct).get('url', '')) if direct else None

    def build_dependency_tree(self, project_name, project_path, dependencies=None, *, config=None, allow_missing=False):
        self.__init__()
        project_path = str(Path(project_path).resolve())
        config = read_project(project_path) if config is None else config
        if dependencies is not None:
            config.setdefault('project', {})['dependencies'] = dependencies
        root_id = re.sub(r'[^\w.-]', '_', project_name)[:60] + '_' + hashlib.sha256(canonical_path(project_path).encode('utf-8')).hexdigest()[:12]
        root = DependencyNode(project_name, AddonsPack(root_id, project_path, is_origin=True))
        self.root_node = root
        key = canonical_path(project_path)
        self._nodes[key] = root
        self._active.append(key)
        self._process(root, config)
        self._active.pop()
        self.dependency_map = {canonical_path(n.addon_pack.path): n.addon_pack for n in self._ordered}
        if self.warnings and not allow_missing:
            raise DependencyError('\n'.join(self.warnings))
        return root

    def _process(self, parent, config):
        for entry in declarations(config):
            source = parent.addon_pack.path
            try:
                if entry.kind == 'local':
                    path = str(resolve_path(source, entry.value))
                    self._visit(parent, path, Path(path).name)
                    continue
                try:
                    requirement = Requirement(entry.value)
                except InvalidRequirement as exc:
                    raise DependencyError(f'无效的 Python 包声明: {entry.value}') from exc
                if requirement.marker and not requirement.marker.evaluate():
                    continue
                try:
                    dist = metadata.distribution(requirement.name)
                except metadata.PackageNotFoundError:
                    self._missing(source, entry.value, '尚未安装')
                    continue
                if requirement.specifier and not requirement.specifier.contains(dist.version, prereleases=True):
                    self._missing(source, entry.value, f'已安装 {dist.version}，不满足版本约束')
                    continue
                path = self.find_dependency_path(entry.value)
                if not path:
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
                    self._visit(parent, path, canonicalize_name(requirement.name))
            except (DependencyError, OSError, ValueError) as exc:
                raise DependencyError(f'来源 {source}\n依赖 {entry.value!r}: {exc}') from exc

    def _missing(self, source, value, reason):
        self.warnings.append(f'{source}: {value} {reason}；请显式执行 mcpy add "{value}"')

    def _visit(self, parent, path, name):
        key = canonical_path(path)
        if key in self._active:
            raise DependencyError('循环依赖: ' + ' -> '.join(self._active + [key]))
        if key in self._nodes:
            parent.add_child(self._nodes[key])
            return
        config = read_project(path)
        if config.get('tool', {}).get('mcpywrap', {}).get('project_type', 'addon') != 'addon':
            raise DependencyError(f'仅支持 Addon 目录依赖: {path}')
        folders = addon_directories(path)
        suffix = hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]
        safe_name = re.sub(r'[^\w.-]', '_', name)[:60] or 'addon'
        addon = AddonsPack(f'{safe_name}_{suffix}', path)
        addon.behavior_pack_dir, addon.resource_pack_dir = folders.get('behavior'), folders.get('resource')
        node = DependencyNode(name, addon, parent)
        self._nodes[key] = node
        parent.add_child(node)
        self._active.append(key)
        config = read_project(path)
        if 'mcpywrap' in config.get('tool', {}):
            self._process(node, config)
        self._active.pop()
        self._ordered.append(node)

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

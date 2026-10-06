"""CLI、GUI 共用的依赖声明与只读目录校验。"""
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import tomli
import tomli_w
from packaging.requirements import Requirement, InvalidRequirement


class DependencyError(ValueError):
    # Messages carry their actionable recovery step; avoid a generic path hint.
    hint = None


@dataclass(frozen=True)
class DependencyDeclaration:
    kind: str
    value: str


@dataclass(frozen=True)
class DependencyStatus:
    state: str  # addon, development_only, inactive, unavailable
    message: str = ''


def is_native_file(path):
    name = Path(path).name.lower()
    return name.endswith(('.pyd', '.dll', '.so', '.dylib')) or bool(re.search(r'\.so\.\d+(?:\.\d+)*$', name))


def validate_game_files(project_dir, folders):
    """检查实际游戏包，先于构建过滤；不检查工具环境或项目外的开发文件。"""
    visited = set()
    def fail(error):
        raise error
    for folder in filter(None, folders):
        if not Path(folder).exists():
            continue  # 资源包、行为包均可缺省；结构检查由调用方负责。
        for current, dirs, files in os.walk(folder, followlinks=True, onerror=fail):
            key = canonical_path(current)
            if key in visited:
                dirs[:] = []
                continue
            visited.add(key)
            dirs.sort()
            for name in sorted(files):
                if is_native_file(name):
                    raise DependencyError(
                        f'来源 {project_dir}\n游戏包包含不支持的原生二进制: {Path(current) / name}\n'
                        '游戏使用独立 Python 环境，不能加载工具环境的原生扩展；'
                        '请将开发依赖移出游戏包，或改用兼容游戏环境的纯 Python 实现。')


def canonical_path(path):
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def resolve_path(project_dir, declaration):
    path = Path(declaration).expanduser()
    path = path if path.is_absolute() else Path(project_dir) / path
    value = str(path)
    # Windows 扩展路径禁用 .. 解释，Python 3.9 的 resolve 也可能原样保留。
    # 先恢复普通路径，再解析链接和父目录，保持普通本地依赖的路径语义。
    if os.name == 'nt' and value.startswith('\\\\?\\UNC\\'):
        value = '\\\\' + value[8:]
    elif os.name == 'nt' and value.startswith('\\\\?\\'):
        value = value[4:]
    return Path(value).resolve()


def read_project(project_dir):
    path = Path(project_dir) / 'pyproject.toml'
    if not path.exists():
        return {}
    try:
        with path.open('rb') as stream:
            config = tomli.load(stream)
        validate_tables(config)
        return config
    except (OSError, tomli.TOMLDecodeError) as exc:
        raise DependencyError(f'无法读取配置 {path}: {exc}') from exc


def write_project(project_dir, config):
    """原子替换主项目配置，失败时不留下半份文件。"""
    fd, temporary = tempfile.mkstemp(prefix='.mcpy-', suffix='.toml', dir=project_dir)
    try:
        with os.fdopen(fd, 'wb') as stream:
            tomli_w.dump(config, stream)
        os.replace(temporary, Path(project_dir) / 'pyproject.toml')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_tables(config):
    for name in ('project', 'tool'):
        if not isinstance(config.get(name, {}), dict):
            raise DependencyError(f'{name} 必须是 TOML 表')
    if not isinstance(config.get('tool', {}).get('mcpywrap', {}), dict):
        raise DependencyError('tool.mcpywrap 必须是 TOML 表')


def declarations(config):
    validate_tables(config)
    result = []
    for kind, values in (
        ('package', config.get('project', {}).get('dependencies', [])),
        ('local', config.get('tool', {}).get('mcpywrap', {}).get('local_dependencies', [])),
    ):
        if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
            raise DependencyError(f'{kind} 依赖必须是非空字符串数组')
        result.extend(DependencyDeclaration(kind, value) for value in values)
    return result


def addon_directories(path):
    """识别 Addon 根目录，拒绝地图、单个包和不明确的多包结构。"""
    root = Path(path)
    if not root.is_dir():
        raise DependencyError(f'目录不存在: {root}')
    if (root / 'level.dat').exists() or (root / 'db').is_dir():
        raise DependencyError(f'不支持将地图根目录作为 Addon 依赖: {root}')
    if any((root / name).is_file() for name in ('manifest.json', 'pack_manifest.json')):
        raise DependencyError(f'请选择 Addon 根目录，而不是单个包: {root}')
    found = {}
    for kind, prefixes in (('behavior', ('behavior_pack', 'BehaviorPack')),
                           ('resource', ('resource_pack', 'ResourcePack'))):
        matches = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith(prefixes))
        if len(matches) > 1:
            raise DependencyError(f'{root} 包含多个 {kind} 包，第一版仅支持一个同类型包')
        if not matches:
            continue
        pack = matches[0]
        manifest = next((pack / n for n in ('manifest.json', 'pack_manifest.json') if (pack / n).is_file()), None)
        if manifest is None:
            raise DependencyError(f'缺少 manifest: {pack}')
        try:
            data = json.loads(manifest.read_text(encoding='utf-8-sig'))
            if not isinstance(data, dict) or not isinstance(data.get('header'), dict) or not data['header'].get('uuid'):
                raise ValueError('缺少 header.uuid')
            header = data['header']
            if not isinstance(header.get('name'), str) or not header['name'].strip():
                raise ValueError('缺少 header.name')
            modules = data.get('modules')
            if not isinstance(modules, list) or not modules:
                raise ValueError('modules 必须是非空数组')
            for section in [header] + modules:
                if not isinstance(section, dict) or not isinstance(section.get('uuid'), str):
                    raise ValueError('header/modules 缺少有效 uuid')
                uuid.UUID(section['uuid'])
                version = section.get('version')
                if not isinstance(version, list) or len(version) != 3 or any(type(n) is not int or n < 0 for n in version):
                    raise ValueError('header/modules.version 必须包含三个非负整数')
            if any(not isinstance(module.get('type'), str) or not module['type'] for module in modules):
                raise ValueError('modules 缺少 type')
        except (ValueError, OSError) as exc:
            raise DependencyError(f'无效 manifest {manifest}: {exc}') from exc
        found[kind] = str(pack.resolve())
    if not found:
        raise DependencyError(f'未找到有效的行为包或资源包: {root}')
    return found


def path_for_storage(project_dir, path, absolute=False):
    resolved = resolve_path(project_dir, path)
    if not absolute:
        try:
            return Path(os.path.relpath(resolved, Path(project_dir).resolve())).as_posix()
        except ValueError:
            pass  # Windows 跨盘只能保存绝对路径。
    return resolved.as_posix()


class DependencyService:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir).resolve()
        self.last_resolution = None

    def list(self):
        from .code_libraries import declarations as libraries
        from .git_projects import declarations as projects
        config = read_project(self.project_dir)
        return declarations(config) + [DependencyDeclaration('code', item['name'])
                                       for item in libraries(self.project_dir, config)] + [
            DependencyDeclaration('git', item['name']) for item in projects(self.project_dir, config)]

    def add_framework(self, preset, script_dir=None, source=None, require_new=False):
        from .frameworks import add_framework
        return add_framework(self.project_dir, preset, script_dir, source, require_new)

    def add_git(self, url, **options):
        from .project_dependencies import GitDependencyService
        return GitDependencyService(self.project_dir).add(url, **options)

    def resolve(self, config=None, allow_missing=False, git_lock=None):
        from .builders.dependency_manager import DependencyManager
        config = read_project(self.project_dir) if config is None else config
        manager = DependencyManager()
        manager.build_dependency_tree(config.get('project', {}).get('name', self.project_dir.name),
                                      str(self.project_dir), config=config, allow_missing=allow_missing, git_lock=git_lock)
        self.last_resolution = manager
        return manager

    def prepare_local(self, value, config=None):
        """预检候选配置，不写文件；缺失 Python 包以警告返回。"""
        value = value.strip()
        if not value:
            raise DependencyError('本地目录不能为空')
        candidate = copy.deepcopy(read_project(self.project_dir) if config is None else config)
        settings = candidate.setdefault('tool', {}).setdefault('mcpywrap', {})
        values = settings.setdefault('local_dependencies', [])
        declarations(candidate)
        target = canonical_path(resolve_path(self.project_dir, value))
        duplicate = any(canonical_path(resolve_path(self.project_dir, item)) == target for item in values)
        if not duplicate:
            values.append(value)
        manager = self.resolve(candidate, allow_missing=True)
        return candidate, not duplicate, manager.warnings

    def add_local(self, value):
        candidate, changed, warnings = self.prepare_local(value)
        if changed:
            write_project(self.project_dir, candidate)
        return changed, warnings

    @staticmethod
    def install_package(value):
        try:
            Requirement(value)
        except InvalidRequirement as exc:
            raise DependencyError(f'无效的 Python 包声明: {value}') from exc
        result = subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-input', value],
                                capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode:
            raise DependencyError(result.stderr.strip() or result.stdout.strip() or 'pip 安装失败')

    def add_package(self, value):
        declarations(read_project(self.project_dir))
        self.install_package(value)
        try:
            config = read_project(self.project_dir)
            declarations(config)
            values = config.setdefault('project', {}).setdefault('dependencies', [])
            changed = value not in values
            if changed:
                values.append(value)
            manager = self.resolve(config, allow_missing=True)
            status = manager.status_for(self.project_dir, DependencyDeclaration('package', value))
            if status.state == 'unavailable':
                raise DependencyError(status.message)
            if changed:
                write_project(self.project_dir, config)
            return changed
        except (DependencyError, OSError) as exc:
            raise DependencyError(f'{exc}\npip 已在 mcpy 工具环境完成安装；新增声明未保存，未自动卸载。') from exc

    def remove(self, declaration):
        if declaration.kind == 'git':
            from .project_dependencies import GitDependencyService
            return GitDependencyService(self.project_dir).remove(declaration.value)
        if declaration.kind == 'code':
            # 兼容既有code_libraries；移除不删除源码和缓存。
            from .code_libraries import remove_library
            return remove_library(self.project_dir, declaration.value)
        config = read_project(self.project_dir)
        declarations(config)
        if declaration.kind == 'local':
            values = config.get('tool', {}).get('mcpywrap', {}).get('local_dependencies', [])
            target = canonical_path(resolve_path(self.project_dir, declaration.value))
            matches = [v for v in values if v == declaration.value or canonical_path(resolve_path(self.project_dir, v)) == target]
        else:
            values = config.get('project', {}).get('dependencies', [])
            matches = [v for v in values if v == declaration.value]
        if not matches:
            raise DependencyError(f'未声明该依赖: {declaration.value}')
        values[:] = [v for v in values if v not in matches]
        write_project(self.project_dir, config)

    def inspect(self, declaration):
        if declaration.kind == 'git':
            from .project_dependencies import GitDependencyService
            return GitDependencyService(self.project_dir).inspect(declaration.value)
        config = read_project(self.project_dir)
        if declaration.kind == 'code':
            from .code_libraries import declarations as libraries, resolve_libraries, LOCK_FILE
            try:
                selected = [item for item in libraries(self.project_dir, config) if item['name'] == declaration.value]
                if not selected:
                    raise DependencyError('未声明此代码库')
                config['tool']['mcpywrap']['code_libraries'] = selected
                lock = json.loads((self.project_dir / LOCK_FILE).read_text('utf-8'))
                lock['libraries'] = [item for item in lock['libraries'] if item['declaration']['name'] == declaration.value]
                resolved = resolve_libraries(self.project_dir, config, lock)[0]
                return DependencyStatus('code_library', f"{resolved['git']}\n提交: {resolved['rev']}\n行为包内目标: {resolved['target']}")
            except (DependencyError, OSError, ValueError, KeyError, TypeError) as exc:
                return DependencyStatus('unavailable', f'{exc}\n请执行 mcpy sync 恢复代码库')
        config.setdefault('project', {})['dependencies'] = [declaration.value] if declaration.kind == 'package' else []
        config.setdefault('tool', {}).setdefault('mcpywrap', {})['local_dependencies'] = [declaration.value] if declaration.kind == 'local' else []
        try:
            manager = self.resolve(config, allow_missing=True)
            status = manager.status_for(self.project_dir, declaration)
            if manager.errors:
                return DependencyStatus('unavailable', '\n'.join(manager.errors))
            return DependencyStatus(status.state, '\n'.join(manager.warnings) or status.message)
        except (DependencyError, OSError) as exc:
            return DependencyStatus('unavailable', str(exc))

    def status(self, declaration):
        return self.inspect(declaration).message

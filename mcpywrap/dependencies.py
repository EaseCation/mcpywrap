"""CLI、GUI 共用的依赖声明与只读目录校验。"""
import copy
import json
import os
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
    pass


@dataclass(frozen=True)
class DependencyDeclaration:
    kind: str
    value: str


def canonical_path(path):
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def resolve_path(project_dir, declaration):
    path = Path(declaration).expanduser()
    return path.resolve() if path.is_absolute() else (Path(project_dir) / path).resolve()


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

    def list(self):
        return declarations(read_project(self.project_dir))

    def resolve(self, config=None, allow_missing=False):
        from .builders.dependency_manager import DependencyManager
        config = read_project(self.project_dir) if config is None else config
        manager = DependencyManager()
        manager.build_dependency_tree(config.get('project', {}).get('name', self.project_dir.name),
                                      str(self.project_dir), config=config, allow_missing=allow_missing)
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
        result = subprocess.run([sys.executable, '-m', 'pip', 'install', value],
                                capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode:
            raise DependencyError(result.stderr.strip() or result.stdout.strip() or 'pip 安装失败')

    def add_package(self, value):
        declarations(read_project(self.project_dir))
        self.install_package(value)
        config = read_project(self.project_dir)
        declarations(config)
        values = config.setdefault('project', {}).setdefault('dependencies', [])
        if value in values:
            return False
        values.append(value)
        write_project(self.project_dir, config)
        return True

    def remove(self, declaration):
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

    def status(self, declaration):
        config = read_project(self.project_dir)
        config.setdefault('project', {})['dependencies'] = [declaration.value] if declaration.kind == 'package' else []
        config.setdefault('tool', {}).setdefault('mcpywrap', {})['local_dependencies'] = [declaration.value] if declaration.kind == 'local' else []
        try:
            return '\n'.join(self.resolve(config, allow_missing=True).warnings)
        except (DependencyError, OSError) as exc:
            return str(exc)

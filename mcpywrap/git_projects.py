"""远程项目依赖：固定源码、识别导出结构、解析依赖图并注册为统一 Addon 节点。

此模块不包含任何框架名称或模板。构建/运行仅读取锁定后的注册节点，不访问网络。
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from .code_libraries import sync_libraries
from .source_files import _relative, digest, long_path, windows_checkout_digest
from .dependencies import DependencyError, addon_directories, read_project, write_project, resolve_path

LOCK_FILE = 'mcpy-git.lock.json'
REGISTRATION_VERSION = 1


def declarations(root, config=None):
    config = read_project(root) if config is None else config
    entries = config.get('tool', {}).get('mcpywrap', {}).get('git_dependencies', [])
    if not isinstance(entries, list):
        raise DependencyError('git_dependencies 必须是表数组')
    names = set()
    for entry in entries:
        if not isinstance(entry, dict) or not {'name', 'git', 'rev'} <= set(entry) or set(entry) - {'name', 'git', 'rev', 'subdir', 'kind', 'target'}:
            raise DependencyError('Git依赖需要 name/git/rev，可选 subdir/kind/target')
        name = entry['name']
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name) or name.lower() in names:
            raise DependencyError('Git依赖名称无效或重复')
        names.add(name.lower())
        if not isinstance(entry['git'], str) or not entry['git'].startswith(('https://', 'file://')):
            raise DependencyError('Git来源须为HTTPS或file://本地Git仓库')
        if not isinstance(entry['rev'], str) or not re.fullmatch('[0-9a-f]{40}', entry['rev']):
            raise DependencyError('Git依赖必须锁定完整提交；通过 mcpy add --git 解析分支或标签')
        if entry.get('kind', 'auto') not in ('auto', 'addon', 'code'):
            raise DependencyError('Git依赖 kind 须为 auto/addon/code')
        if entry.get('subdir', '.') != '.':
            _relative(entry['subdir'], 'Git项目子目录')
        if 'target' in entry:
            _relative(entry['target'], '代码安装目标')
    return entries


def _key(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _write_json(path, data):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.mcpy-json-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def fetch_source(root, url, ref):
    from .git_cache import fetch_snapshot
    return fetch_snapshot(url, ref)


def _layout(source, entry):
    project = source / entry.get('subdir', '.')
    if not project.is_dir():
        raise DependencyError(f'Git子目录不存在: {entry.get("subdir")}')
    config = read_project(project)
    export = config.get('tool', {}).get('mcpywrap', {}).get('export', {})
    if not isinstance(export, dict) or set(export) - {'kind', 'path', 'target'}:
        raise DependencyError('tool.mcpywrap.export 支持 kind/path/target')
    kind = entry.get('kind', 'auto')
    if kind == 'auto':
        kind = export.get('kind', 'auto')
    path = export.get('path', '.')
    if path != '.':
        _relative(path, '导出路径')
    payload = project / path
    if not payload.is_dir():
        raise DependencyError('项目声明的导出目录不存在')
    if kind == 'auto':
        try:
            addon_directories(payload)
            kind = 'addon'
        except DependencyError as exc:
            raise DependencyError('无法识别Git项目布局：请提供 tool.mcpywrap.export，或显式 --kind code --subdir <源码> --target <安装目录>') from exc
    if kind not in ('addon', 'code'):
        raise DependencyError('不支持的项目导出类型')
    target = entry.get('target') or export.get('target')
    if kind == 'addon':
        if target:
            raise DependencyError('Addon导出不使用target；包目录来自manifest')
        addon_directories(payload)
    else:
        target = _relative(target, '代码导出需要明确target')
        if not any(payload.rglob('*.py')):
            raise DependencyError('代码导出目录中没有Python文件')
    return project, payload, config, kind, target


def prepare_graph(root, config=None, migrate_windows_lock=False):
    root = Path(root).resolve()
    config = read_project(root) if config is None else config
    roots = declarations(root, config)
    expected, legacy = {}, False
    if (root / LOCK_FILE).exists():
        try:
            prior = json.loads((root / LOCK_FILE).read_text('utf-8'))
            legacy = prior['version'] == 1
            expected = {record['id']: record for record in prior['nodes']}
        except (ValueError, KeyError, TypeError) as exc:
            raise DependencyError('无法读取依赖锁文件 mcpy-git.lock.json。\n请从版本控制恢复该文件后运行 mcpy sync。') from exc
        if prior.get('version') not in (1, 2):
            raise DependencyError('此项目需要较新版本的 mcpy，请先升级 mcpywrap。')
    registered = long_path(root / '.mcpy/git-projects')
    registered.mkdir(parents=True, exist_ok=True)
    nodes, active, migrations = {}, [], []
    def visit(entry, supplied_source=None):
        source, commit = supplied_source or fetch_source(root, entry['git'], entry['rev'])
        project, payload, project_config, kind, target = _layout(source, entry)
        identity = {k: v for k, v in entry.items() if k != 'name'}
        identity['subdir'] = entry.get('subdir', '.')
        identity['kind'] = kind
        identity['registration'] = REGISTRATION_VERSION
        if target:
            identity['target'] = target
        key = _key(identity)
        if key in active:
            raise DependencyError('Git项目循环依赖: ' + ' -> '.join(active + [key]))
        if key in nodes:
            return key
        active.append(key)
        source_hash = digest(source)
        previous = expected.get(key)
        migrating = legacy and previous is not None
        if previous and previous['source_sha256'] != source_hash:
            if not migrating or previous['source_sha256'] not in (
                    windows_checkout_digest(source), windows_checkout_digest(source, crlf=False)):
                raise DependencyError(f"依赖 {entry['name']} 的源码校验失败。\n请保留 mcpy-git.lock.json，并重新获取该依赖的固定版本。")
        children = []
        for child in declarations(project, project_config):
            children.append(visit(child))
        local = project_config.get('tool', {}).get('mcpywrap', {}).get('local_dependencies', [])
        if not isinstance(local, list) or any(not isinstance(v, str) for v in local):
            raise DependencyError('远程项目local_dependencies必须是相对路径数组')
        for value in local:
            path = long_path(resolve_path(project, value))
            source_root = long_path(resolve_path(source, '.'))
            if Path(value).is_absolute() or not path.is_relative_to(source_root):
                raise DependencyError('远程项目本地引用不得离开Git快照；外部仓库请声明git_dependencies')
            # Python 3.9 的 resolve 会移除 Windows 扩展路径前缀；
            # 边界检查和相对路径计算必须使用同一个规范化基准。
            child = {'name': path.name, 'git': entry['git'], 'rev': commit,
                     'subdir': path.relative_to(source_root).as_posix(), 'kind': 'auto'}
            children.append(visit(child, (source, commit)))
        with tempfile.TemporaryDirectory(prefix='register-', dir=registered) as temporary:
            stage = Path(temporary) / 'project'
            stage.mkdir()
            if kind == 'addon':
                folders = addon_directories(payload)
                for folder in folders.values():
                    shutil.copytree(folder, stage / Path(folder).name)
            else:
                behavior = stage / 'behavior_pack'
                shutil.copytree(payload, behavior / target)
                manifest = {'format_version': 2, 'header': {'name': 'git-' + key[:12], 'description': 'Registered code dependency',
                    'uuid': str(uuid.uuid5(uuid.NAMESPACE_URL, key)), 'version': [1, 0, 0]},
                    'modules': [{'type': 'data', 'uuid': str(uuid.uuid5(uuid.NAMESPACE_URL, key + ':module')), 'version': [1, 0, 0]}]}
                _write_json(behavior / 'manifest.json', manifest)
            # 把注册节点依赖转为工具已有的本地Addon图，不向解释器安装任何内容。
            normalized = copy.deepcopy(project_config)
            settings = normalized.setdefault('tool', {}).setdefault('mcpywrap', {})
            settings.pop('git_dependencies', None)
            settings.pop('export', None)
            settings.pop('_registered_code_target', None)
            if kind == 'code':
                settings['_registered_code_target'] = target
            settings['project_type'] = 'addon'
            settings['local_dependencies'] = ['../' + child for child in dict.fromkeys(children)]
            normalized.setdefault('project', {})['name'] = 'git-' + key[:12]
            write_project(stage, normalized)
            for file in source.iterdir():
                if file.is_file() and re.fullmatch(r'(LICENSE|COPYING|NOTICE)(\.[\w-]+)?', file.name, re.I):
                    for folder in addon_directories(stage).values():
                        # 多个Git项目合并时，各自的许可不得被同名文件覆盖。
                        notice = Path(folder) / 'mcpy_licenses' / key / file.name
                        notice.parent.mkdir(parents=True, exist_ok=True)
                        notice.write_bytes(file.read_bytes())
            if settings.get('code_libraries'):
                sync_libraries(stage)
            from .dependencies import validate_game_files
            validate_game_files(stage, addon_directories(stage).values())
            content_hash = digest(stage)
            if previous and previous['sha256'] != content_hash and not migrating:
                raise DependencyError(f"依赖 {entry['name']} 的安装内容与锁文件不一致。\n请确认团队使用相同版本的 mcpywrap；不要删除锁文件。")
            final = registered / key
            if final.exists():
                if digest(final) != content_hash:
                    # Old generated files may contain Windows line endings. Only
                    # replace a verified old registration; preserve it for recovery.
                    if not migrating or previous['sha256'] not in (
                            digest(final), windows_checkout_digest(final, crlf=False)):
                        raise DependencyError(f"依赖 {entry['name']} 的本地文件已修改。\n请将 {final} 移到项目外备份，再运行 mcpy sync。")
                    backups = root/'.mcpy/registration-backups'
                    backups.mkdir(parents=True, exist_ok=True)
                    backup = Path(tempfile.mkdtemp(prefix=key[:12]+'-', dir=backups))/'project'
                    os.replace(final, backup)
                    try:
                        os.replace(stage, final)
                    except BaseException:
                        os.replace(backup, final)
                        raise
            else:
                os.replace(stage, final)
        record = {'id': key, 'source': identity, 'source_sha256': source_hash, 'sha256': content_hash,
                  'kind': kind, 'target': target, 'children': list(dict.fromkeys(children))}
        if migrating:
            migrations.append({'node': key, 'name': entry['name'], 'git': entry['git'], 'rev': commit,
                               'old_source_sha256': previous['source_sha256'], 'source_sha256': source_hash,
                               'old_registered_sha256': previous['sha256'], 'registered_sha256': content_hash})
        nodes[key] = record
        active.pop()
        return key
    root_ids = [visit(entry) for entry in roots]
    lock = {'version': 2, 'declarations': roots, 'roots': root_ids, 'nodes': list(nodes.values())}
    if migrations:
        lock['_lock_migrations'] = migrations
    return lock


def write_lock(root, lock):
    data = dict(lock)
    migrations = data.pop('_lock_migrations', [])
    report = []
    if migrations and (Path(root)/LOCK_FILE).exists():
        old = (Path(root)/LOCK_FILE).read_bytes()
        backup = Path(root)/'.mcpy/lock-backups'/(hashlib.sha256(old).hexdigest()+'.json')
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists() and backup.read_bytes() != old:
            raise DependencyError('无法备份旧依赖记录，原锁文件未修改。')
        backup.write_bytes(old)
        report.append({'project': str(root), 'backup': str(backup), 'nodes': migrations})
    _write_json(Path(root) / LOCK_FILE, data)
    return report


def sync_projects(root, config=None, migrate_windows_lock=False, migration_report=None):
    # Kept for older callers; recognized legacy locks now migrate automatically.
    lock = prepare_graph(root, config, migrate_windows_lock=migrate_windows_lock)
    report = write_lock(root, lock)
    if migration_report is not None:
        migration_report.extend(report)
    return len(lock['nodes'])


def resolve_projects(root, config=None, lock=None):
    root = Path(root).resolve()
    entries = declarations(root, config)
    if not entries:
        return []
    try:
        lock = json.loads((root / LOCK_FILE).read_text('utf-8')) if lock is None else lock
        if lock['version'] not in (1, 2):
            raise DependencyError('此项目需要较新版本的 mcpy，请先升级 mcpywrap。')
        if lock['declarations'] != entries:
            raise ValueError('项目的依赖配置已更新。')
        if len(lock['roots']) != len(entries):
            raise ValueError('Git锁文件根节点数量不符')
        nodes = {node['id']: node for node in lock['nodes']}
        for key, node in nodes.items():
            if not re.fullmatch('[0-9a-f]{64}', key):
                raise ValueError('Git锁文件节点ID无效')
            folder = long_path(root / '.mcpy/git-projects' / key)
            name = next((e['name'] for e, k in zip(entries, lock['roots']) if k == key),
                        node['source']['git'].rstrip('/').split('/')[-1].removesuffix('.git'))
            if not folder.is_dir():
                raise ValueError(f'依赖 {name} 尚未安装。')
            if digest(folder) != node['sha256']:
                if lock['version'] != 1 or windows_checkout_digest(folder, crlf=False) != node['sha256']:
                    raise ValueError(f'依赖 {name} 的本地文件需要重新同步。')
            if any(child not in nodes for child in node['children']):
                raise ValueError('Git锁文件缺少子依赖')
        return [(entry, long_path(root / '.mcpy/git-projects' / key), nodes[key]) for entry, key in zip(entries, lock['roots'])]
    except DependencyError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DependencyError(f'{exc}\n运行 mcpy sync 后重试。') from exc

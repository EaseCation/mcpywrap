"""远程项目管理事务。入口层提交标准声明；核心没有框架特判。"""
import copy
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit

from . import git_projects
from .source_files import _relative
from .dependencies import DependencyError, DependencyService, DependencyStatus, addon_directories, read_project, write_project


def _snapshot(path):
    return path.read_bytes() if path.exists() else None


def _restore(path, data):
    if data is None:
        path.unlink(missing_ok=True)
        return
    fd, temporary = tempfile.mkstemp(prefix='.mcpy-restore-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class GitDependencyService:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def add(self, url, ref=None, name=None, subdir=None, kind=None, target=None, scaffold=None):
        if not (self.root / 'pyproject.toml').is_file():
            raise DependencyError('请先执行 mcpy init 初始化项目')
        name = name or re.sub(r'[^A-Za-z0-9_.-]', '-', Path(urlsplit(url).path.rstrip('/')).name.removesuffix('.git'))
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
            raise DependencyError('依赖名称无效')
        config = read_project(self.root)
        if target:
            _relative(target, '代码安装目标')
            behavior = addon_directories(self.root).get('behavior')
            if behavior:
                destination = Path(behavior) / target
                if destination.exists() or destination.with_suffix('.py').exists():
                    raise DependencyError(f'已有手工内容，依赖不会覆盖或删除: {destination}')
        candidate = copy.deepcopy(config)
        entries = candidate.setdefault('tool', {}).setdefault('mcpywrap', {}).setdefault('git_dependencies', [])
        previous = next((entry for entry in entries if entry['name'] == name), None)
        same_source = previous if previous and previous['git'] == url else {}
        subdir = subdir if subdir is not None else same_source.get('subdir', '.')
        kind = kind if kind is not None else same_source.get('kind', 'auto')
        if target is None and kind != 'addon':
            target = same_source.get('target')
        # 重复添加默认保持固定提交，只有显式ref才重新解析远程引用。
        requested_ref = ref or (previous['rev'] if previous and previous['git'] == url else 'HEAD')
        paths = [self.root / 'pyproject.toml', self.root / git_projects.LOCK_FILE, self.root / '.gitignore']
        before = [_snapshot(path) for path in paths]
        source, commit = git_projects.fetch_source(self.root, url, requested_ref)
        entry = {'name': name, 'git': url, 'rev': commit, 'subdir': subdir, 'kind': kind}
        if target:
            entry['target'] = target
        if previous:
            entries[entries.index(previous)] = entry
        else:
            entries.append(entry)
        git_projects.declarations(self.root, candidate)
        git_projects._layout(source, entry)
        script = None
        files = {}
        if scaffold:
            directory = _relative(scaffold['directory'], '模板目录')
            if '/' in directory or not target or not target.startswith(directory + '/'):
                raise DependencyError('模板必须属于依赖安装的顶级脚本目录')
            behavior = addon_directories(self.root).get('behavior')
            if not behavior:
                raise DependencyError('入口模板需要行为包')
            script = Path(behavior) / directory
            if script.exists() or script.is_symlink():
                raise DependencyError('脚本目录已存在，不覆盖: ' + str(script))
            files = {_relative(path, '模板文件'): text for path, text in scaffold['files'].items()}
            if any(not isinstance(text, str) for text in files.values()):
                raise DependencyError('模板文件必须为文本')
        lock = git_projects.prepare_graph(self.root, candidate)
        manager = DependencyService(self.root).resolve(candidate, git_lock=lock)
        from .code_libraries import prepare_libraries
        packs = list(manager.get_all_dependencies().values()) + [manager.root_node.addon_pack]
        prepare_libraries(packs)
        if any(_snapshot(path) != data for path, data in zip(paths, before)):
            raise DependencyError('同步期间项目配置或锁文件已改变；没有覆盖，请重试')
        created = False
        try:
            if script is not None:
                script.mkdir()
                created = True
                for relative, text in files.items():
                    path = script / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text, encoding='utf-8')
            git_projects.write_lock(self.root, lock)
            if candidate != config:
                write_project(self.root, candidate)
            ignore = before[2].decode('utf-8-sig') if before[2] is not None else ''
            extra = [p for p in ('.mcpy/', '.runtime/', 'build/', 'dist/', '__pycache__/', '*.pyc') if p not in ignore.splitlines()]
            if extra:
                ignore += ('\n' if ignore and not ignore.endswith('\n') else '') + '\n# mcpywrap 本地产物\n' + '\n'.join(extra) + '\n'
                paths[2].write_text(ignore, encoding='utf-8')
        except Exception:
            for path, data in zip(paths, before):
                _restore(path, data)
            if created and script.parent.resolve() == Path(addon_directories(self.root)['behavior']).resolve() and not script.is_symlink():
                shutil.rmtree(script)
            raise
        node_id = lock['roots'][next(i for i, item in enumerate(entries) if item['name'] == name)]
        resolved = next(node for node in lock['nodes'] if node['id'] == node_id)
        return {'dependency': name, 'source': url, 'rev': commit, 'target': resolved['target'], 'kind': resolved['kind'],
                'classification': 'git_project', 'synced': True, 'changed': candidate != config,
                'new_script': created, 'warnings': manager.warnings, 'nodes': len(lock['nodes'])}

    def inspect(self, name):
        try:
            for entry, path, node in git_projects.resolve_projects(self.root):
                if entry['name'] == name:
                    return DependencyStatus('git_project', f"{entry['git']}\n提交: {entry['rev']}\n类型: {node['kind']}\n目标: {node.get('target') or '独立Addon'}")
            raise DependencyError('未声明此Git依赖')
        except (DependencyError, OSError) as exc:
            return DependencyStatus('unavailable', str(exc))

    def remove(self, name):
        config = read_project(self.root)
        entries = git_projects.declarations(self.root, config)
        index = next((i for i, entry in enumerate(entries) if entry['name'] == name), None)
        if index is None:
            raise DependencyError('未声明此Git依赖: ' + name)
        del config['tool']['mcpywrap']['git_dependencies'][index]
        paths = self.root / 'pyproject.toml', self.root / git_projects.LOCK_FILE
        before = [_snapshot(path) for path in paths]
        try:
            if before[1] is not None:
                lock = json.loads(before[1])
                # 缺失/陈旧的锁不猜测对应关系；删除后显式sync可重新恢复。
                if len(lock['roots']) == len(lock['declarations']) and lock['declarations'][index]['name'] == name:
                    del lock['roots'][index]
                    del lock['declarations'][index]
                    by_id = {node['id']: node for node in lock['nodes']}
                    reachable = set()
                    def include(key):
                        if key not in reachable:
                            reachable.add(key)
                            for child in by_id[key]['children']:
                                include(child)
                    for key in lock['roots']:
                        include(key)
                    lock['nodes'] = [node for node in lock['nodes'] if node['id'] in reachable]
                    git_projects.write_lock(self.root, lock)
            write_project(self.root, config)
        except Exception:
            for path, data in zip(paths, before):
                _restore(path, data)
            raise

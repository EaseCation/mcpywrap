"""显式维护项目，无隐式初始化或 SDK 安装。"""
import subprocess
import sys
from pathlib import Path
import click
from ..command_context import OperationCommand, project_dir, require_project, project_scope
from ..dependencies import read_project, write_project


@click.command(cls=OperationCommand)
@click.option('--install', is_flag=True, help='同时在当前工具环境中可编辑安装项目')
def sync_cmd(install):
    """同步包配置；--install 安装到 mcpy 工具环境，不安装到游戏。"""
    require_project()
    return sync_project(project_dir(), install)


def sync_project(path, install=False):
    from ..config import ensure_map_setuptools_sync
    from ..utils.project_setup import find_and_configure_behavior_pack
    with project_scope(path):
        config = read_project(path)
        from ..dependencies import DependencyService, canonical_path, declarations as dependency_declarations, resolve_path
        from ..code_libraries import declarations, sync_libraries
        from ..git_projects import declarations as git_declarations, sync_projects, LOCK_FILE as GIT_LOCK_FILE
        from ..builders.dependency_manager import DependencyManager
        visited, active = set(), set()
        git_count = 0
        def sync_sources(directory):
            nonlocal git_count
            key = canonical_path(directory)
            if key in active:
                from ..dependencies import DependencyError
                raise DependencyError('本地项目循环依赖: ' + str(directory))
            if key in visited:
                return
            active.add(key)
            source_config = read_project(directory)
            for entry in dependency_declarations(source_config):
                if entry.kind == 'local':
                    sync_sources(resolve_path(directory, entry.value))
                else:
                    target = DependencyManager().find_dependency_path(entry.value)
                    if target and 'mcpywrap' in read_project(target).get('tool', {}):
                        sync_sources(target)
            if git_declarations(directory, source_config) or Path(directory, GIT_LOCK_FILE).exists():
                git_count += sync_projects(directory, source_config)
            active.remove(key)
            visited.add(key)
        sync_sources(path)
        manager = DependencyService(path).resolve()
        packs = list(manager.get_all_dependencies().values()) + [manager.root_node.addon_pack]
        library_count = sum(sync_libraries(pack.path) for pack in packs if declarations(pack.path) or
                            Path(pack.path, 'mcpy-code-libraries.lock.json').exists())
        kind = config.get('tool', {}).get('mcpywrap', {}).get('project_type', 'addon')
        if kind == 'map':
            ensure_map_setuptools_sync(interactive=False)
        else:
            find_and_configure_behavior_pack(str(path), config)
            write_project(path, config)
        if install:
            proc = subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-input', '-e', str(path)],
                                  capture_output=True, text=True)
            if proc.returncode:
                raise click.ClickException(proc.stderr or proc.stdout or '项目安装失败')
    return {'project': str(path), 'installed': install, 'code_libraries': library_count, 'git_projects': git_count}

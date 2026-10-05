"""显式维护项目，无隐式初始化或 SDK 安装。"""
import subprocess
import sys
import time
from pathlib import Path
import click
from ..command_context import OperationCommand, project_dir, require_project, project_scope, json_output
from ..dependencies import read_project, write_project


@click.command(cls=OperationCommand)
@click.option('--install', is_flag=True, help='同时在当前工具环境中可编辑安装项目')
@click.option('--migrate-windows-lock', is_flag=True, hidden=True)
def sync_cmd(install, migrate_windows_lock=False):
    """同步包配置；--install 安装到 mcpy 工具环境，不安装到游戏。"""
    require_project()
    started = time.monotonic()
    click.echo('同步依赖…', err=True)
    result = sync_project(project_dir(), install, migrate_windows_lock=migrate_windows_lock)
    if json_output():
        return result
    if result['git_lock_migrations']:
        click.echo('已更新跨平台依赖记录，旧文件已备份。')
    count = result['git_projects'] + result['code_libraries']
    click.secho('完成 · %d 个源码依赖已就绪 · %.1fs' % (count, time.monotonic()-started), fg='green')
    if install:
        click.echo('项目已安装到当前 Python 环境。')


def sync_project(path, install=False, migrate_windows_lock=False):
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
        migrations = []
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
                git_count += sync_projects(directory, source_config, migrate_windows_lock=migrate_windows_lock,
                                           migration_report=migrations)
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
            find_and_configure_behavior_pack(str(path), config, quiet=True)
            write_project(path, config)
        if install:
            proc = subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-input', '-e', str(path)],
                                  capture_output=True, text=True)
            if proc.returncode:
                raise click.ClickException(proc.stderr or proc.stdout or '项目安装失败')
    return {'project': str(path), 'installed': install, 'code_libraries': library_count,
            'git_projects': git_count, 'git_lock_migrations': migrations}

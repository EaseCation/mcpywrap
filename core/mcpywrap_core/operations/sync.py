"""Shared dependency synchronization; CLI is only presentation."""
import subprocess
import sys
from pathlib import Path
from ..command_context import project_scope
from ..dependencies import read_project, write_project
from ..host import run_command, tool_python


def sync_project(path, install=False, migrate_windows_lock=False, bundled_only=False):
    from ..project_scripts import project_lock
    with project_lock(path, force=True):
        return _sync_project(path, install, migrate_windows_lock, bundled_only=bundled_only)


def _sync_project(path, install=False, migrate_windows_lock=False, bundled_only=False):
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
        def sync_sources(directory, root=False):
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
                if entry.unbundled and (not root or bundled_only):
                    continue
                if entry.kind == 'local':
                    sync_sources(resolve_path(directory, entry.value))
                else:
                    target = DependencyManager().find_dependency_path(entry.value)
                    if target and 'mcpywrap' in read_project(target).get('tool', {}):
                        sync_sources(target)
            if git_declarations(directory, source_config) or Path(directory, GIT_LOCK_FILE).exists():
                git_count += sync_projects(directory, source_config, purpose="runtime" if root and not bundled_only else "release", consumer=not root)
            active.remove(key)
            visited.add(key)
        sync_sources(path, root=True)
        manager = DependencyService(path).resolve(purpose="release" if bundled_only else "runtime")
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
            proc = run_command([tool_python(), '-m', 'pip', 'install', '--no-input', '-e', str(path)],
                                  capture_output=True, text=True)
            if proc.returncode:
                raise ValueError(proc.stderr or proc.stdout or '项目安装失败')
    result = {'project': str(path), 'installed': install, 'code_libraries': library_count,
              'dependency_selection': manager.selection(), 'git_projects': git_count, 'git_lock_migrations': [], 'sources_synced': True}
    from ..consumer_prepare import PreparationPlan, guidance
    from ..prepare_environment import ensure_environment
    from ..project_scripts import ScriptError
    try:
        plan = PreparationPlan(path, resolved=manager)
        result['environment'] = ensure_environment(path, plan.requirements, plan.override)
        plan.check()
    except (ValueError, OSError) as exc:
        if isinstance(exc, ScriptError):
            exc.details.update(result, environment_ready=False)
            exc.args = ('依赖已恢复，消费者准备未就绪：' + str(exc),)
            raise
        from ..prepare_environment import PrepareError
        raise PrepareError('依赖已恢复，消费者工具环境未就绪：' + str(exc),
                           sources_synced=True, environment_ready=False) from exc
    result['preparation'] = guidance(path, resolved=manager)
    return result

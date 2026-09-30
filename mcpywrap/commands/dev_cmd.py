# -*- coding: utf-8 -*-

"""
开发命令模块
"""
import os
import queue
import threading
import time
from pathlib import Path
import click
from ..command_context import OperationCommand, project_dir as current_project, non_interactive, require_project
from ..config import get_mcpywrap_config, config_exists, read_config, get_project_type, CONFIG_FILE, ensure_map_setuptools_sync
from ..builders.watcher import ProjectWatcher
from .build_cmd import build

def file_change_callback(src_path, dest_path, success, output, is_python, is_dependency=False, dependency_name=None, event_type=None):
    """文件变化回调函数 - 展示处理结果"""
    # 显示文件变化来源
    if is_dependency:
        click.secho(f"\n📝 检测到依赖项目文件变化 {dependency_name} {src_path}", fg="bright_blue", nl=False)
    else:
        click.secho(f"\n📝 检测到文件变化 {src_path}", fg="bright_blue")
    
    # 处理其他事件（创建或修改）
    if success:
        click.secho(f'✅ 处理成功 {output}', fg="green")
    else:
        click.secho(f'❌ 处理失败 {output}', fg="red")


def changed_reload_targets(target_dir, changed_paths):
    from ..mcstudio.hot_reload import target_from_file
    targets = {}
    for path in changed_paths:
        parts = [part.lower() for part in os.path.normpath(path).split(os.sep)]
        kind = ('python' if path.lower().endswith('.py') else
                'ui' if 'ui' in parts and path.lower().endswith('.json') else
                'shader' if 'shaders' in parts else
                'material' if 'materials' in parts else
                'particle' if 'particles' in parts and path.lower().endswith('.json') else None)
        if not kind:
            continue
        try:
            target = target_from_file(target_dir, kind, path)
            targets[(kind, None if kind == 'ui' else target)] = path
        except ValueError as exc:
            click.secho('跳过热更: ' + str(exc), fg='yellow')
    return targets

@click.command(cls=OperationCommand)
@click.option('--reload-session', help='文件成功组装后热更指定的本地世界会话')
def dev_cmd(reload_session):
    """使用watch模式，实时构建为 MCStudio 工程，代码更新时，自动构建"""
    from ..command_context import json_output
    project = current_project()
    if json_output():
        raise click.UsageError("dev 持续输出文本日志，不支持 --json")
    if reload_session:
        from ..command_context import remote_url
        from ..mcstudio import sessions
        if remote_url():
            raise click.UsageError('热更监控仅支持 Windows 本地项目；请显式使用 --local')
        data = sessions.read(project, reload_session)
        if data.get('mode') != 'local' or data['state'] != 'running':
            raise click.UsageError('--reload-session 必须指向运行中的本地世界')
    if not config_exists():
        click.secho('❌ 错误: 未找到配置文件。请先运行 `mcpywrap init` 初始化项目。', fg="red")
        raise click.ClickException('无法启动开发监控')
    
    # 确保 map 项目的 setuptools 配置同步
    ensure_map_setuptools_sync(interactive=False)
    
    # 获取mcpywrap特定配置
    mcpywrap_config = get_mcpywrap_config()

    if get_project_type() == "addon":
        # 源代码目录固定为当前目录
        source_dir = str(current_project())
        # 目标目录从配置中读取
        target_dir = mcpywrap_config.get('target_dir')
        
        if not target_dir:
            click.secho('❌ 错误: 配置文件中未找到target_dir。请手动添加。', fg="red")
            raise click.ClickException('无法启动开发监控')
        
        # 转换为绝对路径
        target_dir = os.path.normpath(os.path.join(source_dir, target_dir))

        # 读取项目配置获取项目名和依赖项
        config = read_config(os.path.join(source_dir, CONFIG_FILE))
        project_name = config.get('project', {}).get('name', 'current_project')
        dependencies_list = config.get('project', {}).get('dependencies', [])
        
        # 实际构建
        suc = build(source_dir, target_dir)
        if not suc:
            click.secho("❌ 初始构建失败", fg="red")
            raise click.ClickException('无法启动开发监控')

        click.secho(f"🔍 开始监控代码变化，路径: ", fg="bright_blue", nl=False)
        click.secho(f"{source_dir}", fg="bright_cyan")
        
        # 创建项目监视器
        pending = queue.Queue()
        stop_reload = threading.Event()

        def changed(src, dest, success, output, is_python, is_dependency=False,
                    dependency_name=None, event_type=None):
            file_change_callback(src, dest, success, output, is_python, is_dependency,
                                 dependency_name, event_type)
            if reload_session and success and dest and event_type != 'deleted':
                pending.put(dest)

        def reload_loop():
            from ..mcstudio.hot_reload import reload_session as trigger, target_from_file
            while not stop_reload.is_set():
                try:
                    first = pending.get(timeout=.2)
                except queue.Empty:
                    continue
                changed_paths = {first}
                time.sleep(1.5)
                while True:
                    try:
                        changed_paths.add(pending.get_nowait())
                    except queue.Empty:
                        break
                # The game may still read its previous compiled module immediately after assembly.
                try:
                    snapshot = {p: (os.path.getmtime(p), os.path.getsize(p)) for p in changed_paths
                                if os.path.isfile(p)}
                except OSError:
                    pending.put(first)
                    continue
                time.sleep(.5)
                if stop_reload.is_set():
                    break
                try:
                    stable = all(os.path.isfile(p) and (os.path.getmtime(p), os.path.getsize(p)) == stat
                                 for p, stat in snapshot.items())
                except OSError:
                    stable = False
                if not stable:
                    pending.put(first)
                    continue
                targets = changed_reload_targets(target_dir, changed_paths)
                for (kind, target), path in sorted(targets.items()):
                    try:
                        source = Path(path).read_bytes() if kind == 'python' else None
                        result = trigger(project, reload_session, kind, target, source=source)
                        if result['state'] in ('completed', 'triggered'):
                            click.secho(f'已触发热更 {kind} {target}', fg='green')
                        else:
                            click.secho(f'热更失败 {kind} {target}: {result.get("error")}', fg='red')
                    except (OSError, ValueError) as exc:
                        click.secho(f'热更失败 {kind} {target}: {exc}', fg='red')

        project_watcher = ProjectWatcher(source_dir, target_dir, changed)
        
        # 设置监视器
        dep_count = project_watcher.setup_from_config(project_name, dependencies_list)
        
        if dep_count > 0:
            click.secho(f"✅ 找到并监控 {dep_count} 个依赖包", fg="green")
        
        # 启动监视
        project_watcher.start()
        reload_thread = None
        if reload_session:
            reload_thread = threading.Thread(target=reload_loop, daemon=True)
            reload_thread.start()
        
        try:
            click.secho("👀 监控中... 按 Ctrl+C 停止", fg="bright_magenta")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            project_watcher.stop()
            stop_reload.set()
            if reload_thread:
                reload_thread.join(timeout=1)
            click.secho("🛑 监控已停止", fg="bright_yellow")
            raise
    else:
        click.secho('❌ 暂未支持: 当前仅支持Addons项目的构建', fg="red")
        raise click.ClickException('无法启动开发监控')

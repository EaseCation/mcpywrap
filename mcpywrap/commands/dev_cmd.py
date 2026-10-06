# -*- coding: utf-8 -*-

"""
开发命令模块
"""
import os
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
@click.option('--reload-session', hidden=True, help='已迁移到 runtime watch --session')
def dev_cmd(reload_session):
    """监控项目文件变化，持续更新构建结果。"""
    from ..command_context import json_output
    project = current_project()
    if json_output():
        raise click.UsageError("dev 持续输出文本日志，不支持 --json")
    if reload_session:
        from .runtime_cmd import watch_cmd
        return watch_cmd.callback(session=reload_session)
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
        project_watcher = ProjectWatcher(source_dir, target_dir, file_change_callback)
        
        # 设置监视器
        dep_count = project_watcher.setup_from_config(project_name, dependencies_list)
        
        if dep_count > 0:
            click.secho(f"✅ 找到并监控 {dep_count} 个依赖包", fg="green")
        
        # 启动监视
        project_watcher.start()
        try:
            click.secho("👀 监控中... 按 Ctrl+C 停止", fg="bright_magenta")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            project_watcher.stop()
            click.secho("🛑 监控已停止", fg="bright_yellow")
            raise
    else:
        click.secho('❌ 暂未支持: 当前仅支持Addons项目的构建', fg="red")
        raise click.ClickException('无法启动开发监控')

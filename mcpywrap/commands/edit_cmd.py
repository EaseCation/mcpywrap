# -*- coding: utf-8 -*-

"""
项目编辑命令模块
"""

import click
from ..command_context import OperationCommand, project_dir as current_project, non_interactive, require_project
import os

from ..builders.AddonsPack import AddonsPack
from ..builders.dependency_manager import DependencyManager
from ..config import config_exists, read_config, get_project_type, get_project_name, get_project_dependencies
from ..mcstudio.mcs import *
from ..mcstudio.editor import open_editor, create_editor_config
from ..mcstudio.discovery import (
    discover_engines, require_resources, studio_installation, DiscoveryError, engine_options,
)
from ..utils.project_setup import find_and_configure_behavior_pack



@click.command(cls=OperationCommand)
@engine_options
@click.option("--detach", is_flag=True, help="启动编辑器后返回进程信息")
def edit_cmd(detach, **engine_overrides):
    """使用 MC Studio Editor 编辑器进行编辑"""
    if os.name != 'nt':
        raise click.ClickException('此界面仅支持 Windows 人工操作，不支持远程 GUI')
    # 检查项目是否已初始化
    if not config_exists():
        require_project()
    result = open_edit(str(current_project()), engine_overrides=engine_overrides, raise_errors=True)
    if result is False:
        raise click.ClickException('编辑器准备失败')
    return result

def open_edit(project_dir=None, engine_overrides=None, raise_errors=False):
    from ..dependencies import read_project
    from .run_cmd import _setup_dependencies
    base_dir = os.path.abspath(project_dir or str(current_project()))
    config = read_project(base_dir)
    project_name = config.get('project', {}).get('name', 'project')
    project_type = config.get('tool', {}).get('mcpywrap', {}).get('project_type', 'addon')
    try:
        engine = discover_engines(base_dir, engine_overrides).require_engine()
        require_resources(engine, 'editor')
        install_dir, issues = studio_installation('editor')
        if not install_dir:
            raise DiscoveryError('未找到编辑器安装资源: ' + '; '.join(issues))
    except DiscoveryError as exc:
        if raise_errors:
            raise
        click.echo(str(exc))
        return False
    all_packs = _setup_dependencies(project_name, base_dir)
    if all_packs is None:
        return False
    studio_config_path = os.path.join(base_dir, 'studio.json')
    addon_packs_dirs = []
    for pack in all_packs:
        addon_packs_dirs.append(pack.path)
    
    config = create_editor_config(
        project_name=project_name, project_dir=base_dir,
        is_map=project_type == 'map', addon_paths=addon_packs_dirs,
        engine=engine, engine_install_dir=install_dir)
    if not config:
        return False
    with open(studio_config_path, 'w', encoding='utf-8') as f:
        import json
        json.dump(config, f, indent=4, ensure_ascii=False)
    click.echo(click.style(f'✅ 编辑器配置文件已创建: {studio_config_path}', fg='green'))

    # 直接运行编辑器（使用外部终端运行）
    click.echo(click.style('🔧 正在启动编辑器...', fg='yellow'))

    editor_process = open_editor(studio_config_path, engine=engine)

    if not editor_process:
        return False

    # 等待游戏进程结束
    click.echo(click.style('✨ 编辑器已启动...', fg='bright_green', bold=True))
    from ..mcstudio.processes import identity
    return {'application': 'editor', 'project': base_dir, **identity(editor_process.pid)}

    # 先不阻塞，因为用户可能还需要直接run
    # click.echo(click.style('⏱️ 按 Ctrl+C 可以中止等待', fg='yellow'))

    # try:
    #     # 等待游戏进程结束
    #     editor_process.wait()
    #     click.echo(click.style('👋 编辑器已退出', fg='bright_cyan', bold=True))
    # except KeyboardInterrupt:
    #     # 捕获 Ctrl+C，但不终止游戏进程
    #     click.echo(click.style('\n🛑 收到中止信号，脚本将退出但游戏继续运行', fg='yellow'))
    
def _print_dependency_tree(node, level):
    """打印依赖树结构"""
    indent = "  " * level
    if level == 0:
        click.secho(f"{indent}└─ {node.name} (主项目)", fg="bright_cyan")
    else:
        click.secho(f"{indent}└─ {node.name}", fg="cyan")

    for child in node.children:
        _print_dependency_tree(child, level + 1)

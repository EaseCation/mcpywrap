# -*- coding: utf-8 -*-

"""
项目编辑命令模块
"""

import click
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

base_dir = os.getcwd()


@click.command()
@engine_options
def edit_cmd(**engine_overrides):
    """使用 MC Studio Editor 编辑器进行编辑"""
    # 检查项目是否已初始化
    if not config_exists():
        click.echo(click.style('❌ 项目尚未初始化，请先运行 mcpy init', fg='red', bold=True))
        return
    if open_edit(engine_overrides=engine_overrides) is False:
        raise click.ClickException('编辑器准备失败')

def open_edit(project_dir=None, engine_overrides=None):
    from ..dependencies import read_project
    from .run_cmd import _setup_dependencies
    base_dir = os.path.abspath(project_dir or os.getcwd())
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

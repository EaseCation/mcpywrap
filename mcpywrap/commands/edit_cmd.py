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
from ..utils.project_setup import find_and_configure_behavior_pack

base_dir = os.getcwd()


@click.command()
def edit_cmd():
    """使用 MC Studio Editor 编辑器进行编辑"""
    # 检查项目是否已初始化
    if not config_exists():
        click.echo(click.style('❌ 项目尚未初始化，请先运行 mcpy init', fg='red', bold=True))
        return
    open_edit()

def open_edit():
    # 读取项目配置
    config = read_config()

    project_name = get_project_name()
    project_type = get_project_type()
    
    studio_config_path = os.path.join(base_dir, "studio.json")

    # 创建一个新的配置文件
    click.echo(click.style('📝 正在创建编辑器配置文件...', fg='yellow'))
    all_packs: list[AddonsPack] = []

    if project_type == 'addon':
        # 查找当前项目的行为包
        behavior_pack_dir, resource_pack_dir = find_and_configure_behavior_pack(base_dir, config)
        if not behavior_pack_dir:
            click.echo(click.style('❌ 未找到行为包目录，请检查项目结构', fg='red', bold=True))
            return
        # 创建主包实例
        main_pack = AddonsPack(project_name, base_dir, is_origin=True)
        all_packs.append(main_pack)

    # 解析依赖包
    dependency_manager = DependencyManager()
    dependencies = get_project_dependencies()

    if dependencies:
        click.secho('📦 正在解析依赖包...', fg='blue')

        # 构建依赖树
        dependency_manager.build_dependency_tree(
            project_name,
            base_dir,
            dependencies
        )

        # 获取所有依赖
        dependency_map = dependency_manager.get_all_dependencies()
        dependency_packs = list(dependency_map.values())

        if dependency_packs:
            click.secho(f'✅ 成功解析 {len(dependency_packs)} 个依赖包', fg='green')

            # 打印依赖树结构
            click.secho('📊 依赖关系:', fg='cyan')
            root_node = dependency_manager.get_dependency_tree()
            if root_node:
                _print_dependency_tree(root_node, 0)
        else:
            click.secho('ℹ️ 没有找到可用的依赖包', fg='cyan')
    else:
        click.secho('ℹ️ 项目没有声明依赖包', fg='cyan')
        dependency_packs = []

    all_packs += dependency_packs

    addon_packs_dirs = []
    for pack in all_packs:
        addon_packs_dirs.append(pack.path)
    
    with open(studio_config_path, 'w', encoding='utf-8') as f:
        config = create_editor_config(
            project_name=project_name,
            project_dir=base_dir,
            is_map=project_type == 'map',
            addon_paths=addon_packs_dirs,
        )
        # json写入
        import json
        json.dump(config, f, indent=4, ensure_ascii=False)
        click.echo(click.style(f'✅ 编辑器配置文件已创建: {studio_config_path}', fg='green'))
    
    # 直接运行编辑器（使用外部终端运行）
    click.echo(click.style('🔧 正在启动编辑器...', fg='yellow'))

    editor_process = open_editor(studio_config_path)

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
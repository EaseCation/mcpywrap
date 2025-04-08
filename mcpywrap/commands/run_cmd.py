# -*- coding: utf-8 -*-

"""
项目运行命令模块
"""
import subprocess

import click
import os
import json
import uuid

from future.moves import sys

from ..builders import DependencyManager
from ..config import config_exists, read_config, get_project_dependencies
from ..builders.AddonsPack import AddonsPack
from ..mcstudio.game import open_game, open_safaia
from ..mcstudio.mcs import *
from ..mcstudio.runtime_cppconfig import gen_runtime_config
from ..mcstudio.studio_server_ui import run_studio_server_ui, run_studio_server_ui_subprocess
from ..mcstudio.symlinks import setup_addons_symlinks
from ..utils.project_setup import find_and_configure_behavior_pack
from ..utils.utils import ensure_dir

@click.command()
def run_cmd():
    """以开发模式运行游戏测试"""
    # 检查项目是否已初始化
    if not config_exists():
        click.echo(click.style('❌ 项目尚未初始化，请先运行 mcpy init', fg='red', bold=True))
        return

    # 读取项目配置
    config = read_config()
    base_dir = os.getcwd()

    # 创建运行时配置目录
    runtime_dir = os.path.join(base_dir, ".runtime")
    ensure_dir(runtime_dir)

    # 获取MC Studio安装目录
    mcs_download_dir = get_mcs_download_path()
    if not mcs_download_dir:
        click.echo(click.style('❌ 未找到MC Studio下载目录，请确保已安装MC Studio', fg='red', bold=True))
        return

    # 获取游戏引擎版本
    engine_dirs = get_mcs_game_engine_dirs()
    if not engine_dirs:
        click.echo(click.style('❌ 未找到MC Studio游戏引擎，请确保已安装MC Studio', fg='red', bold=True))
        return

    # 使用最新版本的引擎
    latest_engine = engine_dirs[0]
    click.echo(click.style(f'🎮 使用引擎版本: {latest_engine}', fg='cyan'))

    # 查找当前项目的行为包
    behavior_pack_dir, resource_pack_dir = find_and_configure_behavior_pack(base_dir, config)
    if not behavior_pack_dir:
        click.echo(click.style('❌ 未找到行为包目录，请检查项目结构', fg='red', bold=True))
        return

    # 创建主包实例
    main_pack = AddonsPack(config.get('project', {}).get('name', 'main'), base_dir, is_origin=True)

    # 解析依赖包
    dependency_manager = DependencyManager()
    dependencies = get_project_dependencies()

    if dependencies:
        click.secho('📦 正在解析依赖包...', fg='blue')

        # 构建依赖树
        dependency_manager.build_dependency_tree(
            config.get('project', {}).get('name', 'main'),
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

    # 设置软链接
    all_packs = [main_pack] + dependency_packs
    link_suc, behavior_links, resource_links = setup_addons_symlinks(all_packs)

    if not link_suc:
        click.echo(click.style('❌ 软链接创建失败，请检查权限', fg='red', bold=True))
        return

    config_path = os.path.join(runtime_dir, "runtime.cppconfig")

    # 获取原始配置
    if not os.path.isfile(config_path):
        # 生成唯一的世界ID
        level_id = str(uuid.uuid4())
    else:
        # 读取配置文件
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            level_id = config_data.get('world_info', {}).get('level_id', str(uuid.uuid4()))

    # 生成世界名称
    world_name = f"{config.get('project', {}).get('name', 'MyWorld')}"

    # 生成运行时配置
    runtime_config = gen_runtime_config(
        latest_engine,
        world_name,
        level_id,
        mcs_download_dir,
        main_pack.pkg_name,
        behavior_links,
        resource_links
    )

    # 写入配置文件

    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(runtime_config, f, ensure_ascii=False, indent=2)

    click.echo(click.style('📝 配置文件已生成', fg='green'))

    logging_port = 8678

    # 启动游戏
    click.echo(click.style('🚀 正在启动游戏...', fg='bright_blue', bold=True))
    game_process = open_game(config_path, logging_port=logging_port)

    if game_process is None:
        click.echo(click.style('❌ 游戏启动失败', fg='red', bold=True))
        return

    # 启动studio_logging_server
    run_studio_server_ui_subprocess(port=logging_port)

    # 启动日志与调试工具
    open_safaia()

    # 等待游戏进程结束
    click.echo(click.style('✨ 游戏已启动，正在运行中...', fg='bright_green', bold=True))
    click.echo(click.style('⏱️ 按 Ctrl+C 可以中止等待', fg='yellow'))

    try:
        # 等待游戏进程结束
        game_process.wait()
        click.echo(click.style('👋 游戏已退出', fg='bright_cyan', bold=True))
    except KeyboardInterrupt:
        # 捕获 Ctrl+C，但不终止游戏进程
        click.echo(click.style('\n🛑 收到中止信号，脚本将退出但游戏继续运行', fg='yellow'))

def _print_dependency_tree(node, level):
    """打印依赖树结构"""
    indent = "  " * level
    if level == 0:
        click.secho(f"{indent}└─ {node.name} (主项目)", fg="bright_cyan")
    else:
        click.secho(f"{indent}└─ {node.name}", fg="cyan")

    for child in node.children:
        _print_dependency_tree(child, level + 1)
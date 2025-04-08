# -*- coding: utf-8 -*-

"""
项目编辑命令模块
"""

import click
import os
import subprocess

from ..config import config_exists, read_config, get_project_type, get_project_name
from ..mcstudio.mcs import *
from ..mcstudio.editor import open_editor


@click.command()
def edit_cmd():
    """使用 MC Studio Editor 编辑器进行编辑"""
    # 检查项目是否已初始化
    if not config_exists():
        click.echo(click.style('❌ 项目尚未初始化，请先运行 mcpy init', fg='red', bold=True))
        return

    # 读取项目配置
    config = read_config()
    base_dir = os.getcwd()

    project_name = get_project_name()
    project_type = get_project_type()
    
    studio_config_path = os.path.join(base_dir, "studio.json")

    if not os.path.exists(studio_config_path):
        # TODO 按照向导，创建一个新的配置文件
        click.echo(click.style('📝 正在创建编辑器配置文件...', fg='yellow'))
        with open(studio_config_path, 'w', encoding='utf-8') as f:
            f.write('{}')
        return
    
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
    

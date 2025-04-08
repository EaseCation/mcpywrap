# -*- coding: utf-8 -*-

import os
import click

from ..minecraft.addons import is_minecraft_addon_project
from ..minecraft.template.mod_template import open_ui_crate_mod
from ..utils.project_setup import find_behavior_pack_dir

base_dir = os.getcwd()


@click.command()
def mod_cmd():
    """ 向导式创建 Python Mod 基础框架 """
    
    if is_minecraft_addon_project(base_dir):
        behavior_pack_dir = find_behavior_pack_dir(base_dir)
        if behavior_pack_dir:
            open_ui_crate_mod(behavior_pack_dir)
            click.echo(click.style('✅ Mod UI 创建成功！', fg='green'))
        else:
            click.echo(click.style('❌ 未找到行为包目录，请先使用 mcpy init 命令初始化项目', fg='red'))
    else:
        # 未检测到，需要先使用mcpy init
        click.echo(click.style('❌ 未检测到 Minecraft Addon 项目结构，请先使用 mcpy init 命令初始化项目', fg='red'))
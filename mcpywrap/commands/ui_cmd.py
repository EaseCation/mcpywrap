# -*- coding: utf-8 -*-
import os
import click

from rich.console import Console
from ..config import config_exists

base_dir = os.getcwd()
console = Console()


@click.command()
def ui_cmd():
    """启动图形界面"""
    # 检查项目是否已初始化
    if not config_exists():
        console.print("❌ 项目尚未初始化，请先运行 mcpy init", style="red bold")
        return
    
    from ..ui.project_ui import show_run_ui
    # 显示图形界面
    show_run_ui(base_dir)


# -*- coding: utf-8 -*-
import os
import click
from ..command_context import OperationCommand, project_dir as current_project, non_interactive, require_project

from rich.console import Console
from ..config import config_exists

console = Console()


@click.command(cls=OperationCommand)
def ui_cmd():
    """启动图形界面"""
    from ..command_context import json_output
    if non_interactive() or json_output():
        raise click.UsageError("Qt 管理页仅供人工使用；Agent 请调用 run、add、remove 等命令")
    # 检查项目是否已初始化
    if not config_exists():
        require_project()
    
    from ..ui.project_ui import show_run_ui
    # 显示图形界面
    show_run_ui(str(current_project()))


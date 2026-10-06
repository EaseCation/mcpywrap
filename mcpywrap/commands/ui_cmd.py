# -*- coding: utf-8 -*-
import os
import click
from ..command_context import OperationCommand, project_dir as current_project, non_interactive, require_project

from rich.console import Console
from ..config import config_exists

console = Console()


@click.command(cls=OperationCommand)
@click.option('--mcs-auth', is_flag=True, help='本次 GUI 单人测试使用已登录的 MC Studio 身份')
def ui_cmd(mcs_auth=False):
    """启动图形界面"""
    from ..command_context import json_output
    if non_interactive() or json_output():
        raise click.UsageError("Qt 管理页仅供人工使用；Agent 请调用 run、add、remove 等命令")
    from ..engines.backend import get_backend
    backend = get_backend()
    if 'project-ui' not in backend.capabilities:
        raise click.ClickException('本机后端暂不支持项目界面')
    if mcs_auth and 'mcs-auth' not in backend.capabilities:
        raise click.UsageError('当前后端不支持 MC Studio 登录身份')
    # 检查项目是否已初始化
    if not config_exists():
        require_project()

    from ..dependencies import read_project
    if 'server' in read_project(current_project()).get('tool', {}).get('mcpywrap', {}):
        raise click.UsageError('服务器目标暂不支持 GUI，请使用 mcpy run')
    
    from ..ui.project_ui import show_run_ui
    # 显示图形界面
    show_run_ui(str(current_project()), mcs_auth=mcs_auth)


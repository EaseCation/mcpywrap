"""显式维护项目，无隐式初始化或 SDK 安装。"""
import subprocess
import sys
import time
from pathlib import Path
import click
from ..command_context import OperationCommand, project_dir, require_project, project_scope, json_output
from ..api import Core
from ..operations.sync import sync_project, _sync_project


@click.command(cls=OperationCommand)
@click.option('--install', is_flag=True, help='同时在当前工具环境中可编辑安装项目')
@click.option('--bundled-only', is_flag=True, help='仅恢复随发布的依赖，保留 unbundled 依赖的锁记录')
@click.option('--migrate-windows-lock', is_flag=True, hidden=True)
def sync_cmd(install, migrate_windows_lock=False, bundled_only=False):
    """同步包配置；--install 安装到 mcpy 工具环境，不安装到游戏。"""
    require_project()
    started = time.monotonic()
    click.echo('同步依赖…', err=True)
    result = Core().execute('sync', project_dir(), install=install, migrate_windows_lock=migrate_windows_lock, bundled_only=bundled_only)
    if json_output():
        return result
    from ..dependency_feedback import report_selection
    report_selection(result.get('dependency_selection'))
    count = result['git_projects'] + result['code_libraries']
    click.secho('完成 · %d 个源码依赖已就绪 · %.1fs' % (count, time.monotonic()-started), fg='green')
    if install:
        click.echo('项目已安装到当前 Python 环境。')
    if result['environment']['state'] == 'ready':
        click.echo('消费者工具环境：%s（Python %s）' %
                   (result['environment']['python'], result['environment']['version']))

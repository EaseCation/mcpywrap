"""显式维护项目，无隐式初始化或 SDK 安装。"""
import subprocess
import sys
import click
from ..command_context import OperationCommand, project_dir, require_project, project_scope
from ..dependencies import read_project, write_project


@click.command(cls=OperationCommand)
@click.option('--install', is_flag=True, help='同时在当前工具环境中可编辑安装项目')
def sync_cmd(install):
    """同步包配置；--install 安装到 mcpy 工具环境，不安装到游戏。"""
    require_project()
    return sync_project(project_dir(), install)


def sync_project(path, install=False):
    from ..config import ensure_map_setuptools_sync
    from ..utils.project_setup import find_and_configure_behavior_pack
    with project_scope(path):
        config = read_project(path)
        kind = config.get('tool', {}).get('mcpywrap', {}).get('project_type', 'addon')
        if kind == 'map':
            ensure_map_setuptools_sync(interactive=False)
        else:
            find_and_configure_behavior_pack(str(path), config)
            write_project(path, config)
        if install:
            proc = subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-input', '-e', str(path)],
                                  capture_output=True, text=True)
            if proc.returncode:
                raise click.ClickException(proc.stderr or proc.stdout or '项目安装失败')
    return {'project': str(path), 'installed': install}

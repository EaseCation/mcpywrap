"""交互入口复用初始化与项目同步。"""
import click
from ..command_context import OperationCommand, project_dir, non_interactive
from .init_cmd import init
from .sync_cmd import sync_project


@click.command(cls=OperationCommand)
def default_cmd():
    if non_interactive():
        raise click.UsageError('请明确指定 init 或 sync 子命令')
    if not (project_dir() / 'pyproject.toml').exists():
        return init()
    return sync_project(project_dir(), install=True)

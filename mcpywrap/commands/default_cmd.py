"""交互入口复用初始化与项目终端菜单。"""
import click
from ..command_context import OperationCommand, project_dir, non_interactive
from .init_cmd import init


@click.command(cls=OperationCommand)
def default_cmd():
    if non_interactive():
        raise click.UsageError('请明确指定 init 或 sync 子命令')
    if not (project_dir() / 'pyproject.toml').exists():
        return init()
    from ..engines.tui import menu
    return menu()

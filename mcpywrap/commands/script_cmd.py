"""Explicit local project scripts, separate from game run and runtime Python."""
import click
from ..command_context import OperationCommand, project_dir, require_project
from ..project_scripts import configuration, operation


@click.group()
def script_cmd():
    """列出或执行当前项目的有限宿主脚本。"""


@script_cmd.command(name='list', cls=OperationCommand, local_only=True)
def list_cmd():
    """只读列出脚本与生命周期绑定。"""
    require_project()
    scripts, hooks = configuration(project_dir())
    return {'scripts': [{'name': name, 'command': spec['command'], 'timeout': spec['timeout'],
                         'hooks': [event for event, names in hooks.items() if name in names]}
                        for name, spec in scripts.items()]}


@script_cmd.command(name='run', cls=OperationCommand, local_only=True)
@click.argument('name')
@click.argument('args', nargs=-1, type=click.UNPROCESSED)
def run_cmd(name, args):
    """执行一次脚本；在 -- 之后传递脚本参数。"""
    require_project()
    with operation(project_dir(), task=name, args=args) as results:
        return {'scripts': results}

# -*- coding: utf-8 -*-

import click
from copy import copy
from . import __version__
from .command_context import OperationGroup, configure_context

from .commands.run_cmd import run_cmd
from .commands.connect_cmd import connect_cmd
from .commands.init_cmd import init_cmd
from .commands.add_cmd import add_cmd
from .commands.remove_cmd import remove_cmd
from .commands.build_cmd import build_cmd
from .commands.dev_cmd import dev_cmd
from .commands.package_cmd import package_cmd
from .commands.publish_cmd import publish_cmd
from .commands.default_cmd import default_cmd
from .commands.modsdk_cmd import modsdk_cmd
from .commands.mod_cmd import mod_cmd
from .commands.edit_cmd import edit_cmd
from .commands.ui_cmd import ui_cmd
from .commands.doctor_cmd import doctor_cmd
from .commands.engine_cmd import engine_cmd
from .commands.sync_cmd import sync_cmd
from .commands.session_cmd import status_cmd, logs_cmd, stop_cmd
from .commands.runtime_cmd import py_cmd, reload_cmd, runtime_cmd


@click.group(cls=OperationGroup, invoke_without_command=True)
@click.option("--project", type=click.Path(file_okay=False), help="项目目录，默认当前目录")
@click.option("--non-interactive", is_flag=True, help="不读取终端输入")
@click.option("--json", "json_output", is_flag=True, help="输出 JSON 结果")
@click.option('--remote', help='Windows 测试服务地址，例如 http://192.168.1.20:18765')
@click.option('--local', 'local_only', is_flag=True, help='本次强制本机执行')
@click.version_option(__version__)
@click.pass_context
def cli(ctx, project, non_interactive, json_output, remote, local_only):
    """mcpywrap - 《我的世界》中国版 依赖管理与项目构建工具"""
    configure_context(project, non_interactive, remote, local_only)
    # 如果没有提供子命令，则运行 default_cmd
    if ctx.invoked_subcommand is None:
        # 导入并运行默认命令
        from .command_context import non_interactive as unattended
        if unattended():
            raise click.UsageError("请指定子命令，例如 doctor、init 或 sync")
        return default_cmd.callback()

# 注册其他子命令
cli.add_command(modsdk_cmd, name='modsdk')
cli.add_command(init_cmd, name='init')
cli.add_command(add_cmd, name='add')
cli.add_command(remove_cmd, name='remove')
cli.add_command(build_cmd, name='build')
cli.add_command(dev_cmd, name='dev')
cli.add_command(package_cmd, name='package')
cli.add_command(publish_cmd, name='publish')
cli.add_command(mod_cmd, name='mod')
cli.add_command(run_cmd, name='run')
cli.add_command(connect_cmd, name='connect')
cli.add_command(edit_cmd, name='edit')
cli.add_command(ui_cmd, name='ui')
cli.add_command(doctor_cmd, name='doctor')
cli.add_command(engine_cmd)
cli.add_command(sync_cmd, name='sync')
cli.add_command(status_cmd)
cli.add_command(logs_cmd)
cli.add_command(stop_cmd)
cli.add_command(runtime_cmd)
for old_command in (py_cmd, reload_cmd):
    alias = copy(old_command)
    alias.hidden = True
    alias.deprecated = True
    cli.add_command(alias)

from .commands.desktop_cmd import screenshot_cmd, key_cmd, mouse_cmd, input_sequence_cmd
key_cmd.hidden = mouse_cmd.hidden = input_sequence_cmd.hidden = True
from .commands.serve_cmd import serve_cmd
cli.add_command(screenshot_cmd, 'screenshot')
cli.add_command(key_cmd, 'key')
cli.add_command(mouse_cmd, 'mouse')
cli.add_command(input_sequence_cmd)
cli.add_command(serve_cmd, 'serve')
from .commands.record_cmd import record_cmd
cli.add_command(record_cmd)

if __name__ == '__main__':
    cli()

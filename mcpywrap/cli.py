# -- coding: utf-8 -*-

import click
from .commands.init_cmd import init_cmd
from .commands.install_cmd import install_cmd
from .commands.build_cmd import build_cmd
from .commands.dev_cmd import dev_cmd
from .commands.publish_cmd import publish_cmd
from .commands.default_cmd import default_cmd
from .commands.modsdk_cmd import modsdk_cmd

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """mcpywrap - 《我的世界》中国版 依赖管理与项目构建工具"""
    # 如果没有提供子命令，则运行 default_cmd
    if ctx.invoked_subcommand is None:
        # 导入并运行默认命令
        default_cmd()

# 注册其他子命令
cli.add_command(modsdk_cmd, name='modsdk')
cli.add_command(init_cmd, name='init')
cli.add_command(install_cmd, name='install')
cli.add_command(build_cmd, name='build')
cli.add_command(dev_cmd, name='dev')
cli.add_command(publish_cmd, name='publish')

if __name__ == '__main__':
    cli()
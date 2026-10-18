# -*- coding: utf-8 -*-

import click
from copy import copy
from . import __version__
from .command_context import OperationGroup, configure_context

COMMANDS = {
    name: (name + '_cmd', name + '_cmd') for name in
    ('modsdk', 'init', 'add', 'remove', 'build', 'dev', 'package', 'publish',
     'mod', 'run', 'connect', 'edit', 'ui', 'doctor', 'engine', 'sync', 'serve', 'record', 'script')
}
COMMANDS.update({name: ('session_cmd', name + '_cmd') for name in ('status', 'logs', 'stop', 'restart')})
COMMANDS.update({name: ('runtime_cmd', name + '_cmd') for name in ('runtime', 'py', 'reload')})
COMMANDS.update({name: ('desktop_cmd', name.replace('-', '_') + '_cmd')
                 for name in ('screenshot', 'key', 'mouse', 'input-sequence')})


class CommandGroup(OperationGroup):
    """Load only the selected command; status must not import build tooling."""

    def list_commands(self, ctx):
        return sorted(set(COMMANDS) | set(self.commands))

    def get_command(self, ctx, name):
        if name not in self.commands and name in COMMANDS:
            from importlib import import_module
            module, attribute = COMMANDS[name]
            command = getattr(import_module('.commands.' + module, __package__), attribute)
            if name in ('py', 'reload'):
                command = copy(command)
                command.hidden = command.deprecated = True
            elif name in ('key', 'mouse', 'input-sequence'):
                command.hidden = True
            self.add_command(command, name)
        return super().get_command(ctx, name)


@click.group(cls=CommandGroup, invoke_without_command=True)
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
        from .commands.default_cmd import default_cmd
        return default_cmd.callback()

if __name__ == '__main__':
    cli()

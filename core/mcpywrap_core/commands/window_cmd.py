"""运行中游戏窗口的尺寸查询与调整；--remote 时在远程 Windows 执行端操作。"""
import click

from ..command_context import OperationCommand, project_dir, remote_url
from ..runtime import game_window


class WindowCommand(OperationCommand):
    def invoke(self, ctx):
        ctx.params.pop('json_output', None)
        from ..mobile_host import profiles
        if profiles.select(project_dir()) is not None:
            raise click.UsageError('此工作区绑定 mcpy App，游戏画面由 App 决定，不支持窗口尺寸操作')
        if remote_url():
            from ..remote.client import routed_window
            return routed_window(ctx.info_name, ctx.params)
        return click.Command.invoke(self, ctx)


def parse(ctx, param, value):
    try:
        return game_window.parse_size(value)
    except ValueError as error:
        raise click.BadParameter(str(error)) from None


@click.group(name='window')
def window_cmd():
    """查询或调整游戏窗口客户区像素尺寸（决定画面分辨率），经系统窗口 API，不激活窗口。"""


@window_cmd.command(cls=WindowCommand, name='info')
@click.option('--session', required=True)
def info_cmd(session):
    """当前客户区像素尺寸、显示缩放及全屏/最小化状态；附启动时请求的尺寸及其结果。"""
    return game_window.info(project_dir(), session)


@window_cmd.command(cls=WindowCommand, name='resize')
@click.option('--session', required=True)
@click.option('--size', required=True, callback=parse, metavar='WxH', help='客户区像素尺寸，例如 1280x720')
def resize_cmd(session, size):
    """调整客户区并核对实际尺寸；保持窗口位置。macOS 需要“辅助功能”授权，录制中拒绝。"""
    return game_window.resize(project_dir(), session, *size)

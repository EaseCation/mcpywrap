"""无项目、无登录身份的临时网络连接。"""
import click

from ..command_context import OperationCommand
from ..mcstudio.discovery import engine_options
from ..mcstudio.network import ServerTarget, run_network


@click.command(cls=OperationCommand)
@engine_options
@click.argument('host')
@click.option('--port', type=click.IntRange(1, 65535), default=19132, show_default=True)
def connect_cmd(host, port, **engine_overrides):
    """尝试未认证连接服务器；前台采集日志，Ctrl+C 结束本次游戏。

    不读取项目配置或登录身份，不装配本地 Mod，不保证服务器接受连接。
    """
    return run_network(ServerTarget(host, port), engine_overrides=engine_overrides)

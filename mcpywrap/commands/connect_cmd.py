"""无项目的临时网络连接，可显式使用 MCS 当前身份。"""
import click

from ..command_context import OperationCommand
from ..mcstudio.discovery import engine_options
from ..mcstudio.network import ServerTarget


@click.command(cls=OperationCommand)
@engine_options
@click.argument('host')
@click.option('--port', type=click.IntRange(1, 65535), default=19132, show_default=True)
@click.option('--mcs-auth', is_flag=True, help='本次连接使用已登录的 MC Studio 身份')
@click.option('--detach', is_flag=True, help='后台连接并返回游戏会话；JSON 必须指定')
@click.option('--request-id', help='远程启动的 32 位十六进制请求 ID，用于找回或重试同一请求')
def connect_cmd(host, port, mcs_auth=False, detach=False, request_id=None, **engine_overrides):
    """尝试连接服务器；前台采集日志，Ctrl+C 结束本次游戏。

    默认不读取登录身份；--mcs-auth 要求 MCS 已登录及本机桥接可用。
    不读取项目配置，不装配本地 Mod，不保证服务器接受连接。
    """
    if request_id:
        raise click.UsageError('--request-id 仅用于远程启动')
    from ..engines.backend import get_backend
    from ..engines.host import EngineError
    backend = get_backend()
    target = ServerTarget(host, port, 'mcs' if mcs_auth else 'none')
    try:
        return backend.connect(target, engine_overrides=engine_overrides, detach=detach)
    except EngineError as error:
        if error.code != 'setup_required' or not backend.managed_install: raise
        from .engine_cmd import perform_install
        click.echo('首次运行：自动下载并准备本地游戏环境…', err=True)
        perform_install()
        return backend.connect(target, engine_overrides=engine_overrides, detach=detach)

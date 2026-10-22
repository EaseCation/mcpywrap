"""Manually hosted LAN endpoint in the logged-in Windows desktop."""
import os
from pathlib import Path
import click
from ..command_context import OperationCommand, json_output
from ..mcstudio.discovery import engine_options


@click.command(cls=OperationCommand)
@click.option('--host', default='0.0.0.0', show_default=True)
@click.option('--port', type=click.IntRange(1, 65535), default=18765, show_default=True)
@click.option('--data-dir', type=click.Path(file_okay=False), help='服务会话与日志目录')
@click.option('--no-token', is_flag=True, help='关闭访问令牌认证，仅用于可信网络；忽略 MCPY_REMOTE_TOKEN')
@engine_options
def serve_cmd(host, port, data_dir, no_token, **engine_overrides):
    """在当前 Windows 用户桌面启动局域网测试服务；Ctrl+C 清理所属游戏。"""
    if json_output():
        raise click.UsageError('serve 是持续服务，不支持 --json')
    if os.name != 'nt':
        raise click.ClickException('serve 只能在 Windows 交互桌面启动；macOS 请配置 --remote')
    token = None if no_token else os.environ.get('MCPY_REMOTE_TOKEN')
    if not no_token and not token:
        raise click.ClickException('serve 需要 MCPY_REMOTE_TOKEN；远程服务允许在游戏客户端执行 Python。可信网络可显式使用 --no-token')
    from ..remote.service import GameService, directory_lock
    from ..remote.http_server import GameHTTPServer
    root = Path(data_dir).expanduser().resolve() if data_dir else Path.home()/'.local/share/mcpywrap/remote'
    with directory_lock(root):
        service = GameService(root, {k: v for k, v in engine_overrides.items() if v is not None})
        try:
            with GameHTTPServer((host, port), service, token) as server:
                click.echo(f'测试服务: http://{host}:{port}\n数据目录: {root}\n'
                           f'访问令牌: {"已启用" if server.token else "未启用（--no-token；可访问此端口的设备均可执行游戏 Python）"}\n'
                           '保持桌面登录且未锁屏；Ctrl+C 停止服务及所属游戏。')
                try:
                    server.serve_forever(poll_interval=.2)
                except KeyboardInterrupt:
                    click.echo('正在取消输入并清理所属会话…')
        finally:
            service.close()

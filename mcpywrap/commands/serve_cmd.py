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
@engine_options
def serve_cmd(host, port, data_dir, **engine_overrides):
    """在当前 Windows 用户桌面启动局域网测试服务；Ctrl+C 清理所属游戏。"""
    if json_output():
        raise click.UsageError('serve 是持续服务，不支持 --json')
    if os.name != 'nt':
        raise click.ClickException('serve 只能在 Windows 交互桌面启动；macOS 请配置 --remote')
    from ..remote.service import GameService, directory_lock
    from ..remote.http_server import GameHTTPServer
    root = Path(data_dir).expanduser().resolve() if data_dir else Path.home()/'.local/share/mcpywrap/remote'
    with directory_lock(root):
        service = GameService(root, {k: v for k, v in engine_overrides.items() if v is not None})
        try:
            with GameHTTPServer((host, port), service, os.environ.get('MCPY_REMOTE_TOKEN')) as server:
                click.echo(f'测试服务: http://{host}:{port}\n数据目录: {root}\n'
                           f'访问令牌: {"已启用" if server.token else "未启用"}\n'
                           '保持桌面登录且未锁屏；Ctrl+C 停止服务及所属游戏。')
                try:
                    server.serve_forever(poll_interval=.2)
                except KeyboardInterrupt:
                    click.echo('正在取消输入并清理所属会话…')
        finally:
            service.close()

"""Session-bound game Python and local hot reload commands."""
from pathlib import Path
import click

from ..command_context import OperationCommand, project_dir


@click.group(name='runtime')
def runtime_cmd():
    """控制已启动的游戏会话：执行代码、热更和监控。"""


@click.command(cls=OperationCommand, name='capabilities')
@click.option('--session', required=True, help='已有的本地游戏会话 ID')
def capabilities_cmd(session):
    """只读查询当前会话可用的 Python、资源热更和纯命令控制入口。"""
    from ..command_context import remote_url
    if remote_url():
        raise click.UsageError('会话能力查询目前仅支持 --local；远端使用 doctor --capabilities，不回退本机。')
    from ..mcstudio.session_capabilities import inspect_session
    return inspect_session(project_dir(), session)


def code_argument(code, filename):
    if (code is None) == (filename is None):
        raise click.UsageError('必须且只能指定 --code 或 --file')
    if filename is not None:
        path = Path(filename).expanduser()
        code = path.read_text(encoding='utf-8-sig')
    return code


@click.command(cls=OperationCommand, name='py')
@click.option('--session', required=True, help='运行中的游戏会话 ID')
@click.option('--side', type=click.Choice(['client', 'server']), default='client', show_default=True)
@click.option('--code', help='游戏内执行的 Python 2 代码')
@click.option('--file', 'filename', type=click.Path(dir_okay=False), help='调用端的 UTF-8 脚本文件')
@click.option('--no-wait', is_flag=True, help='提交客户端请求后立即返回 request_id')
@click.option('--wait-until', help='客户端执行前等待的无副作用 Python 布尔表达式')
def py_cmd(session, side, code, filename, no_wait=False, wait_until=None):
    """在游戏 Python 环境执行代码，返回输出与结果。"""
    from ..mcstudio import sessions
    from ..mcstudio.runtime_debug import control_request
    source = code_argument(code, filename)
    data = sessions.read(project_dir(), session)
    if data.get('mode') == 'network' and side == 'server':
        raise click.UsageError('联机会话只能在客户端执行；服务器不属于此会话')
    if side == 'server' and (no_wait or wait_until is not None):
        raise click.UsageError('服务端继续走 Safaia，仅客户端支持请求队列和等待条件')
    options = {'condition': wait_until} if wait_until is not None else {}
    result = control_request(project_dir(), session, 'submit' if no_wait else 'execute', code=source, side=side, **options)
    return {'ok': result.get('state') in (('queued', 'running', 'completed') if no_wait else ('completed',)),
            'session': session, **result}


@click.command(cls=OperationCommand, name='py-result')
@click.argument('request_id')
@click.option('--session', required=True)
@click.option('--cancel', is_flag=True, help='仅取消尚未执行的客户端请求')
def py_result_cmd(request_id, session, cancel):
    """查询客户端请求结果；超时后使用原 request_id，不重复发送代码。"""
    from ..mcstudio.runtime_debug import control_request
    from ..command_context import remote_url
    if remote_url():
        raise click.UsageError('远程会话不支持客户端队列结果查询；不会读取本机会话。')
    result = control_request(project_dir(), session, 'python-cancel' if cancel else 'python-result', request_id=request_id)
    return {'ok': result.get('state') in ('completed', 'cancelled'), 'session': session, **result}


@click.command(cls=OperationCommand, name='reload')
@click.argument('kind', type=click.Choice(['python', 'ui', 'shader', 'material', 'particle']))
@click.option('--session', required=True, help='本地世界会话 ID')
@click.option('--file', 'filename', type=click.Path(dir_okay=False), help='当前项目内的目标文件')
@click.option('--module', help='Python 模块名，例如 MyMod.client.logic')
@click.option('--side', type=click.Choice(['client', 'server']), default='client', show_default=True,
              help='Python 执行端侧；资源热更仅支持 client')
def reload_cmd(kind, session, filename, module, side):
    """重载本地测试世界中的一个模块或资源。"""
    from ..command_context import remote_url
    from ..mcstudio.hot_reload import reload_session, target_from_file
    if remote_url():
        raise click.UsageError('远程联机会话暂不支持热更；本地世界请显式使用 --local')
    if module and (kind != 'python' or filename):
        raise click.UsageError('--module 仅可单独用于 Python 热更')
    if side == 'server' and kind != 'python':
        raise click.UsageError('--side server 仅适用于 Python 模块')
    if not filename and not module and kind != 'ui':
        raise click.UsageError('此热更类型需要 --file 或 --module')
    target = target_from_file(project_dir(), kind, filename) if filename else module
    source = Path(filename).read_bytes() if filename and kind == 'python' else None
    result = reload_session(project_dir(), session, kind, target, source=source, side=side)
    return {'ok': result.get('state') in ('completed', 'triggered'), 'session': session, **result}


@click.command(cls=OperationCommand, name='watch')
@click.option('--session', required=True, help='运行中的本地世界会话 ID')
@click.option('--side', type=click.Choice(['client', 'server', 'both']), default='client', show_default=True,
              help='自动热更端侧；both 仅适合可安全重复执行的公共模块')
def watch_cmd(session, side='client'):
    """监控项目文件，成功组装后更新该游戏会话。"""
    from ..command_context import remote_url, json_output
    from ..mcstudio.hot_reload import SessionWatcher
    import time
    if remote_url() or json_output():
        raise click.UsageError('watch 是本地持续日志命令，请使用 --local，不加 --json')
    watcher = SessionWatcher(project_dir(), session, lambda message, level: click.echo(message),
                             sides=('client', 'server') if side == 'both' else (side,))
    try:
        watcher.start()
        while watcher.thread.is_alive(): time.sleep(.2)
    except KeyboardInterrupt:
        click.echo('停止自动热更；游戏会话继续运行。')
    finally:
        watcher.stop()


runtime_cmd.add_command(capabilities_cmd)
runtime_cmd.add_command(py_cmd)
runtime_cmd.add_command(py_result_cmd)
runtime_cmd.add_command(reload_cmd)
runtime_cmd.add_command(watch_cmd)

from .runtime_ui_cmd import ui_cmd
runtime_cmd.add_command(ui_cmd)

from .runtime_player_cmd import player_cmd, install_cmd as install_runtime_cmd
runtime_cmd.add_command(player_cmd)
runtime_cmd.add_command(install_runtime_cmd, 'install')

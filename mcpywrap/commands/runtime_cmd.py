"""Session-bound game Python and local hot reload commands."""
from pathlib import Path
import click

from ..command_context import OperationCommand, project_dir


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
def py_cmd(session, side, code, filename):
    """在游戏 Python 环境执行代码，返回输出与结果。"""
    from ..mcstudio import sessions
    from ..mcstudio.runtime_debug import control_request
    source = code_argument(code, filename)
    data = sessions.read(project_dir(), session)
    if data.get('mode') == 'network' and side == 'server':
        raise click.UsageError('联机会话只能在客户端执行；服务器不属于此会话')
    result = control_request(project_dir(), session, 'execute', code=source, side=side)
    return {'ok': result.get('state') == 'completed', 'session': session, **result}


@click.command(cls=OperationCommand, name='reload')
@click.argument('kind', type=click.Choice(['python', 'ui', 'shader', 'material', 'particle']))
@click.option('--session', required=True, help='本地世界会话 ID')
@click.option('--file', 'filename', type=click.Path(dir_okay=False), help='当前项目内的目标文件')
@click.option('--module', help='Python 模块名，例如 MyMod.client.logic')
def reload_cmd(kind, session, filename, module):
    """重载本地测试世界中的一个模块或资源。"""
    from ..command_context import remote_url
    from ..mcstudio.hot_reload import reload_session, target_from_file
    if remote_url():
        raise click.UsageError('远程联机会话暂不支持热更；Windows 本地世界请显式使用 --local')
    if module and (kind != 'python' or filename):
        raise click.UsageError('--module 仅可单独用于 Python 热更')
    if not filename and not module and kind != 'ui':
        raise click.UsageError('此热更类型需要 --file 或 --module')
    target = target_from_file(project_dir(), kind, filename) if filename else module
    source = Path(filename).read_bytes() if filename and kind == 'python' else None
    result = reload_session(project_dir(), session, kind, target, source=source)
    return {'ok': result.get('state') in ('completed', 'triggered'), 'session': session, **result}

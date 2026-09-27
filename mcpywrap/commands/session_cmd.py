"""查询、读取和停止本项目的游戏会话。"""
import click
from ..command_context import OperationCommand, project_dir, json_output
from ..mcstudio import sessions


@click.command(cls=OperationCommand, name='status')
@click.option('--session', required=True)
def status_cmd(session):
    """查询会话；running 只表示进程存活。"""
    return sessions.read(project_dir(), session)


@click.command(cls=OperationCommand, name='logs')
@click.option('--session', required=True)
@click.option('--tail', type=click.IntRange(1, 10000), default=100, show_default=True)
def logs_cmd(session, tail):
    """读取会话日志末尾，不等待新日志。"""
    text = sessions.logs(project_dir(), session, tail)
    if json_output():
        return {'session': session, 'text': text}
    click.echo(text, nl=False)


@click.command(cls=OperationCommand, name='stop')
@click.option('--session', required=True)
def stop_cmd(session):
    """停止指定会话，核对进程身份，不按进程名批量停止。"""
    return sessions.stop(project_dir(), session)

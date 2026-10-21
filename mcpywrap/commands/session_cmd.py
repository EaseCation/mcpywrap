"""查询、读取和停止本项目的游戏会话。"""
import click
from ..command_context import OperationCommand, project_dir, json_output
from ..mcstudio import sessions


@click.command(cls=OperationCommand, name='status')
@click.option('--session')
@click.option('--group')
@click.option('--list', 'list_sessions', is_flag=True, help='列举会话，远端可用于找回启动结果')
def status_cmd(session, list_sessions, group=None):
    """查询会话；running 只表示进程存活。"""
    from ..runtime import groups
    if sum(map(bool, (session, group, list_sessions))) != 1:
        raise click.UsageError('指定 --session、--group 或 --list 中的一项')
    if group:
        return groups.refresh_status(project_dir(), group)
    if list_sessions:
        root = project_dir()/'.runtime/sessions'
        return {'sessions': [sessions.read(project_dir(), p.parent.name)
                             for p in sorted(root.glob('*/session.json'))], 'groups': groups.list_groups(project_dir())}
    return sessions.read(project_dir(), session)


@click.command(cls=OperationCommand, name='logs')
@click.option('--session')
@click.option('--group')
@click.option('--tail', type=click.IntRange(0, 10000), default=100, show_default=True)
@click.option('--source', type=click.Choice(['game', 'engine', 'worker', 'all']), default='game', show_default=True)
@click.option('--follow', is_flag=True, help='增量跟随日志，结束订阅不停止游戏（仅本机）')
@click.option('--format', 'output_format', type=click.Choice(['text', 'jsonl']), default='text', show_default=True)
def logs_cmd(session, tail, source, group=None, follow=False, output_format='text'):
    """读取日志快照，或使用 --follow 持续接收增量日志。"""
    target(session, group)
    if follow:
        if json_output():
            raise click.UsageError('--follow 是持续流；使用 --format jsonl，不加 --json')
        from ..mcstudio.log_stream import follow as events
        import json
        try:
            for item in events(project_dir(), session=session, group=group, source=source, tail=tail):
                if output_format == 'jsonl':
                    click.echo(json.dumps(item, ensure_ascii=True))
                elif item['event'] == 'log':
                    click.echo('[' + item['session'][:8] + ' ' + item['source'] + '] ' + item['text'], nl=False)
        except KeyboardInterrupt:
            pass
        return
    if source == 'all' or output_format != 'text' or tail == 0:
        raise click.UsageError('--source all、--format jsonl 和 --tail 0 仅用于 --follow')
    if group:
        from ..runtime import groups
        result = groups.logs(project_dir(), group, tail, source)
        if json_output():
            return result
        for item in result['logs']:
            for line in item['text'].splitlines():
                click.echo('[' + item['role'] + ' ' + item['session'][:8] + '] ' + line)
        return
    text = sessions.logs(project_dir(), session, tail, source)
    if json_output():
        return {'session': session, 'text': text}
    click.echo(text, nl=False)


@click.command(cls=OperationCommand, name='stop')
@click.option('--session')
@click.option('--group')
def stop_cmd(session, group=None):
    """停止指定会话，核对进程身份，不按进程名批量停止。"""
    target(session, group)
    if group:
        from ..runtime import groups
        return groups.stop(project_dir(), group)
    return sessions.stop(project_dir(), session)


def target(session, group):
    if bool(session) == bool(group):
        raise click.UsageError('指定 --session 或 --group 中的一项')


@click.command(cls=OperationCommand, name='restart')
@click.option('--session')
@click.option('--group')
def restart_cmd(session, group):
    """重试指定成员，或重新运行整个联调组。"""
    from ..runtime import groups
    from ..command_context import remote_url
    if remote_url():
        raise click.UsageError('restart 当前仅支持 --local，不会回退操作本机会话。')
    target(session, group)
    return groups.restart(project_dir(), session=session, group=group)

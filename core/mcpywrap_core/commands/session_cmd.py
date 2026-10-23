"""查询、读取和停止本项目的游戏会话。"""
import click
from ..command_context import OperationCommand, project_dir, json_output
from ..mcstudio import sessions
from ..mobile_host.options import HostOption, LogSource


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
@click.option('--source', type=LogSource(), default='game', show_default=True)
@click.option('--follow', is_flag=True, help='增量跟随日志，结束订阅不停止游戏（仅本机）')
@click.option('--format', 'output_format', type=click.Choice(['text', 'jsonl']), default='text', show_default=True)
@click.option('--filter', 'contains', type=click.STRING, help='区分大小写的字面文本匹配，先过滤再取 tail')
@click.option('--summary', is_flag=True, help='统计扫描范围内完全相同的消息，不推断错误等级')
@click.option('--since-ms', cls=HostOption, type=click.IntRange(min=0), help='起始 Unix 毫秒时间（需要宿主提供带时间戳日志）')
@click.option('--until-ms', cls=HostOption, type=click.IntRange(min=0), help='截止 Unix 毫秒时间（需要宿主提供带时间戳日志）')
def logs_cmd(session, tail, source, group=None, follow=False, output_format='text', contains=None, summary=False, since_ms=None, until_ms=None):
    """读取日志快照，或使用 --follow 持续接收增量日志。"""
    target(session, group)
    if source in ('client','server') or since_ms is not None or until_ms is not None:
        raise click.UsageError('本地文本日志未提供可靠端侧/时间戳；这些筛选需支持结构化日志的宿主')
    if summary and follow:
        raise click.UsageError('--summary 用于有限日志快照，不与 --follow 同用')
    if follow:
        if json_output():
            raise click.UsageError('--follow 是持续流；使用 --format jsonl，不加 --json')
        from ..mcstudio.log_stream import follow as events
        import json
        from ..mcstudio.log_query import StreamFilter
        filters = {}
        from contextlib import closing
        try:
            with closing(events(project_dir(), session=session, group=group, source=source, tail=tail, **({"contains":contains} if contains is not None else {}))) as stream:
                for item in stream:
                    if item.get('event') == 'reset': filters.pop((item.get('session'),item.get('source')),None)
                    if item.get('event') == 'log' and contains is not None:
                        key=(item.get('session'),item.get('source'))
                        item=dict(item,text=filters.setdefault(key,StreamFilter(contains)).feed(item['text']))
                        if not item['text']: continue
                    if item.get('event') == 'end':
                        for (sid,name), selection in filters.items():
                            remaining=selection.feed('',final=True)
                            if remaining:
                                if output_format=='jsonl': click.echo(json.dumps({'event':'log','session':sid,'source':name,'text':remaining},ensure_ascii=True))
                                else: click.echo('['+sid[:8]+' '+name+'] '+remaining,nl=False)
                    if output_format == 'jsonl':
                        click.echo(json.dumps(item, ensure_ascii=True))
                    elif item['event'] == 'log':
                        click.echo('[' + item['session'][:8] + ' ' + item['source'] + '] ' + item['text'], nl=False)
        except KeyboardInterrupt:
            pass
        return
    if contains is not None or summary:
        if output_format != 'text' or tail == 0: raise click.UsageError('日志快照需要 --tail 1..10000 和 --format text')
        from ..mcstudio.log_query import snapshot
        if group:
            from ..runtime.groups import read
            targets=[member['session'] for member in read(project_dir(),group)['members'] if member.get('session')]
        else: targets=[session]
        streams=[]
        for sid in targets:
            directory=sessions.session_path(project_dir(),sid)
            if not (directory/'session.json').is_file(): raise ValueError('会话不存在')
            for name in (('game','engine','worker') if source=='all' else (source,)):
                streams.append(dict(snapshot(directory/(name+'.log'),contains=contains,tail=tail,summary=summary),session=sid,source=name))
        if json_output():
            return streams[0] if len(streams)==1 else {'streams':streams}
        from ..mcstudio.log_query import show_snapshot
        show_snapshot({'streams':streams},summary)
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
@click.option('--launch-timeout', cls=HostOption, type=click.IntRange(5,120), default=None, help='App 宿主启动确认等待秒数')
def restart_cmd(session, group, launch_timeout=None):
    """重试指定成员，或重新运行整个联调组。"""
    if launch_timeout is not None: raise click.UsageError('当前执行目标不支持 --launch-timeout')
    from ..runtime import groups
    from ..command_context import remote_url
    if remote_url():
        raise click.UsageError('restart 当前仅支持 --local，不会回退操作本机会话。')
    target(session, group)
    return groups.restart(project_dir(), session=session, group=group)

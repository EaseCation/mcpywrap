"""Terminal presentation only; all actions use the existing public command layer."""
import time
import click
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel


def watch_session(project, session):
    from ..mcstudio import sessions
    console = Console()
    try:
        with Live(console=console, refresh_per_second=4) as live:
            while True:
                data = sessions.read(project, session)
                if data['state'] not in ('starting', 'running'): break
                from .backend import get_backend
                backend = get_backend(data.get('backend', 'windows'))
                table = Table.grid(padding=(0, 2))
                table.add_row('平台', backend.label)
                network = data.get('mode') == 'network'
                table.add_row('状态', ('已进入服务器' if data.get('connection_verified') else '正在连接服务器…')
                              if network else ('世界已就绪' if data.get('world_ready') else '引擎已启动，正在准备世界…'))
                table.add_row('会话', session)
                table.add_row('操作', 'Ctrl+C 停止游戏；其他终端可使用 logs / runtime py')
                live.update(Panel(table, title='mcpy 服务器测试' if network else 'mcpy 本地测试'))
                time.sleep(.25)
    except KeyboardInterrupt:
        console.print('正在停止游戏…')
        sessions.stop(project, session)
    data = sessions.read(project, session)
    if sessions.failed_exit(project, session, data):
        raise click.ClickException(data.get('error') or '游戏异常退出；请查看 logs --source engine')
    return {'session': session, 'state': 'exited', 'backend': data.get('backend', 'windows')}


def watch_group(project, result):
    """Observe both members; interrupt only sessions created by this command."""
    import codecs
    from contextlib import ExitStack
    from pathlib import Path
    from ..runtime import groups
    group, owned = result['group'], tuple(result.get('owned_sessions', ()))
    click.echo('联调组：' + group + '；Ctrl+C 停止本次创建的客户端，保留复用的游戏。')
    if result.get('hint'):
        click.echo(result['hint'])
    last_state = None
    tails = {}
    with ExitStack() as stack:
        try:
            while True:
                current = groups.status(project, group)
                if current['state'] != last_state:
                    click.echo('两名玩家已确认加入。' if current['state'] == 'ready' else
                               current.get('hint') or current['state'])
                    last_state = current['state']
                for member in current['members']:
                    sid, filename = member.get('session'), member.get('log_path')
                    if filename and sid not in tails and Path(filename).is_file():
                        tails[sid] = (stack.enter_context(Path(filename).open('rb')),
                                      codecs.getincrementaldecoder('utf-8')(errors='replace'), '')
                    if sid in tails:
                        stream, decoder, pending = tails[sid]
                        lines = (pending + decoder.decode(stream.read())).split('\n')
                        for line in lines[:-1]:
                            click.echo('[' + member['role'] + ' ' + sid[:8] + '] ' + line)
                        tails[sid] = stream, decoder, lines[-1]
                if not any(m['state'] in ('starting', 'running') for m in current['members']):
                    return current
                if current['kind'] == 'local' and current['members'][0]['state'] not in ('starting', 'running'):
                    return dict(current, ok=False, error='主机已退出；仍存活的客户端已保留。')
                time.sleep(.25)
        except KeyboardInterrupt:
            groups.stop_owned(project, group, owned)
            raise
        finally:
            for sid, (stream, decoder, pending) in tails.items():
                remaining = pending + decoder.decode(stream.read(), final=True)
                if remaining:
                    role = next(m['role'] for m in current['members'] if m.get('session') == sid)
                    click.echo('[' + role + ' ' + sid[:8] + '] ' + remaining)


def menu():
    import subprocess
    import sys
    from ..command_context import project_dir, remote_url, human_interaction
    from .backend import get_backend
    if not human_interaction():
        raise click.UsageError('请指定子命令；AI／脚本使用 --non-interactive 和 --json')
    backend, endpoint = get_backend(), remote_url()
    console = Console()
    title = '远程 Windows' if endpoint else backend.label
    choices = {'1': ('同步项目依赖', ['sync']), '2': ('构建项目', ['build']),
               '3': ('运行测试', ['run', '--no-gui']), '4': ('诊断运行环境', ['doctor']),
               '5': ('查看游戏会话', ['status', '--list']), '0': ('退出', None)}
    if backend.managed_install and not endpoint:
        choices['6'] = ('安装／管理本地运行资源', ['engine'])
    if 'project-ui' in backend.capabilities and not endpoint:
        choices['7'] = ('打开图形开发界面', ['ui'])
    while True:
        table = Table('选项', '操作', show_header=False)
        for key, (label, _) in sorted(choices.items()): table.add_row(key, label)
        console.print(Panel(table, title='mcpy · ' + title, subtitle=str(project_dir())))
        selected = click.prompt('选择', type=click.Choice(list(choices)), default='3')
        args = choices[selected][1]
        if args is None: return
        route = ['--remote', endpoint] if endpoint else ['--local']
        subprocess.run([sys.executable, '-m', 'mcpywrap_core', '--project', str(project_dir()), *route, *args])

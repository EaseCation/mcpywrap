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
                table.add_row('状态', '世界已就绪' if data.get('world_ready') else '引擎已启动，正在准备世界…')
                table.add_row('会话', session)
                table.add_row('操作', 'Ctrl+C 保存退出；其他终端可使用 logs / runtime py')
                live.update(Panel(table, title='mcpy 本地测试'))
                time.sleep(.25)
    except KeyboardInterrupt:
        console.print('正在保存世界并关闭窗口…')
        sessions.stop(project, session)
    data = sessions.read(project, session)
    if data['state'] == 'failed' or data.get('exit_code', 0):
        raise click.ClickException(data.get('error') or '游戏异常退出；请查看 logs --source engine')
    return {'session': session, 'state': 'exited', 'backend': data.get('backend', 'windows')}


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
        subprocess.run([sys.executable, '-m', 'mcpywrap', '--project', str(project_dir()), *route, *args])

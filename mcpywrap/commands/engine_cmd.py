"""Backend-independent resource commands and terminal setup wizard."""
import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn, DownloadColumn
from ..command_context import OperationCommand, human_interaction
from ..engines.backend import get_backend


def perform_install(catalog=None, apk=None):
    if not human_interaction():
        return get_backend().install(catalog, apk)
    with Progress(TextColumn('{task.description}'), BarColumn(), DownloadColumn()) as progress:
        task = progress.add_task('校验并安装资源', total=None)
        def update(done, total): progress.update(task, completed=done, total=total)
        return get_backend().install(catalog, apk, update)


def setup_wizard():
    backend = get_backend()
    if not human_interaction():
        raise click.UsageError('非交互安装请提供 engine install 参数')
    console = Console()
    state = backend.diagnose(check_files=True)
    console.print(Panel(backend.setup_description, title='准备本地测试环境'))
    if not backend.managed_install:
        return state
    if state['ok']:
        console.print('当前资源已安装。可直接运行 mcpy run。')
        return state
    location = None
    try:
        console.print('运行资源：' + backend.installation_choice())
    except ValueError:
        console.print('尚无默认发布源。可输入发行方提供的 catalog.json；开发阶段也支持本地发行目录。')
        location = click.prompt('发布目录路径或 HTTPS 地址（留空取消）', default='', show_default=False).strip()
        if not location: raise click.Abort()
    choice = click.prompt('APK 来源：1 网易官方自动下载，2 本地 APK，0 取消',
                          type=click.Choice(['1', '2', '0']), default='1')
    if choice == '0': raise click.Abort()
    apk = click.prompt('开发者 APK 路径', type=click.Path(exists=True, dir_okay=False)) if choice == '2' else None
    if not click.confirm('开始下载、校验并在本机组装？', default=True): raise click.Abort()
    return perform_install(location, apk)


@click.group(name='engine', invoke_without_command=True)
@click.pass_context
def engine_cmd(ctx):
    """管理 macOS 本地运行资源；Windows 引擎由 MC Studio 管理。"""
    if ctx.invoked_subcommand is None:
        if human_interaction(): return setup_wizard()
        raise click.UsageError('请指定 engine doctor 或 engine install；此处不读取非交互输入')


@click.command(cls=OperationCommand, name='doctor')
def engine_doctor():
    """只读检查平台、运行包和 APK 资源。"""
    state = get_backend().diagnose(check_files=True)
    if human_interaction():
        Console().print(Panel('\n'.join('%s: %s' % (k, state[k]) for k in ('backend', 'state', 'home', 'runtime', 'game') if state.get(k)), title='运行资源'))
        if state.get('hint'): click.echo(state['hint'])
    return state


@click.command(cls=OperationCommand, name='install')
@click.option('--catalog', help='发行方的 catalog.json（本地路径或 HTTPS 地址）')
@click.option('--apk', type=click.Path(exists=True, dir_okay=False), help='导入匹配版本的本地开发者 APK；省略则从网易下载')
def engine_install(catalog, apk):
    """下载校验预构建启动器，取得 APK 后在本机提取资源。"""
    if not catalog and not apk and human_interaction(): return setup_wizard()
    return perform_install(catalog, apk)


engine_cmd.add_command(engine_doctor)
engine_cmd.add_command(engine_install)

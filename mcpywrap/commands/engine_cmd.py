"""Backend-independent resource commands and terminal setup wizard."""
import click
from rich.console import Console
from rich.panel import Panel
import time
from rich.progress import Progress, BarColumn, TextColumn, DownloadColumn, TaskProgressColumn, TransferSpeedColumn, TimeRemainingColumn
from ..command_context import OperationCommand, human_interaction, json_output
from ..engines.backend import get_backend


def perform_install(catalog=None, apk=None):
    # Progress goes to stderr on every CLI path, including --json and CI pipes.
    console = Console(stderr=True)
    if not console.is_terminal:
        last = [0.0, None]
        def update_plain(done, total):
            now = time.monotonic()
            if total != last[1] or now-last[0] >= 2 or done == total:
                click.echo('下载／提取：%.1f / %.1f MiB' % (done/1048576, total/1048576), err=True)
                last[:] = [now, total]
        def phase_plain(label):
            last[:] = [0.0, None]
            click.echo(label + '…', err=True)
        update_plain.phase = phase_plain
        return get_backend().install(catalog, apk, update_plain)
    with Progress(TextColumn('{task.description}'), BarColumn(), TaskProgressColumn(),
                  DownloadColumn(), TransferSpeedColumn(), TimeRemainingColumn(), console=console) as progress:
        task = progress.add_task('准备运行资源', total=None)
        def update(done, total): progress.update(task, completed=done, total=total)
        def phase(label): progress.reset(task, description=label, total=None, completed=0)
        update.phase = phase
        result = get_backend().install(catalog, apk, update)
    return result


def setup_wizard():
    """Compatibility entry point: default installation never asks for sources."""
    backend = get_backend()
    state = backend.diagnose(check_files=True)
    if not backend.managed_install or state['ok']:
        return state
    click.echo('正在自动准备本地游戏环境…', err=True)
    return perform_install()


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
@click.option('--catalog', help='高级选项：覆盖内置发布源（catalog.json 的本地路径或 HTTPS 地址）')
@click.option('--apk', type=click.Path(exists=True, dir_okay=False), help='导入匹配版本的本地开发者 APK；省略则从网易下载')
def engine_install(catalog, apk):
    """下载校验预构建启动器，取得 APK 后在本机提取资源。"""
    return perform_install(catalog, apk)


engine_cmd.add_command(engine_doctor)
engine_cmd.add_command(engine_install)


@click.command(cls=OperationCommand, name='check-updates')
def engine_check_updates():
    """查询网易 pe/pe_old 的实际版本；不下载、不切换当前游戏。"""
    result = get_backend().check_updates()
    if json_output(): return result
    click.echo('当前版本：' + (result['installed_version'] or '尚未安装'))
    for item in result['versions']:
        suffix = ' · 可发现的新版本，兼容性待检查' if item['newer_than_installed'] else ''
        click.echo(item['channel'] + '：' + item['version'] + suffix)
    if not result['ok']:
        raise click.ClickException(result['error'] + ' ' + result['hint'])


engine_cmd.add_command(engine_check_updates)

"""性能分析：基于游戏内置 Tracy 0.11.1（协议 69）的实时查看、采集、报告与对比。"""
import datetime
import subprocess
import sys
import time
from pathlib import Path

import click

from ..command_context import OperationCommand, json_output, project_dir


def _download_progress():
    last = [0.0]

    def update(done, total):
        now = time.monotonic()
        if now - last[0] >= 1 or done == total:
            click.echo('下载 Tracy 工具：%.1f / %.1f MiB' % (done / 1048576, total / 1048576), err=True)
            last[0] = now
    return update


def _target(session, port):
    from ..profiling import endpoint, tools
    if session and port:
        raise click.UsageError('--session 与 --port 只能指定一个')
    return endpoint.resolve(project_dir(), tools.manifest()['protocol'], session=session, port=port)


def _launch(command):
    from ..mcstudio.processes import background_options
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, **background_options())
    return process.pid


def _summary(trace, top, filter):
    from ..profiling import analysis
    summary = analysis.summarize(analysis.load(trace), project_dir(), top=top, filter=filter)
    summary['trace'] = str(Path(trace).resolve())
    summary['report'] = str(analysis.report_path(Path(trace).resolve()))
    return summary


def _show(summary):
    """人类模式打印文本并返回简短结果；JSON 模式返回完整摘要。"""
    if json_output():
        return summary
    from ..profiling.analysis import format_summary
    click.echo(format_summary(summary))
    click.echo('')
    return {'trace': summary['trace']}


@click.group(name='profile')
def profile_cmd():
    """性能分析：实时分析器、离线查看、采集、报告与前后对比（Tracy 0.11.1）。"""


@profile_cmd.command(cls=OperationCommand, local_only=True, name='install')
@click.option('--from', 'from_archive', type=click.Path(exists=True, dir_okay=False), help='导入已下载的工具包 ZIP（须与清单摘要一致）')
@click.option('--force', is_flag=True, help='已安装时也重新解压')
def profile_install(from_archive, force):
    """下载并校验固定版本的 Tracy 工具；多镜像、可续传，可用 MCPY_TRACY_MIRROR 指定镜像。"""
    from ..profiling import tools
    return tools.install(from_archive, force, None if json_output() else _download_progress())


@profile_cmd.command(cls=OperationCommand, local_only=True, name='status')
def profile_status():
    """工具安装状态与本机正在监听 Tracy 的游戏进程（只查连接表，不连接游戏）。"""
    from ..profiling import endpoint, tools
    return dict(tools.status(), endpoints=endpoint.discover())


@profile_cmd.command(cls=OperationCommand, local_only=True, name='open')
@click.argument('trace', required=False, type=click.Path(exists=True, dir_okay=False))
@click.option('--session', help='连接此会话的游戏')
@click.option('--port', type=click.IntRange(1, 65535), help='直接指定本机 Tracy 端口')
def profile_open(trace, session, port):
    """打开 Tracy 分析器：给出 .tracy 文件时离线查看，否则实时连接游戏。"""
    from ..profiling import tools
    profiler = str(tools.require('tracy-profiler'))
    if trace:
        if session or port:
            raise click.UsageError('离线查看文件时不能同时指定 --session 或 --port')
        path = Path(trace).resolve()
        return {'mode': 'file', 'trace': str(path), 'pid': _launch([profiler, str(path)])}
    target = _target(session, port)
    pid = _launch([profiler, '-a', '127.0.0.1', '-p', str(target['port'])])
    return dict(target, mode='live', pid=pid,
                hint='分析器已连接；Tracy 同时只接受一个连接，关闭分析器窗口后才能再次采集。')


@profile_cmd.command(cls=OperationCommand, local_only=True, name='capture')
@click.option('--session', help='采集此会话的游戏')
@click.option('--port', type=click.IntRange(1, 65535), help='直接指定本机 Tracy 端口')
@click.option('--seconds', type=click.IntRange(1, 600), default=20, show_default=True, help='采集时长')
@click.option('--output', type=click.Path(dir_okay=False), help='.tracy 输出路径，默认 .runtime/profiles/ 下按时间命名')
@click.option('--top', type=click.IntRange(1, 200), default=15, show_default=True, help='报告中每类列出的条目数')
@click.option('--filter', help='只列出名称或模块路径包含该文本的脚本函数')
@click.option('--no-report', is_flag=True, help='只保存采集文件，不生成报告')
def profile_capture(session, port, seconds, output, top, filter, no_report):
    """无界面采集一段时间并生成报告；采集期间请让游戏处于要分析的场景。"""
    from ..engines.host import EngineError
    from ..profiling import tools
    capture = str(tools.require('tracy-capture'))
    if not no_report:
        tools.require('mcpy-tracy-report')
    if output:
        path = Path(output).expanduser().resolve()
        if path.suffix != '.tracy' or path.exists():
            raise click.UsageError('输出必须是尚不存在的 .tracy 文件')
    else:
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        path = project_dir() / '.runtime' / 'profiles' / ('%s-%s.tracy' % (stamp, (session or 'port')[:8]))
    target = _target(session, port)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not json_output():
        click.echo('采集 %d 秒（127.0.0.1:%d）…' % (seconds, target['port']), err=True)
    command = [capture, '-o', str(path), '-a', '127.0.0.1', '-p', str(target['port']), '-s', str(seconds)]
    try:
        done = subprocess.run(command, capture_output=True, timeout=seconds + 60)
    except subprocess.TimeoutExpired:
        raise EngineError('采集超时：未能连接或结束', 'capture_failed',
                          '确认没有其他分析器占用该端口后重试。', port=target['port']) from None
    if done.returncode != 0 or not path.is_file():
        tail = done.stdout.decode('utf-8', 'replace').replace('\r', '\n').strip().splitlines()[-3:]
        raise EngineError('采集失败', 'capture_failed', details='\n'.join(tail), port=target['port'])
    if no_report:
        return dict(target, trace=str(path), size=path.stat().st_size)
    return _show(dict(_summary(path, top, filter), target=target))


@profile_cmd.command(cls=OperationCommand, local_only=True, name='report')
@click.argument('trace', type=click.Path(exists=True, dir_okay=False))
@click.option('--top', type=click.IntRange(1, 200), default=15, show_default=True)
@click.option('--filter', help='只列出名称或模块路径包含该文本的脚本函数')
def profile_report(trace, top, filter):
    """汇总 .tracy 文件：主循环与 tick 分位数、脚本函数热点与尖峰、最慢帧归因。"""
    return _show(_summary(trace, top, filter))


@profile_cmd.command(cls=OperationCommand, local_only=True, name='diff')
@click.argument('base', type=click.Path(exists=True, dir_okay=False))
@click.argument('new', type=click.Path(exists=True, dir_okay=False))
@click.option('--top', type=click.IntRange(1, 200), default=15, show_default=True)
def profile_diff(base, new, top):
    """对比两次采集（按每秒耗时，时长可不同）；用于验证优化前后的变化。"""
    from ..profiling import analysis
    before = analysis.summarize(analysis.load(base), project_dir(), top=200)
    after = analysis.summarize(analysis.load(new), project_dir(), top=200)
    result = dict(analysis.diff(before, after, top), base=str(Path(base).resolve()), new=str(Path(new).resolve()))
    if json_output():
        return result
    click.echo(analysis.format_diff(result))
    click.echo('')
    return {'base': result['base'], 'new': result['new']}

"""观察、统一 JSON 计划与操作生命周期；快捷键只生成同一协议。"""
import json
from pathlib import Path
import click
from .runtime_ui_cmd import UICommand, session_option
from ..command_context import project_dir
from ..input_plan import INPUT_ACTIONS, input_key_plan, normalize_input_plan


def perform(session, action, **parameters):
    from ..mcstudio.unified_input import execute
    return execute(project_dir(), session, action, {k: v for k, v in parameters.items() if v is not None})


@click.group(name='input', epilog='动作由同一注册表定义：'+', '.join(INPUT_ACTIONS))
def input_cmd():
    """观察当前状态 → run 提交统一计划 → status/cancel 查询或停止；默认游戏内执行。"""


@input_cmd.command(cls=UICommand, name='capabilities')
@session_option
def capabilities_cmd(session):
    """只读查询动作参数、时钟、后端和限制，不自动安装。"""
    return perform(session, 'capabilities')


@input_cmd.command(cls=UICommand, name='observe')
@session_option
@click.option('--view', type=click.Choice(['auto', 'player', 'ui']), default='auto')
@click.option('--query', help='UI 观察按名称或路径筛选')
@click.option('--limit', type=click.IntRange(1, 160), default=80)
@click.option('--offset', type=click.IntRange(0), default=0)
@click.option('--details', is_flag=True)
def observe_cmd(session, **parameters):
    """按当前画面返回快照、目标和可执行动作；页面改变后重新观察。"""
    return perform(session, 'observe', **parameters)


@input_cmd.command(cls=UICommand, name='run')
@session_option
@click.option('--file', 'filename', required=True, type=click.Path(exists=True, dir_okay=False))
@click.option('--request-id', help='32 位小写十六进制幂等 ID；未知结果查原 ID')
def run_cmd(session, filename, request_id):
    """一次提交 JSON steps；自动/显式排时共用协议，不选择 sequence/timeline。"""
    raw = Path(filename).read_bytes()
    if len(raw) > 65536:
        raise click.UsageError('输入文件超过 64 KiB；规范化计划上限为 16 KiB')
    try:
        plan = normalize_input_plan(json.loads(raw.decode('utf-8-sig')))
    except (ValueError, UnicodeError) as error:
        raise click.UsageError(str(error)) from None
    return perform(session, 'run', plan=plan, request_id=request_id)


@input_cmd.command(cls=UICommand, name='key')
@session_option
@click.argument('keys')
@click.option('--duration-ms', type=click.IntRange(20, 10000), default=80)
@click.option('--request-id')
def key_cmd(session, keys, duration_ms, request_id):
    """人工快捷命令，按声明顺序生成 key 计划，再调用同一个 run。"""
    return perform(session, 'run', plan=input_key_plan(keys, duration_ms), request_id=request_id)


@input_cmd.command(cls=UICommand, name='status')
@session_option
@click.option('--operation')
@click.option('--details', is_flag=True)
def status_cmd(session, operation, details):
    """查询 operation_id；details 返回规范化计划和实际/清理日志。"""
    return perform(session, 'status', operation=operation, details=details)


@input_cmd.command(cls=UICommand, name='cancel')
@session_option
@click.option('--operation', required=True)
def cancel_cmd(session, operation):
    """取消原操作并释放其输入；不能以重跑计划代替清理。"""
    return perform(session, 'cancel', operation=operation)


@input_cmd.command(cls=UICommand, name='stop')
@session_option
def stop_cmd(session):
    """停止本控制层输入，不退出游戏。"""
    return perform(session, 'stop')

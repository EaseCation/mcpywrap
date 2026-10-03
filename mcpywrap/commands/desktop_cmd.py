"""Session-bound desktop operations; the CLI router can execute these remotely."""
from pathlib import Path
import json
import click
from ..command_context import OperationCommand, project_dir


def output_path(value):
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() != '.png' or path.exists():
        raise ValueError('输出必须是尚不存在的 .png 文件')
    return path


def save_image(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(content)


class KeyCommand(OperationCommand):
    def get_help(self, ctx):
        from ..mcstudio.window import KEYS, ALIASES
        self.epilog = '键名: ' + ', '.join(sorted(set(KEYS) | set(ALIASES) | {'NUMPAD_ENTER'}))
        return super().get_help(ctx)


@click.command(cls=OperationCommand)
@click.option('--session', required=True)
@click.option('--output', required=True, help='本机 PNG 路径，不覆盖已有文件')
@click.option('--background-only', is_flag=True, help='仅后台捕获；失败不激活游戏或回退到前台')
def screenshot_cmd(session, output, background_only=False):
    """截图到调用端；远程模式会下载 Windows 游戏客户区 PNG。"""
    from ..mcstudio.window import operate
    path = output_path(output)
    result = operate(project_dir(), session, 'screenshot',
                     {'background_only': True} if background_only else None)
    save_image(path, result.pop('content'))
    return {'image': str(path), **result}


@click.command(cls=KeyCommand)
@click.option('--session', required=True)
@click.argument('keys', nargs=-1, required=True)
@click.option('--hold-ms', type=click.IntRange(20, 60000), default=80, show_default=True)
def key_cmd(session, keys, hold_ms):
    """发送键名、组合键或 VK/SC/E0 扫描码，结束时释放；例如 SHIFT+W。"""
    from ..mcstudio.window import operate
    return operate(project_dir(), session, 'key', {'keys': keys, 'hold_ms': hold_ms})


@click.command(cls=OperationCommand)
@click.argument('action', type=click.Choice(['move', 'click', 'click-current', 'double-click', 'scroll', 'drag', 'relative']))
@click.option('--session', required=True)
@click.option('--x', type=int)
@click.option('--y', type=int)
@click.option('--width', type=click.IntRange(1), help='参考截图客户区宽度')
@click.option('--height', type=click.IntRange(1), help='参考截图客户区高度')
@click.option('--to-x', type=int, help='拖拽终点')
@click.option('--to-y', type=int, help='拖拽终点')
@click.option('--dx', type=int, default=0, help='相对移动总量')
@click.option('--dy', type=int, default=0)
@click.option('--delta', type=int, default=0, help='滚轮量，120 为一格，负值向下')
@click.option('--button', type=click.Choice(['left', 'right', 'middle']), default='left')
@click.option('--duration-ms', type=click.IntRange(20, 60000), default=80, show_default=True)
@click.option('--keys', multiple=True, help='同时按住的修饰键，例如 SHIFT 或 CTRL+ALT')
def mouse_cmd(session, **parameters):
    """客户区鼠标操作；click-current 仅需宽高，relative 用于转向，其余需坐标与宽高。"""
    from ..mcstudio.window import operate
    return operate(project_dir(), session, 'mouse', parameters)


def sequence_parameters(events, filename, width, height, max_lateness_ms):
    if (events is None) == (filename is None):
        raise click.UsageError('必须且只能指定 --events 或 --file')
    if filename:
        with Path(filename).open('rb') as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise click.UsageError('输入序列文件不能超过 64 KiB')
        events = raw.decode('utf-8-sig')
    elif len(events.encode('utf-8')) > 65536:
        raise click.UsageError('输入序列不能超过 64 KiB')
    try:
        plan = json.loads(events)
    except ValueError:
        raise click.UsageError('events 必须是 UTF-8 JSON 事件列表') from None
    from ..mcstudio.input_sequence import validate_events
    parameters = dict(events=plan, width=width, height=height, max_lateness_ms=max_lateness_ms)
    validate_events(**parameters)
    return parameters


@click.command(cls=OperationCommand, name='input-sequence')
@click.option('--session', required=True)
@click.option('--events', help='JSON 事件列表；与 --file 二选一')
@click.option('--file', 'filename', type=click.Path(exists=True, dir_okay=False), help='调用端 UTF-8 JSON 事件文件')
@click.option('--width', type=click.IntRange(1), help='含鼠标事件时必填，参考客户区宽度')
@click.option('--height', type=click.IntRange(1), help='含鼠标事件时必填，参考客户区高度')
@click.option('--max-lateness-ms', type=click.IntRange(0, 10000), help='可选迟到阈值；超过时停止并释放，不重放')
def input_sequence_cmd(session, events, filename, width, height, max_lateness_ms):
    """一次请求执行 Windows 输入时间表，返回逐事件 SendInput 时间；需要游戏前台。"""
    from ..mcstudio.window import operate
    return operate(project_dir(), session, 'input-sequence',
                   sequence_parameters(events, filename, width, height, max_lateness_ms))

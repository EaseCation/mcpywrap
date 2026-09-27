"""Session-bound desktop operations; the CLI router can execute these remotely."""
from pathlib import Path
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
def screenshot_cmd(session, output):
    """截图到调用端；远程模式会下载 Windows 游戏客户区 PNG。"""
    from ..mcstudio.window import operate
    path = output_path(output)
    result = operate(project_dir(), session, 'screenshot')
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
@click.argument('action', type=click.Choice(['move', 'click', 'double-click', 'scroll', 'drag', 'relative']))
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
    """客户区鼠标操作；relative 用于视角转向，其他动作需 x/y/width/height。"""
    from ..mcstudio.window import operate
    return operate(project_dir(), session, 'mouse', parameters)

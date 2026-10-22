"""Explicit window activation policy, independent of worker detachment and Qt."""
import click


def window_options(function):
    return click.option('--background/--foreground', default=None,
                        help='游戏窗口不主动聚焦／正常聚焦；非交互、JSON、--no-gui 或 --detach 默认后台')(function)


def resolve_background(value=None, *, no_gui=False, detach=False):
    if value is not None:
        return validate_background(value)
    from ..command_context import non_interactive, json_output
    return bool(no_gui or detach or non_interactive() or json_output())


def validate_background(value):
    if type(value) is not bool:
        raise ValueError('background 必须是布尔值')
    return value


def require_native_background(metadata, background):
    if background and metadata.get('background_window_protocol') != 1:
        from ..engines.host import EngineError
        raise EngineError('此 macOS 运行包不支持后台窗口启动。', 'background_window_unavailable',
                          '安装支持 background_window_protocol=1 的运行包并新建实例；'
                          '允许游戏聚焦时可显式使用 --foreground。')


def require_foreground_input(project, session):
    from ..mcstudio import sessions
    from ..engines.host import EngineError
    if sessions.read(project, session).get('background', False):
        raise EngineError('后台会话不允许会激活窗口的桌面键鼠输入。', 'foreground_input_disabled',
                          '使用 runtime input 的 game 后端；需要系统键鼠时用 --foreground 启动。')

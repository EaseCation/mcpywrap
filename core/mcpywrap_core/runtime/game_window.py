"""游戏窗口尺寸：启动时指定与运行中调整，均经系统窗口 API 完成。

尺寸统一表示客户区像素（不含标题栏和边框），与截图、录制及指针坐标一致；游戏按窗口
像素渲染，因此它也决定画面分辨率。Windows 使用 SetWindowPos，macOS 使用随 CLI 安装的
原生辅助程序经“辅助功能”API 设置窗口尺寸；两者都不激活窗口、不移动光标。
"""
from contextlib import contextmanager
import contextvars
import json
import re
import subprocess
import sys
import time

from ..engines.host import EngineError

MIN_WIDTH, MIN_HEIGHT = 320, 240
MAX_WIDTH, MAX_HEIGHT = 7680, 4320
SIZE_PATTERN = re.compile(r'([1-9][0-9]{2,4})[xX×]([1-9][0-9]{2,4})')
# 窗口尚未出现或启动画面占用时可重试；其余错误重试也不会改变结果。
TRANSIENT = {'window_unavailable'}
LAUNCH_TIMEOUT = 120
# 游戏可能在加载过程中按自身记录恢复窗口尺寸；进入游戏前最多补设几次。
REAPPLY_LIMIT = 3

_requested = contextvars.ContextVar('mcpy_window_size', default=None)


def parse_size(value):
    """'1280x720' → (1280, 720)；格式错误或超出范围抛出 invalid_size（ValueError 子类）。"""
    match = SIZE_PATTERN.fullmatch(value.strip()) if isinstance(value, str) else None
    if not match:
        raise EngineError('窗口尺寸格式为 宽x高，例如 1280x720', 'invalid_size')
    return validate_size(int(match.group(1)), int(match.group(2)))


def validate_size(width, height):
    if (type(width) is not int or type(height) is not int or not MIN_WIDTH <= width <= MAX_WIDTH
            or not MIN_HEIGHT <= height <= MAX_HEIGHT):
        raise EngineError('窗口客户区尺寸需在 %dx%d 到 %dx%d 像素之间' % (MIN_WIDTH, MIN_HEIGHT, MAX_WIDTH, MAX_HEIGHT),
                          'invalid_size')
    return width, height


def size_option(function):
    import click

    def convert(ctx, param, value):
        if value is None:
            return None
        try:
            return parse_size(value)
        except ValueError as error:
            raise click.BadParameter(str(error)) from None
    return click.option('--window-size', callback=convert, metavar='WxH',
                        help='游戏窗口客户区像素尺寸（决定画面分辨率），例如 1280x720；'
                             '窗口出现后经系统 API 设置，restart 沿用；--clients 2 时两个客户端相同')(function)


@contextmanager
def window_size_scope(size):
    """本作用域内新建的游戏会话请求该窗口尺寸；None 表示保持游戏默认尺寸。"""
    token = _requested.set(tuple(size) if size else None)
    try:
        yield
    finally:
        _requested.reset(token)


def requested_window_size():
    size = _requested.get()
    return list(size) if size else None


def _error(result):
    return EngineError(result.get('error') or '窗口操作失败', result.get('code') or 'window_failed', result.get('hint'))


# --- 平台实现 -------------------------------------------------------------

def _macos(game, size=None):
    from ..mcstudio.recordings import macos_helper
    try:
        executable = macos_helper()
    except ValueError as error:
        raise EngineError('macOS 原生辅助程序不可用：' + str(error), 'capability_missing',
                          '重新安装同版本 CLI；源码检出需先运行 scripts/build_macos_capture.py。') from None
    command = [str(executable), '--window', '--pid', str(game['pid'])]
    if size:
        command += ['--width', str(size[0]), '--height', str(size[1])]
    try:
        probe = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=15)
    except subprocess.TimeoutExpired:
        raise EngineError('窗口辅助程序未在 15 秒内返回', 'window_failed') from None
    lines = probe.stdout.decode('utf-8', 'replace').strip().splitlines()
    try:
        result = json.loads(lines[-1])
    except (IndexError, ValueError):
        detail = probe.stderr.decode('utf-8', 'replace').strip()
        if 'missing argument' in detail or 'usage:' in detail:
            raise EngineError('已安装的 macOS 辅助程序不支持窗口操作', 'capability_missing',
                              '更新 mcpywrap；源码检出需重新运行 scripts/build_macos_capture.py。') from None
        raise EngineError('窗口辅助程序返回无效结果：' + detail[:200], 'window_failed') from None
    if not result.get('ok'):
        if result.get('code') == 'permission_missing':
            result.setdefault('hint', '在“系统设置 > 隐私与安全性 > 辅助功能”中允许运行 mcpy 的终端或宿主应用，并重启该应用。')
        elif result.get('code') == 'invalid_size' and result.get('scale'):
            result.setdefault('hint', '此显示器缩放为 %s 倍，宽高需为它的整数倍。' % result['scale'])
        raise _error(result)
    return result


def _windows(project, session, size=None):
    from ..mcstudio.window import GameWindow, session_game
    try:
        window = GameWindow(session_game(project, session))
    except ValueError as error:
        if getattr(error, 'code', None):
            raise
        # 启动画面或加载期间可能还没有唯一可见窗口，交由调用方决定是否重试。
        raise EngineError(str(error), 'window_unavailable') from None
    try:
        return window.resize_client(*size) if size else window.window_state()
    finally:
        window.close()


def _game(project, session):
    from ..mcstudio import sessions
    from ..mcstudio.recordings import recording_game, RecordingError
    data = sessions.read(project, session)
    if data.get('backend') == 'macos-arm64':
        try:
            return data, recording_game(project, session)
        except RecordingError as error:
            raise EngineError(str(error), 'session_unavailable') from None
    if data.get('backend', 'windows') != 'windows':
        raise EngineError('此会话后端不支持窗口尺寸操作', 'unsupported_feature')
    return data, None


def _native(project, session, size=None):
    data, game = _game(project, session)
    if game is not None:
        result = _macos(game, size)
    elif sys.platform == 'win32':
        result = _windows(project, session, size)
    else:
        raise EngineError('Windows 会话的窗口只能在其执行端调整', 'unsupported_feature',
                          '远程 Windows 会话使用 --remote 调用。')
    keys = ('width', 'height', 'scale', 'fullscreen', 'minimized', 'maximized', 'resize_permission')
    return data, {key: result[key] for key in keys if key in result}


def _requested_record(data):
    window = data.get('window')
    return dict(window) if window else None


def info(project, session):
    """当前客户区像素尺寸与窗口状态；只读，不激活窗口。"""
    data, state = _native(project, session)
    return {'session': session, **state, 'launch_request': _requested_record(data)}


def resize(project, session, width, height):
    """把客户区调整为指定像素尺寸，并核对实际结果；不改变启动时记录的尺寸。"""
    width, height = validate_size(width, height)
    from ..mcstudio import recordings, sessions
    sessions.read(project, session)
    for item in recordings.directory(project, session).glob('*.json'):
        if recordings.read(project, session, item.stem)['state'] in recordings.ACTIVE:
            raise EngineError('此会话正在录制，改变窗口尺寸会结束录像。', 'busy',
                              '等待录制完成或先 record stop，再调整窗口。')
    # 先标记手动调整：启动尺寸的补设检查看到后即停止，不会把窗口改回启动尺寸。
    manual_marker(project, session).touch()
    data, state = _native(project, session, (width, height))
    return {'session': session, 'requested': {'width': width, 'height': height}, **state, 'resized': True}


def manual_marker(project, session):
    from ..mcstudio import sessions
    return sessions.session_path(project, session) / 'window.manual'


def apply_to_running(project, session, size):
    """run 复用运行中的会话时立即调整窗口；失败只记录在结果中，不影响已复用的会话。"""
    record = {'requested': {'width': size[0], 'height': size[1]}}
    try:
        result = resize(project, session, *size)
    except EngineError as error:
        return dict(record, state='failed', error=str(error), code=error.code, hint=error.hint)
    return dict(record, state='applied', width=result.get('width'), height=result.get('height'))


class LaunchSizer:
    """会话 worker 内：游戏窗口出现后应用启动时请求的尺寸，结果写入会话的 window 字段。"""

    def __init__(self, data):
        size = data.get('window_size')
        self.size = tuple(size) if size else None
        self.started = time.monotonic()
        self.next_attempt = 0
        self.reapplied = 0
        if self.size:
            data['window'] = {'requested': {'width': self.size[0], 'height': self.size[1]}, 'state': 'pending'}

    def poll(self, project, session, data):
        """返回会话数据是否变化；只在需要时调用系统 API，不抛出异常。"""
        window = data.get('window')
        if not self.size or window['state'] == 'failed':
            return False
        if manual_marker(project, session).exists():
            # 用户或 AI 已用 window resize 指定尺寸，以手动尺寸为准。
            self.size = None
            return False
        if window['state'] == 'applied' and (data.get('world_ready') or self.reapplied >= REAPPLY_LIMIT):
            return False
        now = time.monotonic()
        if now < self.next_attempt:
            return False
        self.next_attempt = now + (1 if window['state'] == 'applied' else 0.5)
        try:
            if window['state'] == 'applied':
                # 已设置后核对：游戏在加载中恢复了自身尺寸时再设置一次。
                _, state = _native(project, session)
                if (state.get('width'), state.get('height')) == self.size:
                    return False
                self.reapplied += 1
            _, state = _native(project, session, self.size)
        except EngineError as error:
            if error.code in TRANSIENT and now - self.started < LAUNCH_TIMEOUT and window['state'] == 'pending':
                return False
            if window['state'] == 'applied' and error.code in TRANSIENT:
                return False
            window.update(state='failed', error=str(error), code=error.code, hint=error.hint)
            print('窗口尺寸未能应用：' + str(error), file=sys.stderr, flush=True)
            return True
        except (OSError, ValueError) as error:
            window.update(state='failed', error=str(error), code='window_failed', hint=None)
            print('窗口尺寸未能应用：' + str(error), file=sys.stderr, flush=True)
            return True
        window.update(state='applied', width=state.get('width'), height=state.get('height'),
                      error=None, code=None, hint=None)
        return True

"""Single-frame capture routed by the session's backend, never by window title."""
import json
import os
from pathlib import Path
import stat
import time
import uuid

from ..engines.host import EngineError
from . import sessions
from .image import png_bytes
from .launcher_control import LauncherControl
from .processes import checked_process

MAX_PIXELS = 16 * 1024 * 1024
UPGRADE_HINT = '需要 screenshot_protocol=1 的 macOS 运行包；更新运行包后使用新建实例。已有实例仍固定原版本。'


def supported(data):
    """Inspect the pinned runtime only; never execute game code or start capture."""
    if data.get('backend', 'windows') == 'windows':
        return True
    runtime = data.get('launch', {}).get('runtime')
    if data.get('backend') != 'macos-arm64' or not runtime:
        return False
    try:
        metadata = json.loads((Path(runtime)/'Contents/Resources/runtime.json').read_text())
        return metadata.get('screenshot_protocol') == 1
    except (OSError, ValueError):
        return False


def capture(project, session, background_only=False):
    data = sessions.read(project, session)
    if data.get('backend', 'windows') == 'windows':
        from .window import operate
        return operate(project, session, 'screenshot', {'background_only': True} if background_only else None)
    if data.get('backend') != 'macos-arm64':
        raise EngineError('此会话后端不支持截图', 'unsupported_feature')
    if not supported(data):
        raise EngineError('此实例的运行包不支持原生截图', 'capability_missing', UPGRADE_HINT)
    game = data.get('game')
    if (Path(data.get('project', project)).resolve() != Path(project).resolve() or
            data.get('state') not in ('starting', 'running') or not game or
            Path(game['executable']).name != 'mcpelauncher-client' or not checked_process(game)):
        raise EngineError('目标会话没有可用的 Launcher 游戏进程', 'session_unavailable')
    control = LauncherControl(Path(data['launch']['data'])/'python-control.json', game['pid'])
    try:
        status = control.request('status')
    except FileNotFoundError:
        raise EngineError('Launcher 控制通道尚未就绪', 'capture_unavailable') from None
    if status.get('screenshot_protocol') != 1:
        raise EngineError('当前游戏进程不支持原生截图', 'capability_missing', UPGRADE_HINT)
    request_id = uuid.uuid4().hex
    try:
        result = control.request('screenshot', {'op': 'capture', 'request_id': request_id})
        deadline = time.monotonic() + 6
        while result.get('state') in ('queued', 'capturing') and time.monotonic() < deadline:
            time.sleep(.05)
            if not checked_process(game):
                raise EngineError('游戏在截图完成前退出', 'session_unavailable')
            result = control.request('screenshot', {'op': 'poll', 'request_id': request_id})
        if result.get('state') != 'completed':
            code = result.get('code', 'capture_timeout')
            raise EngineError('原生截图未完成：' + code, code,
                              '确认游戏仍在渲染；不会回退到桌面截图。忙碌时等待当前截图结束。')
        if result.get('protocol') != 1 or result.get('request_id') != request_id:
            raise EngineError('截图响应不属于当前请求', 'invalid_capture')
        width, height = result.get('width'), result.get('height')
        if (type(width) is not int or type(height) is not int or
                width <= 0 or height <= 0 or width * height > MAX_PIXELS):
            raise EngineError('截图像素尺寸无效', 'invalid_capture')
        # The server never receives an output path. Read only this request's
        # bounded regular file inside the authenticated private socket directory.
        path = control.directory/('screenshot-' + request_id + '.rgba')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                    info.st_mode & 0o077 or info.st_size != width * height * 4):
                raise EngineError('截图像素文件归属、权限或尺寸无效', 'invalid_capture')
            pixels = stream.read(info.st_size + 1)
        if len(pixels) != width * height * 4 or not checked_process(game):
            raise EngineError('截图读取期间目标进程或像素文件发生变化', 'invalid_capture')
        return {'session': session, 'pid': game['pid'], 'width': width, 'height': height,
                'capture': 'launcher-framebuffer', 'capture_fallback': False,
                'coordinate_space': 'game-content', 'source_time_ns': result.get('source_time_ns'),
                'clock_source': 'launcher.steady_clock',
                'content': png_bytes(width, height, pixels, rgba=True, bottom_up=True)}
    finally:
        try:
            control.request('screenshot', {'op': 'release', 'request_id': request_id})
        except (OSError, ValueError):
            pass  # One bounded native slot expires; cleanup must not mask the result.

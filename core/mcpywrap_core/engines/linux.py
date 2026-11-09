"""AArch64 Linux 后端：与 macOS 共用 APK 原生运行包流程，图形走系统 EGL/GLES。"""
import os
from pathlib import Path

from .macos import COMMON_CAPABILITIES, NativeApkBackend
from .platforms import LINUX

DISPLAY_HINT = ('在桌面会话的终端中运行；通过 SSH 运行时设置 WAYLAND_DISPLAY（及 XDG_RUNTIME_DIR）'
                '或 DISPLAY 指向已登录的图形会话。')


def _wayland_socket(environ):
    name = environ.get('WAYLAND_DISPLAY')
    if not name:
        return None
    path = Path(name) if os.path.isabs(name) else Path(environ.get('XDG_RUNTIME_DIR') or '/nonexistent')/name
    return path if path.exists() else False


def _x11_socket(environ):
    display = environ.get('DISPLAY')
    if not display:
        return None
    host, _, rest = display.rpartition(':')
    if host and host != 'unix':
        return True  # 远程/转发显示无法在本地检查，交给 GLFW 连接时报告
    number = rest.split('.', 1)[0]
    return Path('/tmp/.X11-unix/X' + number).exists() if number.isdecimal() else False


def render_nodes():
    return sorted(str(path) for path in Path('/dev/dri').glob('renderD*')
                  if os.access(path, os.R_OK | os.W_OK)) if Path('/dev/dri').is_dir() else []


def display_diagnostics(environ=None):
    """只检查会话变量与套接字，不连接显示服务器、不创建窗口。"""
    environ = os.environ if environ is None else environ
    wayland, x11 = _wayland_socket(environ), _x11_socket(environ)
    session = 'wayland' if wayland else 'x11' if x11 else None
    nodes = render_nodes()
    result = {'ok': session is not None, 'session': session, 'render_nodes': nodes, 'gpu': bool(nodes)}
    if session is None:
        stale = wayland is False or x11 is False
        result.update(error=('显示会话变量指向的套接字不存在。' if stale else '没有可用的图形显示会话。'),
                      hint=DISPLAY_HINT)
    elif not nodes:
        result['warning'] = '未找到可访问的 GPU 渲染节点，将依赖软件渲染；确认用户属于 render/video 组。'
    return result


class LinuxBackend(NativeApkBackend):
    platform = LINUX
    id = LINUX.backend
    label = 'Linux · AArch64 · GLES'
    graphics_path = 'Linux GLES'
    BASE_CAPABILITIES = COMMON_CAPABILITIES + ('linux-local-worlds', 'linux-engine-install')
    setup_description = ('在 AArch64 Linux（glibc）上运行本地 Addon 测试，需要 Wayland 或 X11 图形会话及 GLES 3 驱动。\n'
                         '首次运行会自动下载原生启动器和网易开发者版资源，并在本机完成安装。\n'
                         '需下载约 2.3 GB，请预留至少 7 GB 可用空间。')

    @property
    def capabilities(self):
        # PySide6 的 aarch64 wheel 需要 glibc 2.39+，在 Linux 上是可选依赖；
        # 未安装时交互式 run 使用终端视图，而不是在启动游戏后才因导入失败中断。
        import importlib.util
        if importlib.util.find_spec('PySide6') is None:
            return tuple(item for item in self.BASE_CAPABILITIES if item != 'project-ui')
        return self.BASE_CAPABILITIES

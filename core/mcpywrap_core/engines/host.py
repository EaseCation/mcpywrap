import platform
import subprocess
import sys


class EngineError(ValueError):
    def __init__(self, message, code='engine_error', hint=None, **details):
        super().__init__(message)
        self.code, self.hint, self.details = code, hint, details


def _glibc_version():
    try:
        library, version = platform.libc_ver()
    except (OSError, ValueError):
        return None
    return version if library == 'glibc' and version else None


def describe():
    machine = platform.machine().lower()
    silicon = machine in ('arm64', 'aarch64')
    if sys.platform == 'darwin' and not silicon:
        try:
            silicon = subprocess.check_output(['/usr/sbin/sysctl', '-n', 'hw.optional.arm64'],
                                              text=True, stderr=subprocess.DEVNULL).strip() == '1'
        except (OSError, subprocess.CalledProcessError):
            pass
    linux = sys.platform.startswith('linux')
    glibc = _glibc_version() if linux else None
    # Linux 运行包是 glibc 动态链接的原生 AArch64 程序；musl 等其他 C 库不支持。
    backend = ('windows' if sys.platform == 'win32' else 'macos-arm64' if sys.platform == 'darwin' and silicon
               else 'linux-arm64' if linux and machine == 'aarch64' and glibc else None)
    return {'platform': sys.platform, 'architecture': machine, 'backend': backend,
            'macos_version': platform.mac_ver()[0] if sys.platform == 'darwin' else None,
            'glibc_version': glibc,
            'translated_python': sys.platform == 'darwin' and silicon and machine == 'x86_64'}


def require_native(target):
    """target 为 platforms.RuntimePlatform；宿主必须与运行包平台一致。"""
    host = describe()
    if host['backend'] != target.backend:
        if target.is_macos:
            raise EngineError('此运行包仅支持 Apple Silicon macOS。', 'unsupported_platform',
                              'Windows 请使用 MC Studio；其他平台可使用 --remote 连接 Windows 测试服务。', host=host)
        raise EngineError('此运行包仅支持 glibc 的 AArch64 Linux。', 'unsupported_platform',
                          '其他平台请使用对应运行包，或通过 --remote 连接 Windows 测试服务。', host=host)
    return host


def require_macos():
    from .platforms import MACOS
    return require_native(MACOS)

import platform
import subprocess
import sys


class EngineError(ValueError):
    def __init__(self, message, code='engine_error', hint=None, **details):
        super().__init__(message)
        self.code, self.hint, self.details = code, hint, details


def describe():
    machine = platform.machine().lower()
    silicon = machine in ('arm64', 'aarch64')
    if sys.platform == 'darwin' and not silicon:
        try:
            silicon = subprocess.check_output(['/usr/sbin/sysctl', '-n', 'hw.optional.arm64'],
                                              text=True, stderr=subprocess.DEVNULL).strip() == '1'
        except (OSError, subprocess.CalledProcessError):
            pass
    backend = 'windows' if sys.platform == 'win32' else 'macos-arm64' if sys.platform == 'darwin' and silicon else None
    return {'platform': sys.platform, 'architecture': machine, 'backend': backend,
            'macos_version': platform.mac_ver()[0] if sys.platform == 'darwin' else None,
            'translated_python': sys.platform == 'darwin' and silicon and machine == 'x86_64'}


def require_macos():
    host = describe()
    if host['backend'] != 'macos-arm64':
        raise EngineError('此运行包仅支持 Apple Silicon macOS。', 'unsupported_platform',
                          'Windows 请使用 MC Studio；其他平台可使用 --remote 连接 Windows 测试服务。', host=host)
    return host

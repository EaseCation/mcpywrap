"""原生 APK 运行包的平台描述：布局、可执行格式、系统版本与本地目录。

同一套 APK 安装、实例与启动流程由 macOS 和 Linux 共用；平台差异只在这里声明。
会话记录保存后端 ID，恢复时据此取回描述，不重新猜测宿主平台。
"""
from dataclasses import dataclass
from pathlib import Path
import os
import struct


@dataclass(frozen=True)
class RuntimePlatform:
    backend: str            # 会话与实例记录中的后端 ID
    catalog_platform: str   # 发布目录与 runtime.json 中的平台
    archive_root: str       # 运行包归档根目录
    system: str             # 面向用户的系统名称
    minimum_key: str        # 发布目录/元数据中最低系统版本字段
    host_version_key: str   # host.describe() 中对应的版本字段
    state_dir: str          # 项目 .runtime 下的实例目录名，同时用于偏好目录

    # 运行包内的路径
    def client(self, app):
        return Path(app)/('Contents/MacOS/mcpelauncher-client' if self.is_macos else 'bin/mcpelauncher-client')

    def resources(self, app):
        return Path(app)/('Contents/Resources' if self.is_macos else 'resources')

    def metadata(self, app):
        return self.resources(app)/'runtime.json'

    def launcher(self, app):
        return self.resources(app)/'launcher'

    @property
    def is_macos(self):
        return self.catalog_platform == 'darwin-arm64'

    def instances_root(self, project):
        return Path(project)/'.runtime'/self.state_dir/'instances'

    def native_executable(self, path):
        """只读取文件头判断是否为本平台 arm64 可执行文件，不执行它。"""
        with Path(path).open('rb') as stream:
            header = stream.read(20)
        if self.is_macos:
            return len(header) >= 8 and struct.unpack('<II', header[:8]) == (0xfeedfacf, 0x100000c)
        # ELF64、小端、e_machine=EM_AARCH64(183)
        return (len(header) >= 20 and header[:4] == b'\x7fELF' and header[4] == 2 and header[5] == 1
                and struct.unpack('<H', header[18:20])[0] == 183)


MACOS = RuntimePlatform('macos-arm64', 'darwin-arm64', 'McpyRuntime.app', 'macOS',
                        'minimum_macos', 'macos_version', 'macos')
LINUX = RuntimePlatform('linux-arm64', 'linux-arm64', 'McpyRuntime', 'Linux (glibc)',
                        'minimum_glibc', 'glibc_version', 'linux')
PLATFORMS = {item.backend: item for item in (MACOS, LINUX)}
NATIVE_BACKENDS = tuple(PLATFORMS)


def is_native(backend):
    return backend in PLATFORMS


def for_backend(backend):
    try:
        return PLATFORMS[backend]
    except KeyError:
        from .host import EngineError
        raise EngineError('未知原生运行后端：' + str(backend), 'unknown_backend') from None


def metadata_path(runtime):
    """按会话固定的运行包目录定位 runtime.json，兼容两种布局。"""
    runtime = Path(runtime)
    for item in (MACOS, LINUX):
        path = item.metadata(runtime)
        if path.is_file():
            return path
    return (LINUX if runtime.name == LINUX.archive_root else MACOS).metadata(runtime)


def default_home(system=None):
    import sys
    system = system or sys.platform
    if system == 'darwin':
        return Path('~/Library/Application Support/mcpy').expanduser()
    base = os.environ.get('XDG_DATA_HOME') or '~/.local/share'
    return Path(base).expanduser()/'mcpy'

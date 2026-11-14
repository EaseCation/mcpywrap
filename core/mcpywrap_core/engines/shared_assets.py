"""为实例数据目录预置引擎中的大文件：用 APFS 写时复制克隆代替整份复制。

运行包启动器只在 ``vanilla.mcp`` 不存在时从共享引擎复制它（约 25 MB），因此预先放置克隆后，
各实例/会话几乎不再为它占用空间；克隆可独立写入，不影响共享引擎。不支持克隆的卷（非 APFS、
跨卷）保持原状，由启动器照常复制。游戏首启复制的 ``storge/asset``（约 400 MB）会覆盖已有文件，
由运行包 0.4.10 起在复制时克隆，不在此预置。
"""
import ctypes
import errno
import os
from pathlib import Path
import sys
import uuid

# (引擎 game 目录内的来源, 数据目录内的目标)
SHARED_FILES = (
    ('assets/assets/vanilla.mcp', 'games/com.netease/vanilla.mcp'),
)
CLONE_NOFOLLOW = 0x0001
CLONE_NOOWNERCOPY = 0x0002
_clonefile = None


def _native():
    global _clonefile
    if _clonefile is None:
        function = ctypes.CDLL(None, use_errno=True).clonefile
        function.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32)
        function.restype = ctypes.c_int
        _clonefile = function
    return _clonefile


def clone(source, target):
    """克隆单个文件；卷不支持克隆时返回 False，其余错误抛出 OSError。"""
    if _native()(os.fsencode(source), os.fsencode(target), CLONE_NOFOLLOW | CLONE_NOOWNERCOPY) == 0:
        return True
    code = ctypes.get_errno()
    if code in (errno.ENOTSUP, errno.EXDEV, errno.ENOSYS):
        return False
    raise OSError(code, os.strerror(code), str(target))


def seed(game, data):
    """在启动器运行前预置缺失的共享文件；返回已克隆的目标相对路径。失败不阻止启动。"""
    if sys.platform != 'darwin':
        return []
    seeded = []
    for relative_source, relative_target in SHARED_FILES:
        source, target = Path(game)/relative_source, Path(data)/relative_target
        if os.path.lexists(target) or source.is_symlink() or not source.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        # 先克隆到临时名再以不覆盖的方式链接到目标，避免与并发写入者竞争或留下残缺文件。
        staging = target.with_name('.mcpy-clone-' + uuid.uuid4().hex)
        try:
            if not clone(source, staging):
                return seeded
            os.link(staging, target)
            seeded.append(relative_target)
        except OSError:
            pass
        finally:
            if os.path.lexists(staging):
                staging.unlink()
    return seeded

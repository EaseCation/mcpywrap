"""Keep only the owned Windows game's initial UI thread from activating windows."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import time

from ..engines.host import EngineError


class ActivationGuard:
    def __init__(self):
        from ..host_assets import asset_directory
        root = asset_directory('window_activation')
        path = root/'mcpy-window-activation.dll'
        try:
            manifest = json.loads((root/'manifest.json').read_text(encoding='utf8'))
            if (manifest.get('background_window_protocol') != 1 or
                    hashlib.sha256(path.read_bytes()).hexdigest() != manifest.get('dll_sha256')):
                raise ValueError('activation guard checksum/protocol mismatch')
            library = C.WinDLL(str(path), use_last_error=True)
        except (OSError, ValueError) as error:
            raise EngineError('后台窗口保护组件不可用：' + str(error), 'background_window_unavailable',
                              '安装包含原生组件的完整 mcpywrap；源码开发先运行 scripts/build_all_native.py。'
                              '允许前台启动时可显式 --foreground。') from error
        library.McpyGuardInstall.argtypes = [W.DWORD, C.POINTER(W.DWORD)]
        library.McpyGuardInstall.restype = W.HANDLE
        library.McpyGuardResume.argtypes = [W.DWORD, W.DWORD]
        library.McpyGuardResume.restype = W.BOOL
        library.McpyGuardClose.argtypes = [W.HANDLE]
        library.McpyGuardClose.restype = W.BOOL
        self.library, self.hook = library, None

    def start(self, process):
        thread_id = W.DWORD()
        self.hook = self.library.McpyGuardInstall(process.pid, C.byref(thread_id))
        if not self.hook and (not thread_id.value or C.get_last_error() != 87):
            raise C.WinError(C.get_last_error())
        if not self.library.McpyGuardResume(process.pid, thread_id):
            raise C.WinError(C.get_last_error())
        # User32 cannot hook a thread before its GUI queue exists. Retry the
        # recorded initial thread during engine initialization; never hook all apps.
        deadline = time.monotonic() + 15
        while not self.hook and process.poll() is None and time.monotonic() < deadline:
            self.hook = self.library.McpyGuardInstall(process.pid, C.byref(thread_id))
            if not self.hook:
                if C.get_last_error() != 87:
                    raise C.WinError(C.get_last_error())
                time.sleep(.001)
        if not self.hook:
            raise EngineError('未能及时安装游戏窗口激活保护。', 'background_window_unavailable')

    def close(self):
        if self.hook:
            self.library.McpyGuardClose(self.hook)
            self.hook = None

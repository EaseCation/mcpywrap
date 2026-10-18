"""Bounded JSON RPC to a launcher-owned private Unix socket."""
import json
import os
from pathlib import Path
import socket
import stat

from .runtime_debug import MAX_RESULT


class LauncherControl:
    def __init__(self, metadata, pid):
        self.metadata, self.pid = Path(metadata), pid
        self.directory = None

    def request(self, method, params=None):
        if os.name != 'posix':
            raise ValueError('原生客户端 Unix 通道不可用于此平台；Windows 使用 Safaia')
        st = self.metadata.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077 or st.st_size > 4096:
            raise ValueError('启动器控制记录的归属或权限无效')
        info = json.loads(self.metadata.read_text(encoding='utf-8'))
        if info.get('protocol') != 1 or info.get('pid') != self.pid:
            raise ValueError('控制记录不属于当前游戏进程')
        parent = Path(info['socket']).parent
        owner = parent.lstat()
        if not stat.S_ISDIR(owner.st_mode) or owner.st_uid != os.getuid() or owner.st_mode & 0o077:
            raise ValueError('启动器 socket 目录不安全')
        if self.directory is not None and self.directory != parent:
            raise ValueError('启动器控制通道已改变')
        self.directory = parent
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
            stream.settimeout(3)
            stream.connect(info['socket'])
            payload = json.dumps({'id': 1, 'method': method, 'params': params or {}}, ensure_ascii=True)
            stream.sendall(payload.encode('utf-8') + b'\n')
            data = bytearray()
            while b'\n' not in data:
                block = stream.recv(4096)
                if not block:
                    raise ConnectionError('启动器控制通道已关闭')
                data.extend(block)
                if len(data) > MAX_RESULT * 2:
                    raise ValueError('原生控制响应过大')
        message = json.loads(data.split(b'\n', 1)[0])
        if message.get('id') != 1 or 'result' not in message:
            raise ValueError('启动器 RPC 响应无效')
        return message['result']

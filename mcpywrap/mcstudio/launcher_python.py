"""Client Python through the launcher's existing JNI bridge; server uses Safaia."""
from collections import deque
import json
import os
from pathlib import Path
import socket
import stat
import threading
import time
import uuid

from .runtime_debug import MAX_CODE, MAX_RESULT, script_request


class LauncherPythonChannel:
    def __init__(self, safaia, data_directory):
        self.safaia = safaia
        self.metadata = Path(data_directory) / 'python-control.json'
        self.pid = None
        self.serial = threading.Lock()
        self.finished = deque()

    @property
    def connected(self):
        return self.safaia.connected

    @property
    def last_error(self):
        return self.safaia.last_error

    def start(self, pid):
        self.pid = pid
        self.safaia.start(pid)

    def close(self):
        self.safaia.close()

    def _rpc(self, method, params=None):
        if os.name != 'posix':
            raise ValueError('原生客户端 Unix 通道不可用于此平台；Windows 使用 Safaia')
        st = self.metadata.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077 or st.st_size > 4096:
            raise ValueError('启动器 Python 控制记录的归属或权限无效')
        info = json.loads(self.metadata.read_text(encoding='utf-8'))
        if info.get('protocol') != 1 or info.get('pid') != self.pid:
            raise ValueError('Python 控制记录不属于当前游戏进程')
        parent = Path(info['socket']).parent
        owner = parent.lstat()
        if not stat.S_ISDIR(owner.st_mode) or owner.st_uid != os.getuid() or owner.st_mode & 0o077:
            raise ValueError('启动器 Python socket 目录不安全')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
            stream.settimeout(3)
            stream.connect(info['socket'])
            payload = json.dumps({'id': 1, 'method': method, 'params': params or {}}, ensure_ascii=True)
            stream.sendall(payload.encode('utf-8') + b'\n')
            data = bytearray()
            while b'\n' not in data:
                block = stream.recv(4096)
                if not block:
                    raise ConnectionError('启动器 Python 通道已关闭')
                data.extend(block)
                if len(data) > MAX_RESULT * 2:
                    raise ValueError('Python 执行结果过大')
        message = json.loads(data.split(b'\n', 1)[0])
        if message.get('id') != 1 or 'result' not in message:
            raise ValueError('启动器 Python RPC 响应无效')
        return message['result']

    @staticmethod
    def _normalize(result):
        result = dict(result, side='client')
        if result.get('state') == 'completed':
            payload = result.pop('value', None)
            if not isinstance(payload, dict) or not {'stdout', 'stderr', 'value', 'error'} <= payload.keys():
                return dict(result, state='failed', error='启动器 Python 返回格式无效')
            result.update(payload)
            result['state'] = 'failed' if payload.get('error') else 'completed'
        return result

    def _remember(self, result):
        request_id = result.get('request_id')
        if request_id and result.get('state') in ('completed', 'failed', 'cancelled') and request_id not in self.finished:
            self.finished.append(request_id)
            # Retain the latest 64 completed requests for explicit result lookup.
            while len(self.finished) > 64:
                try:
                    self._rpc('release', {'request_id': self.finished[0]})
                except (OSError, ValueError, ConnectionError):
                    break  # Housekeeping must not discard a confirmed result.
                self.finished.popleft()
        return result

    def _submit(self, code, condition=None, request_id=None):
        if not isinstance(code, str) or not code.strip() or len(code.encode('utf-8')) > MAX_CODE:
            raise ValueError('代码必须是非空 UTF-8 文本且不超过 32 KiB')
        if condition is not None and (not isinstance(condition, str) or len(condition.encode('utf-8')) > 4096):
            raise ValueError('等待条件必须是最多 4 KiB 的 Python 表达式')
        request_id = request_id or uuid.uuid4().hex
        source = script_request(code, request_id, emit_result=False)
        # Reuse Safaia's capture/exception/serialization contract. A persistent
        # client namespace permits definitions before and after entering a world.
        expression = (
            "(lambda scope: (eval(compile(%r, '<mcpy-client>', 'exec'), scope, scope), "
            "__import__('json').loads(scope['_m_serialized']))[-1])(__import__('__main__').__dict__.setdefault('_mcpy_client_scope', {}))"
        ) % source
        request = {'request_id': request_id, 'readiness': 'python', 'queue_timeout_ms': 120000,
                   'command': {'module_name': '__builtin__', 'func_name': 'eval',
                               'args': [expression], 'use_instance': False}}
        if condition is not None:
            request['condition'] = {'module_name': '__builtin__', 'func_name': 'eval',
                                    'args': ["eval(%r, __import__('__main__').__dict__.setdefault('_mcpy_client_scope', {}))" % condition],
                                    'use_instance': False}
        deadline = time.monotonic() + 2
        while not self.metadata.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        if not self.metadata.exists():
            return {'state': 'unavailable', 'side': 'client', 'request_id': request_id,
                    'error': '启动器客户端 Python 通道尚未建立；未提交代码'}
        try:
            result = self._normalize(self._rpc('submit', request))
        except (OSError, ValueError, ConnectionError) as error:
            return {'state': 'unknown', 'side': 'client', 'request_id': request_id,
                    'error': '提交结果未确认，请用同一 request_id 查询：' + str(error)}
        return self._remember(result)

    def submit(self, code, condition=None, request_id=None):
        with self.serial:
            if self.safaia.pending is not None:
                raise ValueError('Safaia 执行结果尚未确认')
            return self._submit(code, condition, request_id)

    def request(self, request_id, cancel=False):
        with self.serial:
            return self._remember(self._normalize(self._rpc('cancel' if cancel else 'result', {'request_id': request_id})))

    def status(self):
        if not self.metadata.exists():
            return {'state': 'starting', 'protocol': 1, 'pid': self.pid,
                    'python_ready': False, 'scripts_ready': False}
        return self._rpc('status')

    def execute(self, code, side='client', timeout=12, condition=None):
        if side not in ('client', 'server'):
            raise ValueError('执行侧必须为 client 或 server')
        if not self.serial.acquire(blocking=False):
            raise ValueError('已有游戏脚本正在执行')
        try:
            if side == 'server':
                if condition is not None:
                    raise ValueError('服务端继续使用 Safaia，不支持启动期等待条件')
                return self.safaia.execute(code, side, timeout)
            if self.safaia.pending is not None:
                raise ValueError('Safaia 执行结果尚未确认')
            result = self._submit(code, condition)
            deadline = time.monotonic() + timeout
            while result.get('state') in ('queued', 'running') and time.monotonic() < deadline:
                time.sleep(.05)
                try:
                    result = self._normalize(self._rpc('result', {'request_id': result['request_id']}))
                except (OSError, ValueError, ConnectionError) as error:
                    return dict(result, state='unknown', error='执行结果未确认，请查询原请求：' + str(error))
            return self._remember(result)
        finally:
            self.serial.release()

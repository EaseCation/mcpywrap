"""Session-owned Safaia script channel for the MC Studio game client."""
import base64
import json
import re
import socket
import socketserver
import struct
import threading
import time
import uuid

import psutil


MAX_FRAME = 1024 * 1024
MAX_CODE = 32 * 1024
MAX_RESULT = 256 * 1024
DISCOVERY_PORTS = range(26613, 26623)


def frame(kind, payload):
    data = payload.encode('utf-8') if isinstance(payload, str) else payload
    if len(data) > MAX_FRAME:
        raise ValueError('Safaia 消息过大')
    return struct.pack('<ii', kind, len(data)) + data


def recv_exact(sock, count):
    chunks = bytearray()
    deadline = time.monotonic() + 10
    while len(chunks) < count:
        try:
            part = sock.recv(count - len(chunks))
        except socket.timeout:
            if time.monotonic() >= deadline:
                raise
            continue
        if not part:
            raise ConnectionError('Safaia 连接已断开')
        chunks.extend(part)
    return bytes(chunks)


def recv_frame(sock):
    kind, size = struct.unpack('<ii', recv_exact(sock, 8))
    if size < 0 or size > MAX_FRAME:
        raise ValueError('Safaia 消息长度无效')
    return kind, recv_exact(sock, size)


def owned_udp_ports(pid):
    return {item.laddr.port for item in psutil.net_connections(kind='udp')
            if item.pid == pid and item.laddr and item.laddr.port in DISCOVERY_PORTS}


def owned_udp_endpoints(pid):
    endpoints = set()
    addresses = {'127.0.0.1'}
    for items in psutil.net_if_addrs().values():
        addresses.update(item.address for item in items if item.family == socket.AF_INET)
    for item in psutil.net_connections(kind='udp'):
        if item.pid != pid or not item.laddr or item.laddr.port not in DISCOVERY_PORTS:
            continue
        targets = addresses if item.laddr.ip == '0.0.0.0' else (item.laddr.ip,)
        endpoints.update((address, item.laddr.port) for address in targets)
    return endpoints


def script_request(code, request_id):
    encoded = base64.b64encode(code.encode('utf-8')).decode('ascii')
    # The game runs Python 2. The single result line is independent of user print output.
    return '''# coding: utf-8
import base64 as _m_b64, json as _m_json, sys as _m_sys, traceback as _m_tb
class _McpyCapture(object):
    def __init__(self): self.parts = []
    def write(self, text): self.parts.append(text)
    def flush(self): pass
_m_out, _m_err = _McpyCapture(), _McpyCapture()
_m_old_out, _m_old_err = _m_sys.stdout, _m_sys.stderr
_m_scope = globals()
_m_value, _m_error = None, None
def _m_text(parts):
    return u''.join([part if isinstance(part, unicode) else part.decode('utf-8', 'replace') for part in parts])
try:
    _m_sys.stdout, _m_sys.stderr = _m_out, _m_err
    _m_code = _m_b64.b64decode('%s')
    try:
        _m_value = eval(compile(_m_code, '<mcpy>', 'eval'), _m_scope, _m_scope)
    except SyntaxError:
        _m_scope.pop('_result', None)
        exec compile(_m_code, '<mcpy>', 'exec') in _m_scope, _m_scope
        _m_value = _m_scope.pop('_result', None)
except BaseException:
    _m_error = _m_tb.format_exc()
finally:
    _m_sys.stdout, _m_sys.stderr = _m_old_out, _m_old_err
try:
    _m_json.dumps(_m_value, allow_nan=False)
except (TypeError, ValueError):
    _m_value = {'type': type(_m_value).__name__, 'repr': repr(_m_value)}
_m_payload = {'stdout': _m_text(_m_out.parts), 'stderr': _m_text(_m_err.parts),
              'value': _m_value, 'error': _m_error}
_m_serialized = _m_json.dumps(_m_payload, ensure_ascii=True, allow_nan=False)
if len(_m_serialized) > 180000:
    _m_serialized = _m_json.dumps({'stdout': '', 'stderr': '', 'value': None,
                                  'error': 'result_too_large'})
print('__MCPY_RESULT_%s__' + _m_b64.b64encode(_m_serialized))
''' % (encoded, request_id)


class SafaiaChannel:
    def __init__(self, log_write):
        self.log_write = log_write
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(2)
        self.listener.settimeout(.2)
        self.port = self.listener.getsockname()[1]
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.stop_event = threading.Event()
        self.connected = threading.Event()
        self.changed = threading.Condition()
        self.serial = threading.Lock()
        self.client = None
        self.pid = None
        self.pending = None
        self.line_buffer = ''
        self.last_error = None
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.discovery = threading.Thread(target=self._discover, daemon=True)

    def start(self, pid):
        self.pid = pid
        self.thread.start()
        self.discovery.start()

    def _discover(self):
        payload = json.dumps({'ip': '127.0.0.1', 'port': self.port}).encode('utf-8')
        while not self.stop_event.is_set():
            if not self.connected.is_set():
                try:
                    for endpoint in owned_udp_endpoints(self.pid):
                        self.udp.sendto(payload, endpoint)
                except (OSError, psutil.Error):
                    pass
            self.stop_event.wait(.5)

    def _accept(self):
        while not self.stop_event.is_set():
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                client.settimeout(5)
                port = None
                for _ in range(8):
                    kind, payload = recv_frame(client)
                    if kind != 3:
                        continue
                    config = json.loads(payload.decode('utf-8'))
                    port = config.get('connect_port')
                    if isinstance(port, str) and port.isdecimal():
                        port = int(port)
                    if port is not None:
                        break
                if type(port) is not int or port not in owned_udp_ports(self.pid):
                    self.last_error = 'Safaia 握手端口不属于此游戏进程'
                    client.sendall(frame(49, '{"notify":"notify_block"}'))
                    continue
                client.sendall(frame(48, '{"notify":"pass"}'))
                client.settimeout(.2)
                with self.changed:
                    if self.client:
                        self.client.close()
                    self.client = client
                    self.last_error = None
                    self.line_buffer = ''
                    self.connected.set()
                    self.changed.notify_all()
                self._read(client)
            except (OSError, ValueError, ConnectionError, psutil.Error) as exc:
                self.last_error = 'Safaia 握手失败: ' + type(exc).__name__
            finally:
                with self.changed:
                    if self.client is client:
                        self.client = None
                        self.pending = None
                        self.connected.clear()
                        self.changed.notify_all()
                client.close()

    def _read(self, client):
        while not self.stop_event.is_set():
            try:
                kind, payload = recv_frame(client)
            except socket.timeout:
                continue
            if kind == 4:
                text = payload.decode('utf-8', errors='replace')
                self.log_write(text)
                with self.changed:
                    if self.pending:
                        self.line_buffer = (self.line_buffer + text)[-MAX_RESULT * 2:]
                        marker = self.pending['marker']
                        while '\n' in self.line_buffer:
                            line, self.line_buffer = self.line_buffer.split('\n', 1)
                            position = line.find(marker)
                            if position < 0:
                                continue
                            candidate = line[position + len(marker):].strip()
                            if candidate and re.fullmatch(r'[A-Za-z0-9+/]+={0,2}', candidate):
                                self.pending['result'] = candidate
                                if self.pending.get('timed_out'):
                                    self.pending = None
                                self.changed.notify_all()
            elif kind == 32:
                break

    def execute(self, code, side='client', timeout=12):
        if side not in ('client', 'server'):
            raise ValueError('执行侧必须为 client 或 server')
        if not isinstance(code, str) or not code.strip() or len(code.encode('utf-8')) > MAX_CODE:
            raise ValueError('代码必须是非空 UTF-8 文本且不超过 32 KiB')
        if not self.serial.acquire(blocking=False):
            raise ValueError('已有游戏脚本正在执行')
        try:
            if self.pending is not None:
                raise ValueError('上一请求结果未知，等待其完成或重新启动会话')
            request_id = uuid.uuid4().hex
            marker = '__MCPY_RESULT_' + request_id + '__'
            with self.changed:
                if not self.client:
                    return {'state': 'unavailable', 'side': side, 'request_id': request_id,
                            'error': self.last_error or '游戏 Safaia 调试连接尚未就绪'}
                self.pending = {'marker': marker, 'result': None}
                self.line_buffer = ''
                try:
                    self.client.sendall(frame(22 if side == 'client' else 23,
                                              script_request(code, request_id)))
                except OSError:
                    self.pending = None
                    return {'state': 'unavailable', 'side': side, 'request_id': request_id,
                            'error': '游戏调试连接已断开'}
                deadline = time.monotonic() + timeout
                while self.pending['result'] is None and self.client and not self.stop_event.is_set():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self.changed.wait(remaining)
                raw = self.pending['result'] if self.pending else None
                if raw is not None or not self.client or self.stop_event.is_set():
                    self.pending = None
                else:
                    self.pending['timed_out'] = True
            if raw is None:
                return {'state': 'unknown' if self.connected.is_set() else 'unavailable',
                        'side': side, 'request_id': request_id,
                        'error': '执行结果未在时限内返回；不要自动重试'}
            if len(raw) > MAX_RESULT:
                return {'state': 'failed', 'side': side, 'request_id': request_id,
                        'error': '执行结果超过 256 KiB'}
            try:
                data = json.loads(base64.b64decode(raw).decode('utf-8'))
            except (ValueError, UnicodeError):
                return {'state': 'failed', 'side': side, 'request_id': request_id,
                        'error': '游戏返回的执行结果无效'}
            return {'state': 'failed' if data.get('error') else 'completed',
                    'side': side, 'request_id': request_id, **data}
        finally:
            self.serial.release()

    def close(self):
        self.stop_event.set()
        with self.changed:
            if self.client:
                self.client.close()
            self.pending = None
            self.changed.notify_all()
        self.listener.close()
        self.udp.close()
        for thread in (self.thread, self.discovery):
            if thread.is_alive():
                thread.join(timeout=1)


class _ControlHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(20)
        try:
            size = struct.unpack('!I', recv_exact(self.request, 4))[0]
            if size > MAX_CODE * 2 + 4096:
                raise ValueError('控制请求过大')
            request = json.loads(recv_exact(self.request, size).decode('utf-8'))
            if request.get('token') != self.server.token:
                raise ValueError('会话控制凭据无效')
            if request.get('action') == 'execute':
                result = self.server.channel.execute(request.get('code'), request.get('side', 'client'))
            elif request.get('action') == 'reload':
                from .hot_reload import reload_code
                source = request.get('source')
                source = base64.b64decode(source, validate=True) if source is not None else None
                code = reload_code(request.get('kind'), request.get('target'), source)
                result = self.server.channel.execute(code, 'client')
            else:
                raise ValueError('未知的会话操作')
        except (OSError, ValueError, KeyError, UnicodeError) as exc:
            result = {'state': 'failed', 'error': str(exc)}
        except Exception:
            result = {'state': 'failed', 'error': '游戏调试通道内部错误'}
        payload = json.dumps(result, ensure_ascii=True, allow_nan=False).encode('utf-8')
        if len(payload) <= MAX_RESULT * 2:
            self.request.sendall(struct.pack('!I', len(payload)) + payload)


class RuntimeControlServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, channel, token):
        self.channel, self.token = channel, token
        super().__init__(('127.0.0.1', 0), _ControlHandler)
        self.thread = threading.Thread(target=self.serve_forever, kwargs={'poll_interval': .1}, daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=1)


def control_request(project, session, action, **options):
    from . import sessions
    from .processes import checked_process
    directory = sessions.session_path(project, session)
    data = sessions.read(project, session)
    if data['state'] != 'running' or not data.get('worker') or not checked_process(data['worker']):
        raise ValueError('游戏会话没有运行中的调试 worker')
    path = directory / 'control.json'
    if not path.is_file():
        raise ValueError('此会话没有运行时调试通道；请更新 CLI 后重新启动游戏')
    settings = json.loads(path.read_text(encoding='utf-8'))
    payload = json.dumps({'token': settings['token'], 'action': action, **options},
                         ensure_ascii=True).encode('utf-8')
    if len(payload) > MAX_CODE * 2 + 4096:
        raise ValueError('控制请求过大')
    with socket.create_connection(('127.0.0.1', settings['port']), timeout=3) as client:
        client.settimeout(18)
        client.sendall(struct.pack('!I', len(payload)) + payload)
        size = struct.unpack('!I', recv_exact(client, 4))[0]
        if size > MAX_RESULT * 2:
            raise ValueError('调试结果过大')
        return json.loads(recv_exact(client, size).decode('utf-8'))

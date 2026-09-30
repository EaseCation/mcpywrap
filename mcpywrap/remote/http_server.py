"""Versioned, bounded HTTP interface; no file server, arbitrary paths, or shell endpoint."""
import base64
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import urlsplit, parse_qs

from .service import RemoteError, fields


class GameHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, service, token=None):
        self.service, self.token = service, token
        if token and (not token.isascii() or any(ord(c) < 33 for c in token)):
            raise ValueError('MCPY_REMOTE_TOKEN 必须是不含空白的 ASCII 字符串')
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        # The default logger includes arbitrary request text. Log only method/status in do_request.
        pass

    def reply(self, data, status=200):
        content = data.pop('content', None)
        if content is not None:
            self.send_response(status)
            self.send_header('Content-Type', 'image/png')
            for key in ('width', 'height', 'session', 'service_instance'):
                self.send_header('X-Mcpy-' + key.replace('_', '-'), str(data[key]))
            if 'capture' in data:
                self.send_header('X-Mcpy-Capture', data['capture'])
                self.send_header('X-Mcpy-Capture-Fallback', 'true' if data.get('capture_fallback') else 'false')
                if data.get('capture_fallback_reason'):
                    reason = base64.b64encode(data['capture_fallback_reason'].encode('utf-8')).decode('ascii')
                    self.send_header('X-Mcpy-Capture-Fallback-Reason-B64', reason)
        else:
            content = json.dumps({'ok': status < 400, 'error': None, 'hint': None, **data},
                                 ensure_ascii=True, allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(content)

    def request_data(self):
        if self.headers.get('Transfer-Encoding'):
            raise RemoteError('不支持分块请求', 'invalid_request')
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise RemoteError('无效的请求长度', 'invalid_request') from None
        if not 0 <= length <= 65536:
            raise RemoteError('请求超过 64 KiB', 'invalid_request', 413)
        if self.headers.get_content_type() != 'application/json':
            raise RemoteError('请求必须是 application/json', 'invalid_request', 415)
        try:
            data = json.loads(self.rfile.read(length).decode('utf-8-sig'),
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, UnicodeError):
            raise RemoteError('请求不是有效的 UTF-8 JSON', 'invalid_request') from None
        if not isinstance(data, dict):
            raise RemoteError('请求必须是 JSON 对象', 'invalid_request')
        return data

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def dispatch(self):
        try:
            if self.server.token:
                provided = self.headers.get('Authorization', '').encode('utf-8')
                expected = ('Bearer '+self.server.token).encode('ascii')
                if not hmac.compare_digest(provided, expected):
                    raise RemoteError('访问令牌无效', 'unauthorized', 401)
            # Browsers aren't clients of this control protocol; no cross-origin mutation support.
            if self.headers.get('Origin'):
                raise RemoteError('不接受浏览器跨源控制请求', 'invalid_request', 403)
            path = urlsplit(self.path)
            parts = path.path.strip('/').split('/')
            query = parse_qs(path.query, keep_blank_values=True)
            if parts[:1] != ['v1']:
                raise RemoteError('不支持的接口版本或路径', 'not_found', 404)
            if self.command == 'POST' and query:
                raise RemoteError('POST 不接受查询参数', 'invalid_request')
            data = self.request_data() if self.command == 'POST' else {}
            service = self.server.service
            if parts == ['v1', 'capabilities'] and self.command == 'GET' and not query:
                result = service.describe()
            elif parts == ['v1', 'doctor'] and self.command == 'POST':
                result = service.inspect(data)
            elif parts == ['v1', 'sessions'] and not query:
                result = service.create(data) if self.command == 'POST' else service.list_sessions()
            elif len(parts) in (3, 4) and parts[:2] == ['v1', 'sessions']:
                session = parts[2]
                action = parts[3] if len(parts) == 4 else 'status'
                if action == 'status' and self.command == 'GET' and not query:
                    result = service.record(session)
                elif action == 'logs' and self.command == 'GET':
                    if query.keys() - {'source', 'tail'} or any(len(v) != 1 for v in query.values()):
                        raise RemoteError('无效的日志查询参数', 'invalid_request')
                    result = service.logs(session, query.get('source', ['game'])[0], int(query.get('tail', ['100'])[0]))
                elif action == 'py' and self.command == 'POST':
                    result = service.execute_python(session, data)
                elif action == 'stop' and self.command == 'POST':
                    fields(data, ())
                    result = service.stop(session)
                elif action in ('screenshot', 'key', 'mouse') and self.command == 'POST':
                    allowed = {'screenshot': (), 'key': ('keys', 'hold_ms'),
                               'mouse': ('action', 'x', 'y', 'width', 'height', 'to_x', 'to_y', 'dx', 'dy',
                                         'delta', 'button', 'duration_ms', 'keys')}
                    fields(data, allowed[action])
                    if action == 'key':
                        keys = data.get('keys')
                        if (not isinstance(keys, list) or not keys or not all(isinstance(k, str) for k in keys)
                                or type(data.get('hold_ms', 80)) is not int):
                            raise RemoteError('无效的按键参数', 'invalid_request')
                    if action == 'mouse' and (not isinstance(data.get('action'), str) or
                            not isinstance(data.get('keys', []), list) or
                            not all(isinstance(k, str) for k in data.get('keys', []))):
                        raise RemoteError('无效的鼠标参数', 'invalid_request')
                    result = service.desktop(session, action, data)
                else:
                    raise RemoteError('不支持的会话操作', 'not_found', 404)
            else:
                raise RemoteError('不支持的接口', 'not_found', 404)
            self.reply(result)
        except (BrokenPipeError, ConnectionResetError):
            pass  # A disconnected client never cancels or retries its game/input operation.
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.error_reply(str(exc), getattr(exc, 'code', 'execution_failed'),
                             getattr(exc, 'status', 400), getattr(exc, 'hint', None))
        except Exception:
            self.error_reply('服务内部错误，请查看 Windows 控制台', 'internal_error', 500)
            import traceback
            traceback.print_exc()

    def error_reply(self, message, code, status, hint=None):
        try:
            self.reply({'ok': False, 'error': message, 'code': code, 'hint': hint,
                        'service_instance': self.server.service.instance}, status)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

"""CLI routing and standard-library transport. Never falls back or retries mutations."""
import base64
import json
import os
from http.client import HTTPException
import socket
import struct
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlencode
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

import click
from .service import RemoteError, PROTOCOL, identifier

GAME_COMMANDS = {'doctor', 'connect', 'run', 'status', 'logs', 'stop', 'screenshot', 'key', 'mouse', 'py'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RemoteError('服务地址发生重定向，请配置最终地址', 'redirect_refused')


def bounded_response(response, limit=64 * 1024 * 1024):
    # Python 3.9 HTTPResponse.read(n) allocates n bytes even for a tiny JSON body.
    chunks, size = [], 0
    while True:
        block = response.read(min(1024 * 1024, limit + 1 - size))
        if not block:
            return b''.join(chunks)
        size += len(block)
        if size > limit:
            raise RemoteError('远端响应过大', 'invalid_response')
        chunks.append(block)


class Client:
    def __init__(self, endpoint, project, token=None):
        if not isinstance(endpoint, str):
            raise RemoteError('remote_url 必须是 HTTP 地址', 'invalid_remote')
        url = urlsplit(endpoint)
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path not in ('', '/')):
            raise RemoteError('远端地址应为 http://主机:端口，不含凭据或路径', 'invalid_remote')
        self.endpoint, self.project = endpoint.rstrip('/'), str(project)
        self.token = token if token is not None else os.environ.get('MCPY_REMOTE_TOKEN')
        if self.token and (not self.token.isascii() or any(ord(c) < 33 for c in self.token)):
            raise RemoteError('MCPY_REMOTE_TOKEN 必须是不含空白的 ASCII 字符串', 'invalid_remote')
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method, path, data=None, timeout=120, image=False):
        headers = {'Accept': 'image/png' if image else 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer '+self.token
        body = None
        if data is not None:
            body = json.dumps(data, ensure_ascii=True, allow_nan=False).encode('utf-8')
            headers['Content-Type'] = 'application/json; charset=utf-8'
        request = Request(self.endpoint+'/v1'+path, data=body, headers=headers, method=method)
        uncertain = '操作结果未知，不要重复输入；使用 status --list 找回会话。'
        if data and data.get('request_id'):
            uncertain += ' 请求 ID: '+data['request_id']
        try:
            response = self.opener.open(request, timeout=timeout)
        except HTTPError as exc:
            response = exc
        except (TimeoutError, socket.timeout) as exc:
            raise RemoteError('远端请求超时', 'remote_timeout', hint=uncertain) from exc
        except (URLError, OSError) as exc:
            raise RemoteError('无法连接远端测试服务', 'remote_unavailable',
                              hint='确认地址与服务状态；没有切换到本机。'+uncertain) from exc
        with response:
            try:
                raw = bounded_response(response)
            except (OSError, HTTPException) as exc:
                raise RemoteError('读取远端结果中断', 'remote_timeout', hint=uncertain) from exc
            if image and response.status == 200 and response.headers.get_content_type() == 'image/png':
                if not raw.startswith(b'\x89PNG\r\n\x1a\n') or len(raw) < 24:
                    raise RemoteError('远端未返回有效 PNG', 'invalid_response')
                width, height = struct.unpack('>II', raw[16:24])
                result = {'content': raw, 'width': width, 'height': height,
                          'service_instance': response.headers.get('X-Mcpy-Service-Instance')}
                capture = response.headers.get('X-Mcpy-Capture')
                if capture:
                    result['capture'] = capture
                    result['capture_fallback'] = response.headers.get('X-Mcpy-Capture-Fallback') == 'true'
                    reason = response.headers.get('X-Mcpy-Capture-Fallback-Reason-B64')
                    if reason:
                        try:
                            result['capture_fallback_reason'] = base64.b64decode(reason, validate=True).decode('utf-8')
                        except (ValueError, UnicodeError):
                            raise RemoteError('远端截图状态无效', 'invalid_response') from None
                return result
            try:
                result = json.loads(raw.decode('utf-8-sig'))
            except (ValueError, UnicodeError):
                raise RemoteError('远端未返回有效 JSON', 'invalid_response',
                                  hint=uncertain if method == 'POST' else None) from None
            if not isinstance(result, dict) or 'ok' not in result:
                raise RemoteError('远端返回格式不兼容', 'invalid_response')
            if response.status >= 400:
                raise RemoteError(result.get('error') or '远端操作失败', result.get('code', 'remote_error'),
                                  response.status, result.get('hint'))
        return self.normalize(result)

    def normalize(self, result):
        if 'project' in result:
            result['remote_project'] = result.pop('project')
        result.update(project=self.project, endpoint=self.endpoint, execution='remote')
        for record in result.get('sessions', []):
            self.normalize(record)
        for record in result.get('recordings', []):
            self.normalize(record)
        return result

    def download(self, method, path, output, data=None, frames=False):
        from ..recording_io import transfer
        headers = {'Accept': 'application/zip' if frames else 'video/mp4'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        body = None
        if data is not None:
            body = json.dumps(data, ensure_ascii=True, allow_nan=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        request = Request(self.endpoint + '/v1' + path, data=body, headers=headers, method=method)
        try:
            try:
                response = self.opener.open(request, timeout=330 if frames else 30)
            except HTTPError as exc:
                response = exc
            with response:
                if response.status != 200:
                    raw = response.read(65537)
                    try:
                        error = json.loads(raw)
                    except ValueError:
                        raise RemoteError('Invalid artifact error response', 'invalid_response') from None
                    raise RemoteError(error.get('error', 'Artifact download failed'), error.get('code', 'remote_error'), response.status)
                if response.headers.get_content_type() != headers['Accept']:
                    raise RemoteError('Unexpected artifact media type', 'invalid_response')
                try:
                    size = int(response.headers.get('Content-Length', ''))
                except ValueError:
                    raise RemoteError('Invalid artifact length', 'invalid_response') from None
                transfer(response, output, size, response.headers.get('X-Mcpy-Artifact-SHA256'), publish=not frames)
        except (URLError, TimeoutError, socket.timeout, HTTPException) as exc:
            raise RemoteError('Artifact transfer interrupted', 'remote_timeout',
                              hint='Download can be retried; no final output was published.') from exc

    def require(self, action):
        result = self.request('GET', '/capabilities', timeout=15)
        if result.get('protocol_version') != PROTOCOL:
            raise RemoteError('远端协议版本不兼容，请更新客户端或服务端', 'protocol_mismatch')
        if action not in result.get('capabilities', []):
            raise RemoteError('远端缺少能力: '+action, 'capability_missing')
        return result


def routed_command(name, parameters):
    if name not in GAME_COMMANDS:
        return False, None
    from ..command_context import project_dir, remote_url, json_output
    endpoint = remote_url()
    if not endpoint:
        return False, None
    p = dict(parameters)
    client = Client(endpoint, project_dir())
    for key in ('game_executable', 'game_executable_path', 'mcs_download_path'):
        if p.get(key):
            raise click.UsageError('游戏 EXE／下载目录请在 Windows serve 启动参数中配置')
    if name == 'run':
        if any(p.get(key) for key in ('new', 'list', 'delete', 'clean_all', 'instance_prefix', 'force')):
            raise click.UsageError('远端仅支持网络目标，不支持本地世界或实例管理')
        from ..dependencies import read_project
        from ..mcstudio.network import configured_target, prepare_project
        config = read_project(project_dir())
        target = configured_target(config)
        if target is None:
            raise click.UsageError('远端 run 需要配置服务器目标；本地世界使用 Windows 本机运行')
        prepare_project(project_dir(), config)
        p.update(host=target.host, port=target.port)
    if name in ('run', 'connect'):
        if not p.get('detach'):
            raise click.UsageError('远程启动需要 --detach；通过 logs/status/stop 管理会话')
        client.require('network-sessions')
        if p.get('mcs_auth'):
            client.require('mcs-auth')
        data = {k: p[k] for k in ('host', 'port', 'mcs_auth', 'engine_version') if p.get(k) is not None}
        data['request_id'] = p.get('request_id') or uuid.uuid4().hex
        result = client.request('POST', '/sessions', data)
        return True, result
    if name == 'doctor':
        info = client.require('doctor')
        return True, info if p.get('capabilities') else client.request('POST', '/doctor', {
            'mcs_auth': p.get('mcs_auth', False), 'engine_version': p.get('engine_version')})
    client.require(name)
    if name == 'status' and p.get('list_sessions'):
        if p.get('session'):
            raise click.UsageError('--session 与 --list 不能同时使用')
        return True, client.request('GET', '/sessions')
    session = identifier(p.get('session'))
    path = '/sessions/'+session
    if name == 'status':
        return True, client.request('GET', path)
    if name == 'logs':
        result = client.request('GET', path+'/logs?'+urlencode({'source': p['source'], 'tail': p['tail']}))
        if not json_output():
            click.echo(result['text'], nl=False)
            return True, None
        return True, result
    if name == 'stop':
        return True, client.request('POST', path+'/stop', {})
    if name == 'py':
        from ..commands.runtime_cmd import code_argument
        source = code_argument(p.get('code'), p.get('filename'))
        return True, client.request('POST', path+'/py', {'code': source, 'side': p['side']})
    if name == 'screenshot':
        from ..commands.desktop_cmd import output_path, save_image
        output = output_path(p['output'])
        result = client.request('POST', path+'/screenshot', {}, image=True)
        save_image(output, result.pop('content'))
        return True, client.normalize({'session': session, 'image': str(output), **result})
    data = {k: v for k, v in p.items() if k != 'session' and v is not None}
    # Click tuples have a stable JSON list representation.
    if 'keys' in data:
        data['keys'] = list(data['keys'])
    return True, client.request('POST', path+'/'+name, data)


def routed_recording(action, parameters):
    from ..command_context import project_dir, remote_url
    from ..recording_io import output_path, frame_result
    p = dict(parameters)
    client = Client(remote_url(), project_dir())
    client.require('record-frames' if action == 'frames' else 'record')
    session = identifier(p['session'])
    path = '/sessions/' + session + '/recordings'
    if action == 'start':
        return client.request('POST', path, {'duration': p['duration'], 'fps': p['fps'],
                                             'request_id': p.get('request_id') or uuid.uuid4().hex}, timeout=25)
    if action == 'status':
        if bool(p.get('recording')) == p['list_recordings']:
            raise click.UsageError('Specify --recording or --list')
        if p['list_recordings']:
            return client.request('GET', path)
    recording = identifier(p['recording'])
    path += '/' + recording
    if action == 'status':
        return client.request('GET', path)
    if action in ('stop', 'delete'):
        return client.request('POST', path + '/' + action, {}, timeout=30)
    output = output_path(p['output'], directory=action == 'frames')
    if action == 'download':
        data = client.request('GET', path)
        client.download('GET', path + '/video', output)
        return {**data, 'video': str(output)}
    client.download('POST', path + '/frames', output,
                    {'frames': list(p['frames']), 'times': list(p['times'])}, frames=True)
    return client.normalize(frame_result(output))

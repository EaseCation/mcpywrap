"""Small HTTP-independent game service. Never invokes Click or accepts shell commands."""
from contextlib import contextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import threading
import uuid

from .. import __version__
from ..mcstudio import sessions
from ..mcstudio.diagnostics import diagnose
from ..mcstudio.network import ServerTarget, prepare_network
from ..mcstudio.processes import checked_process

PROTOCOL = 1
ACTIONS = ['doctor', 'network-sessions', 'status', 'logs', 'stop', 'screenshot', 'key', 'mouse', 'py', 'input-sequence']
ID = re.compile(r'^[0-9a-f]{32}$')


class RemoteError(ValueError):
    def __init__(self, message, code='execution_failed', status=400, hint=None):
        super().__init__(message)
        self.code, self.status, self.hint = code, status, hint


def fields(data, allowed):
    if not isinstance(data, dict) or data.keys() - set(allowed):
        raise RemoteError('请求包含未知字段或不是 JSON 对象', 'invalid_request')


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise RemoteError('无效的会话或请求 ID', 'invalid_request')
    return value


def capabilities():
    from ..mcstudio.window import desktop_state
    from ..mcstudio.bridge_assets import inspect_bridge
    windows = os.name == 'nt'
    from ..mcstudio.recordings import inspect_media
    media = inspect_media()
    extra = (['record'] if media['record_available'] else []) + (['record-frames'] if media['frames_available'] else [])
    result = {'protocol_version': PROTOCOL, 'version': __version__,
            'capabilities': ACTIONS + ['mcs-auth'] + extra if windows else ['project', 'package', 'remote-client'],
            'media': media,
            'desktop': desktop_state(),
            'mcs_auth': inspect_bridge() if windows else {'component_available': False},
            'execution': 'local', 'platform': os.name}
    from ..engines.backend import get_backend
    from ..engines.host import describe
    backend = get_backend()
    result['host'] = describe()
    result['capabilities'] = list(dict.fromkeys(result['capabilities'] + list(backend.capabilities)))
    if backend.managed_install:
        result['runtime'] = backend.diagnose()
        result['resources_ready'] = result['runtime']['ok']
    return result


@contextmanager
def directory_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    stream = (root/'service.lock').open('a+b')
    try:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RemoteError('此数据目录已有服务运行', 'busy', 409) from None
        yield
    finally:
        stream.close()  # Kernel releases the lock, including when the service crashes.


class GameService:
    def __init__(self, root, engine_overrides=None):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.requests = self.root/'requests'
        self.requests.mkdir(exist_ok=True)
        self.engine_overrides = engine_overrides or {}
        self.instance = uuid.uuid4().hex
        self.closing = threading.Event()
        self.create_lock = threading.Lock()
        self.desktop_lock = threading.Lock()
        self.recording_start_lock = threading.Lock()
        self.action_cancel = threading.Event()
        self.desktop_session = None
        from ..mcstudio.recordings import cleanup
        cleanup(self.root)
        # A request interrupted before any worker record exists cannot have launched a game.
        for path in self.requests.glob('*.json'):
            if not ID.fullmatch(path.stem):
                continue
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('state') == 'starting' and not self.record_path(path.stem).is_file():
                data.update(state='failed', error='服务在完成启动前退出，请使用新的请求 ID 重试')
                sessions.save(path, data)

    def context(self, data):
        return {**data, 'execution': 'remote', 'service_instance': self.instance,
                'project': str(self.root)}

    def recording_action(self, session, action, recording=None, data=None):
        from ..mcstudio import recordings
        self.record(session)
        data = data or {}
        if action == 'start':
            fields(data, ('duration', 'fps', 'request_id'))
            with self.recording_start_lock:
                if self.closing.is_set():
                    raise RemoteError('Service is stopping', 'service_stopping', 503)
                result = recordings.start(self.root, session, data.get('duration', 10), data.get('fps', 30), data.get('request_id'))
                if self.closing.is_set():
                    recordings.stop(self.root, session, result['recording'])
            return self.context(result)
        fields(data, ())
        if action == 'status':
            return self.context(recordings.status(self.root, session, recording))
        if action == 'stop':
            return self.context(recordings.stop(self.root, session, recording))
        if action == 'delete':
            return self.context(recordings.delete(self.root, session, recording))
        raise RemoteError('Unknown recording action', 'not_found', 404)

    def describe(self):
        return self.context(capabilities())

    def record_path(self, session):
        return sessions.session_path(self.root, identifier(session))/'session.json'

    def record(self, session):
        path = self.record_path(session)
        if not path.is_file():
            request = self.requests/(session+'.json')
            if request.is_file():
                data = json.loads(request.read_text(encoding='utf-8'))
                return self.context({'session': session, 'request_id': session, 'state': data['state'],
                                     'error': data.get('error'), 'game': None, 'origin': 'remote'})
            raise RemoteError('此服务没有该会话', 'session_not_found', 404)
        raw = json.loads(path.read_text(encoding='utf-8'))
        if raw.get('origin') != 'remote':
            raise RemoteError('该会话不属于远程服务', 'session_not_owned', 403)
        data = sessions.read(self.root, session)
        # After a host crash, a newly spawned worker may not have recorded its PID yet.
        # Reserve the slot until it reports back or an explicit stop writes its cancellation marker.
        if raw.get('state') == 'starting' and not raw.get('worker') and not raw.get('game'):
            data['state'] = 'exited' if (path.parent/'stop').exists() else 'starting'
            data['error'] = None
        return self.context(data)

    def list_sessions(self):
        ids = {p.parent.name for p in (self.root/'.runtime/sessions').glob('*/session.json')}
        ids.update(p.stem for p in self.requests.glob('*.json'))
        result = []
        for session in sorted(ids):
            if not ID.fullmatch(session):
                continue
            try:
                result.append(self.record(session))
            except RemoteError as exc:
                if exc.code != 'session_not_owned':
                    raise
        return self.context({'sessions': result})

    def active(self):
        for data in self.list_sessions()['sessions']:
            if data['state'] in ('starting', 'running'):
                return True
            # Failed workers may leave a game alive; retired PID identities must not
            # reserve the desktop forever when Windows reuses them for other applications.
            if data['state'] == 'failed' and self.live_owned_process(data):
                return True
        return False

    @staticmethod
    def live_owned_process(data):
        for key in ('game', 'worker'):
            if data.get(key):
                try:
                    if checked_process(data[key]):
                        return True
                except ValueError:
                    continue  # A different identity is not a service-owned process.
        return False

    def inspect(self, data):
        fields(data, ('engine_version', 'mcs_auth'))
        overrides = self.overrides(data)
        if type(data.get('mcs_auth', False)) is not bool:
            raise RemoteError('mcs_auth 必须是布尔值', 'invalid_request')
        result = diagnose(overrides=overrides, mcs_auth=data.get('mcs_auth', False), read_project_config=False)
        result.update(desktop=capabilities()['desktop'])
        return self.context(result)

    def overrides(self, data):
        overrides = dict(self.engine_overrides)
        if data.get('engine_version') is not None:
            if not isinstance(data['engine_version'], str) or not data['engine_version']:
                raise RemoteError('engine_version 必须是非空字符串', 'invalid_request')
            overrides['engine_version'] = data['engine_version']
        return overrides

    def create(self, data):
        fields(data, ('request_id', 'host', 'port', 'mcs_auth', 'engine_version'))
        request_id = identifier(data.get('request_id'))
        if type(data.get('mcs_auth', False)) is not bool:
            raise RemoteError('mcs_auth 必须是布尔值', 'invalid_request')
        target = ServerTarget(data.get('host'), data.get('port', 19132), 'mcs' if data.get('mcs_auth') else 'none')
        overrides = self.overrides(data)
        request_path = self.requests/(request_id+'.json')
        if request_path.exists():
            prior = json.loads(request_path.read_text(encoding='utf-8'))
            if prior['parameters'] != data:
                raise RemoteError('同一请求 ID 不能用于不同参数', 'request_conflict', 409)
            result = self.record(request_id)
            result = self.context(sessions.handoff(result)) if result.get('game') else result
            result['ok'] = result['state'] not in ('failed', 'exited')
            return result
        if self.closing.is_set():
            raise RemoteError('服务正在停止', 'service_stopping', 503)
        if not self.create_lock.acquire(blocking=False):
            raise RemoteError('另一个游戏正在启动', 'busy', 409)
        request = {'parameters': data, 'state': 'starting', 'error': None}
        try:
            if self.active():
                raise RemoteError('已有活动会话，请先停止它', 'busy', 409)
            state = capabilities()['desktop']
            if not state['available']:
                raise RemoteError(state['reason'], 'desktop_unavailable', 409)
            sessions.save(request_path, request)
            engine, auth = prepare_network(target, engine_overrides=overrides, interactive=False)
            if self.closing.is_set():
                raise RemoteError('服务正在停止', 'service_stopping', 503)
            result = sessions.start(self.root, auth_context=auth, session_id=request_id,
                                    origin='remote', request_id=request_id,
                                    network={'target': asdict(target), 'engine': asdict(engine)})
            if self.closing.is_set():
                sessions.stop(self.root, request_id)
                raise RemoteError('服务正在停止，已请求清理会话', 'service_stopping', 503)
            request['state'] = result['state']
            sessions.save(request_path, request)
            return self.context(sessions.handoff(result))
        except Exception as exc:
            if request_path.exists():
                request.update(state='failed', error=str(exc))
                sessions.save(request_path, request)
            raise
        finally:
            self.create_lock.release()

    def stop(self, session):
        data = self.record(session)
        from ..mcstudio.recordings import stop_session
        stop_session(self.root, session)
        if self.desktop_session == session or self.closing.is_set():
            self.action_cancel.set()
        with self.desktop_lock:
            try:
                if self.record_path(session).is_file():
                    # record() has already checked any recorded process identities. This also
                    # cancels a late worker whose PID wasn't persisted before the host crashed.
                    (self.record_path(session).parent/'stop').touch()
                    result = sessions.stop(self.root, session)
                elif data['state'] == 'starting':
                    raise RemoteError('会话仍在预检，请稍后停止或关闭服务', 'busy', 409)
                else:
                    result = {'session': session, 'state': 'exited'}
                return self.context(result)
            finally:
                if not self.closing.is_set():
                    self.action_cancel.clear()

    def logs(self, session, source='game', tail=100):
        self.record(session)
        return self.context({'session': session, 'source': source,
                             'text': sessions.logs(self.root, session, tail, source)})

    def execute_python(self, session, data):
        fields(data, ('code', 'side'))
        if not isinstance(data.get('code'), str) or not data['code'].strip():
            raise RemoteError('code 必须是非空字符串', 'invalid_request')
        record = self.record(session)
        if record.get('mode') != 'network' or record.get('state') != 'running':
            raise RemoteError('仅运行中的远程联机会话支持 Python 执行', 'session_unavailable', 409)
        if data.get('side', 'client') != 'client':
            raise RemoteError('联机会话只能在客户端执行 Python', 'unsupported', 400)
        from ..mcstudio.runtime_debug import control_request
        result = control_request(self.root, session, 'execute', code=data.get('code'), side='client')
        return self.context({'session': session, 'ok': result.get('state') == 'completed', **result})

    def desktop(self, session, action, data):
        self.record(session)
        if self.closing.is_set():
            raise RemoteError('服务正在停止', 'service_stopping', 503)
        if not self.desktop_lock.acquire(blocking=False):
            raise RemoteError('桌面正在执行另一个操作', 'busy', 409)
        try:
            self.desktop_session = session
            from ..mcstudio.window import operate
            return self.context(operate(self.root, session, action, data, self.action_cancel))
        finally:
            self.desktop_session = None
            self.desktop_lock.release()

    def close(self):
        self.closing.set()
        self.action_cancel.set()
        from ..mcstudio.recordings import stop_session
        errors = []
        with self.recording_start_lock:
            for data in self.list_sessions()['sessions']:
                try:
                    stop_session(self.root, data['session'])
                except (ValueError, OSError) as exc:
                    errors.append(str(exc))
        # In-flight preparation finishes without launching, or its newly launched session is stopped.
        with self.create_lock:
            for data in self.list_sessions()['sessions']:
                if data['state'] == 'exited' or (data['state'] == 'failed' and not self.live_owned_process(data)):
                    continue
                try:
                    self.stop(data['session'])
                except (ValueError, OSError) as exc:
                    errors.append(str(exc))
            if errors:
                raise RemoteError('部分会话未能清理: ' + '; '.join(errors), 'cleanup_failed', 500)

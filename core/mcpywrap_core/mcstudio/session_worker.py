"""会话 worker：先启动日志接收，再启动游戏，最后关闭监听。"""
import json
import subprocess
import uuid
import sys
import time
from pathlib import Path

from . import sessions
from .file_logs import FileLogServer
from .processes import identity


def run(project, session):
    directory = sessions.session_path(project, session)
    path = directory / 'session.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    data.update(project=str(Path(project).resolve()), session=session)
    data['worker'] = identity(__import__('os').getpid())
    sessions.save(path, data)
    process = None
    backend = None
    game_exited = False
    receiver = None
    engine_capture = None
    debug_channel = None
    control_server = None
    deployment = None
    guard = None
    group_monitor = None
    ready_recorded = False
    auth_context = None
    auth_path = directory/'auth.cppconfig'
    try:
        auth_context = None
        if data.get('mcs_auth'):
            from .mcs_auth import AuthContext
            from .private_logs import RedactedDecoder
            try:
                payload = json.loads(sys.stdin.buffer.read(65536).decode('utf-8'))
                auth_context = AuthContext.parse(payload, data['mcs_pid'])
            except (ValueError, KeyError, UnicodeError):
                raise ValueError('未能接收有效的 MC Studio 身份，请从命令行重新启动本次测试。') from None
            secrets = auth_context.secrets()
            receiver = FileLogServer(data['log_path'], decoder_factory=lambda: RedactedDecoder(secrets))
        else:
            receiver = FileLogServer(data['log_path'])
        receiver.start()
        sessions.require_launch_requested(project, session)
        from ..engines.backend import get_backend
        backend = get_backend(data.get('backend', 'windows'))
        data['phase'] = 'preparing'
        sessions.save(path, data)
        launched = backend.launch(data, receiver, auth_context)
        process = launched.process
        deployment, guard = launched.deployment, launched.guard
        if process:
            data['game'] = identity(process.pid)
            sessions.save(path, data)
        if not process or process.poll() is not None:
            raise ValueError('游戏进程未成功启动，详见 worker.log 和 engine.log')
        if launched.capture_output:
            from .private_logs import EngineLogCapture
            engine_capture = EngineLogCapture(process.stdout, directory/'engine.log',
                                              auth_context.secrets() if auth_context else ())
        from .runtime_debug import RuntimeControlServer
        debug_channel = backend.debug_channel(data, receiver._write)
        debug_channel.start(process.pid)
        token = uuid.uuid4().hex
        control_server = RuntimeControlServer(debug_channel, token, project, session, mode=data.get('mode', 'local'))
        control_server.start()
        from ..runtime.groups import is_local_guest
        guest = is_local_guest(project, data)
        sessions.save(directory/'control.json', {'port': control_server.server_address[1],
                                                 'token': token,
                                                 'unified_input_worker': True,
                                                 'python_reload_sides': ['client'] if guest else [] if data.get('mode') == 'network' else ['client', 'server'],
                                                 'client_python_queue': callable(getattr(debug_channel, 'submit', None))})
        data.update(state='running', game=identity(process.pid))
        sessions.save(path, data)
        if data.get('group') and data.get('role') in ('guest', 'client2'):
            from ..runtime.groups import GroupMonitor
            group_monitor = GroupMonitor(data).start()
        while process.poll() is None:
            if (directory / 'stop').exists():
                process.terminate()
                break
            changed = backend.refresh(data, debug_channel)
            connected = getattr(debug_channel, 'connected', None)
            if connected is not None and callable(getattr(connected, 'is_set', None)):
                state = 'connected' if connected.is_set() else 'connecting'
                error = getattr(debug_channel, 'last_error', None)
                if (data.get('control_state'), data.get('control_error')) != (state, error):
                    data.update(control_state=state, control_error=error)
                    changed = True
            if data.get('world_ready') and not ready_recorded:
                from ..utils.locks import LockBusy
                try:
                    if deployment:
                        with deployment.lock():
                            deployment.commit()
                except LockBusy:
                    # A status/start operation may briefly own the deployment.
                    # Retry even if the backend emits its ready transition once.
                    pass
                else:
                    from ..runtime.instances import mark
                    mark(data, ready=True)
                    ready_recorded = True
                    changed = True
            if changed:
                sessions.save(path, data)
            time.sleep(0.2)
        code = process.wait(timeout=10)
        game_exited = True
        data.update(state='exited', exit_code=code)
    except Exception as exc:
        from ..runtime.diagnostics import diagnostic, format_diagnostic
        failure = diagnostic(exc, auth_context.secrets() if auth_context else ())
        if not failure['operation_id'] and data.get('operation_id'):
            failure['operation_id'] = data['operation_id']
        data.update(state='failed', **failure)
        from ..utils.console import echo
        echo(format_diagnostic(failure), err=True)
        from ..project_scripts import ScriptError
        if isinstance(exc, ScriptError):
            data['script_error'] = failure['details']
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
                game_exited = True
            except subprocess.TimeoutExpired:
                data['error'] += '；游戏尚未确认退出，进程保留，请查询状态并重试 stop'
    finally:
        activation_guard = getattr(process, '_mcpy_activation_guard', None) if process else None
        if activation_guard:
            activation_guard.close()
        if group_monitor:
            group_monitor.close()
        if deployment and (not process or process.poll() is not None):
            try:
                with deployment.lock():
                    deployment.rollback(confirmed_exit=game_exited)
            except Exception as exc:
                data.update(state='failed', error=str(exc), code='recovery_required')
        if data.get('mode') == 'local' and not data.get('world_ready'):
            from ..runtime.instances import mark
            try:
                mark(data)
            except (OSError, ValueError):
                pass
        if guard:
            guard.close()
        if backend and game_exited:
            try:
                backend.finish(data)
            except Exception as exc:
                data.update(state='failed', error='游戏已退出，但用户偏好保存失败：' + str(exc))
        if control_server:
            control_server.close()
        if debug_channel:
            debug_channel.close()
        (directory/'control.json').unlink(missing_ok=True)
        try:
            if engine_capture:
                engine_capture.close()
        except OSError as exc:
            data.update(state='failed', error=str(exc))
        finally:
            if receiver:
                receiver.close()
            auth_path.unlink(missing_ok=True)
            if data.get('mode') == 'network':
                (directory/'runtime.cppconfig').unlink(missing_ok=True)
            sessions.save(path, data)


if __name__ == '__main__':
    run(*sys.argv[1:3])

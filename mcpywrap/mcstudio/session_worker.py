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
        if (directory / 'stop').exists():
            raise ValueError('启动已取消')
        from ..engines.backend import get_backend
        backend = get_backend(data.get('backend', 'windows'))
        launched = backend.launch(data, receiver, auth_context)
        process = launched.process
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
        control_server = RuntimeControlServer(debug_channel, token, project, session)
        control_server.start()
        sessions.save(directory/'control.json', {'port': control_server.server_address[1],
                                                 'token': token,
                                                 'unified_input_worker': True,
                                                 'python_reload_sides': ['client', 'server'],
                                                 'client_python_queue': callable(getattr(debug_channel, 'submit', None))})
        data.update(state='running', game=identity(process.pid))
        sessions.save(path, data)
        while process.poll() is None:
            if (directory / 'stop').exists():
                process.terminate()
                break
            if backend.refresh(data, debug_channel):
                sessions.save(path, data)
            time.sleep(0.2)
        code = process.wait(timeout=10)
        game_exited = True
        data.update(state='exited', exit_code=code)
    except Exception as exc:
        data.update(state='failed', error=str(exc))
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
                game_exited = True
            except subprocess.TimeoutExpired:
                data['error'] += '；保存退出尚未完成，进程保留，请查询状态并重试 stop'
    finally:
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

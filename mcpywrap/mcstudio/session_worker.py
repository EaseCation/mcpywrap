"""会话 worker：先启动日志接收，再启动游戏，最后关闭监听。"""
import json
import uuid
import sys
import time
from pathlib import Path

from ..command_context import project_scope
from . import sessions
from .file_logs import FileLogServer
from .processes import identity


def run(project, session):
    directory = sessions.session_path(project, session)
    path = directory / 'session.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    data['worker'] = identity(__import__('os').getpid())
    sessions.save(path, data)
    process = None
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
        if data.get('mode') == 'network':
            from .network import launch_network, ServerTarget
            from .discovery import Engine
            process = launch_network(Engine(**data['network']['engine']),
                                     ServerTarget(**data['network']['target']),
                                     directory/'runtime.cppconfig', receiver.port, auth_context)
            success = bool(process)
        else:
            from ..commands.run_cmd import _run_game_with_instance
            with project_scope(project):
                success, process = _run_game_with_instance(
                    data['config_path'], data['level_id'], [], wait=False,
                    engine_overrides=data['engine_overrides'], no_gui=True, logging_port=receiver.port,
                    output_path=str(directory / 'engine.log'), capture_output=True,
                    **({'auth_context': auth_context, 'auth_config_path': str(auth_path)} if auth_context else {}))
        if success and process:
            from .private_logs import EngineLogCapture
            engine_capture = EngineLogCapture(process.stdout, directory/'engine.log',
                                              auth_context.secrets() if auth_context else ())
        if not success or not process or process.poll() is not None:
            raise ValueError('游戏进程未成功启动，详见 worker.log 和 engine.log')
        from .runtime_debug import SafaiaChannel, RuntimeControlServer
        debug_channel = SafaiaChannel(receiver._write)
        debug_channel.start(process.pid)
        token = uuid.uuid4().hex
        control_server = RuntimeControlServer(debug_channel, token)
        control_server.start()
        sessions.save(directory/'control.json', {'port': control_server.server_address[1],
                                                 'token': token})
        data.update(state='running', game=identity(process.pid))
        sessions.save(path, data)
        while process.poll() is None:
            if (directory / 'stop').exists():
                process.terminate()
                break
            time.sleep(0.2)
        code = process.wait(timeout=10)
        data.update(state='exited', exit_code=code)
    except Exception as exc:
        data.update(state='failed', error=str(exc))
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
    finally:
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

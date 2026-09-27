"""会话 worker：先启动日志接收，再启动游戏，最后关闭监听。"""
import json
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
    try:
        receiver = FileLogServer(data['log_path'])
        receiver.start()
        if (directory / 'stop').exists():
            raise ValueError('启动已取消')
        from ..commands.run_cmd import _run_game_with_instance
        with project_scope(project):
            success, process = _run_game_with_instance(
                data['config_path'], data['level_id'], [], wait=False,
                engine_overrides=data['engine_overrides'], no_gui=True, logging_port=receiver.port,
                output_path=str(directory / 'engine.log'))
        if not success or not process or process.poll() is not None:
            raise ValueError('游戏进程未成功启动，详见 worker.log')
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
        if receiver:
            receiver.close()
        sessions.save(path, data)


if __name__ == '__main__':
    run(*sys.argv[1:3])

"""一次运行对应一个会话；记录与日志保留在项目中，无常驻服务。"""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .processes import checked_process, background_options


def session_path(project, session):
    if not isinstance(session, str) or len(session) != 32 or any(c not in '0123456789abcdef' for c in session):
        raise ValueError('无效的会话 ID')
    return Path(project).resolve() / '.runtime' / 'sessions' / session


def save(path, record):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    # Windows 上查询进程短暂打开记录时可能阻止替换；有界重试共享冲突。
    for attempt in range(10):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if os.name != 'nt' or attempt == 9:
                raise
            time.sleep(0.02)


def read(project, session):
    path = session_path(project, session) / 'session.json'
    if not path.is_file():
        raise ValueError(f'会话不存在: {session}')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data['state'] in ('starting', 'running'):
        game = checked_process(data['game']) if data.get('game') else None
        worker = checked_process(data['worker']) if data.get('worker') else None
        if not worker:
            data['state'] = 'failed'
            data['error'] = '会话 worker 已退出' + ('；游戏仍运行，可执行 stop' if game else '')
        elif data.get('game') and not game:
            data['state'] = 'exited'
    return data


def start(project, config_path=None, level_id=None, overrides=None, timeout=30, auth_context=None,
          network=None, session_id=None, origin=None, request_id=None, backend=None, launch=None):
    root = Path(project).resolve()
    session = session_id or uuid.uuid4().hex
    directory = session_path(root, session)
    directory.mkdir(parents=True, exist_ok=False)
    record = {'session': session, 'project': str(root), 'state': 'starting', 'game': None,
              'origin': origin, 'request_id': request_id, 'created_at': time.time(),
              'worker': None, 'error': None, 'log_path': str(directory / 'game.log'),
              'engine_log_path': str(directory / 'engine.log'),
              'config_path': str(Path(config_path).resolve()) if config_path else str(directory / 'runtime.cppconfig'),
              'level_id': level_id, 'mode': 'network' if network else 'local',
              'network': network,
              'backend': backend or 'windows', 'launch': launch,
              'engine_overrides': overrides or {}, 'mcs_auth': auth_context is not None,
              'mcs_pid': auth_context.mcs_pid if auth_context else None}
    save(directory / 'session.json', record)
    with (directory / 'worker.log').open('wb') as log:
        process = subprocess.Popen([sys.executable, '-m', 'mcpywrap.mcstudio.session_worker', str(root), session],
                                   cwd=root, stdin=subprocess.PIPE if auth_context else subprocess.DEVNULL,
                                   stdout=log, stderr=log,
                                   env=dict(os.environ, PYTHONIOENCODING='utf-8'),
                                   **background_options())
    if auth_context:
        try:
            process.stdin.write(json.dumps(auth_context.to_payload()).encode('utf-8'))
            process.stdin.close()
        except (OSError, BrokenPipeError):
            (directory/'stop').touch()
            raise ValueError('启动进程未能接收登录身份，请重试；凭据未写入会话记录。') from None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # worker 是记录的唯一写入者，父进程不与其竞争覆盖。
        try:
            data = json.loads((directory / 'session.json').read_text(encoding='utf-8'))
        except PermissionError:
            if os.name != 'nt':
                raise
            time.sleep(0.1)
            continue
        if data['state'] == 'running':
            return data
        if data['state'] in ('failed', 'exited') or process.poll() is not None:
            raise ValueError(f'游戏启动失败: {data.get("error") or data["state"]}；日志: {directory / "worker.log"}')
        time.sleep(0.1)
    (directory / 'stop').touch()
    raise ValueError(f'启动等待超时，已请求取消会话 {session}；日志: {directory / "worker.log"}')


def handoff(data):
    """本地与网络游戏共用同一进程身份和窗口脚本入口。"""
    result = {'application': 'game', 'project': data['project'], 'session': data['session'],
              'state': data['state'], **data['game'], 'log_path': data['log_path'],
              'engine_log_path': data.get('engine_log_path'),
              'mode': data.get('mode', 'local'),
              'window_title_hint': 'Minecraft', 'window_verified': False}
    if data.get('mode', 'local') == 'local' and data.get('config_path'):
        result['instance'] = data.get('level_id')
        result['config_path'] = data['config_path']
        if str(data['config_path']).endswith('.cppconfig'):
            result['config_hint'] = ('需要自定义世界时，可手动编辑此文件，再用 run --new --cppconfig <该文件路径> 创建实例；'
                                     '已有世界继续使用存档中的设置。')
    from ..engines.backend import get_backend
    result.update(get_backend(data.get('backend', 'windows')).handoff(data))
    if data.get('network'):
        target = data['network']['target']
        result.update(host=target['host'], port=target['port'], identity_source=target['auth'],
                      identity_provided=data['mcs_auth'], authenticated=False,
                      connection_verified=False, addons_assembled=False,
                      engine_version=data['network']['engine']['version'])
    return result


def show_configuration(result):
    """CLI presentation shared by foreground backends; JSON handoffs retain fields."""
    import click
    if result.get('config_path'):
        click.echo('实例配置：' + result['config_path'])
        if result.get('config_hint'): click.echo(result['config_hint'])


def stop(project, session):
    data = read(project, session)
    from .recordings import stop_session
    stop_session(project, session)
    # 先核对身份，再发停止请求。worker 失效时也能准确清理自己创建的游戏。
    game = checked_process(data['game']) if data.get('game') else None
    worker = checked_process(data['worker']) if data.get('worker') else None
    if worker or data['state'] == 'starting':
        (session_path(project, session) / 'stop').touch()
    if game:
        game.terminate()
        try:
            game.wait(timeout=10)
        except Exception as exc:
            raise ValueError('游戏未在 10 秒内退出，请查询会话状态') from exc
    if worker:
        try:
            worker.wait(timeout=10)
        except Exception as exc:
            raise ValueError('worker 尚未退出，请查询会话状态') from exc
    # Also clear credentials when the worker previously crashed before its finally block.
    (session_path(project, session)/'auth.cppconfig').unlink(missing_ok=True)
    if data.get('mode') == 'network':
        (session_path(project, session)/'runtime.cppconfig').unlink(missing_ok=True)
    return {'session': session, 'state': 'exited'}


def failed_exit(project, session, data):
    """Requested termination may be nonzero; worker failures are never masked."""
    if data.get('state') == 'failed':
        return True
    return bool(data.get('exit_code', 0)) and not (session_path(project, session)/'stop').is_file()


def logs(project, session, tail=100, source='game'):
    from collections import deque
    if source not in ('game', 'engine', 'worker') or type(tail) is not int or not 1 <= tail <= 10000:
        raise ValueError('无效的日志来源或行数')
    path = session_path(project, session) / (source + '.log')
    if not (path.parent / 'session.json').is_file():
        raise ValueError('会话不存在')
    if not path.is_file():
        return ''
    with path.open(encoding='utf-8', errors='replace') as stream:
        return ''.join(deque(stream, maxlen=tail))

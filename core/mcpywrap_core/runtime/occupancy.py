"""Reconcile recorded reservations with process identities, never just timestamps."""
from pathlib import Path
from contextlib import contextmanager
import os

from .storage import read
from ..engines.host import EngineError
def observed_process(record):
    # Offline assembly does not inspect processes unless an active record exists.
    from ..mcstudio.processes import observed_process as observe
    return observe(record)


def live(record):
    for name in ('game', 'worker', 'starter'):
        identity = record.get(name)
        if not identity or (name == 'starter' and record.get('worker')):
            continue
        try:
            if observed_process(identity):
                if name != 'starter' or record.get('state') == 'starting':
                    return True
        except ValueError as exc:
            raise EngineError('无法确认会话是否已退出：' + str(record.get('session')), 'recovery_required', str(exc)) from exc
    return False


def active(project, *, exclude=()):
    found = []
    for path in (Path(project) / '.runtime/sessions').glob('*/session.json'):
        if path.parent.name in exclude:
            continue
        data = read(path)
        if live(data):
            found.append(data)
    return found


def path_key(path):
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def launch_identity_missing(record):
    return (record.get('state') == 'starting' and record.get('phase') == 'prepared'
            and not record.get('game'))


def require_idle(records, message='运行包正在使用，请先停止相关会话。'):
    if records:
        raise EngineError(message, 'deployment_in_use',
                          '先查询状态，保存退出相关世界后重新运行。',
                          sessions=[r['session'] for r in records])


@contextmanager
def session_lease(directory, resource, session=None, label='资源', busy_code='resource_in_use'):
    """Retain process-backed ownership after a crashed worker releases its lock."""
    from .storage import write
    from ..utils.locks import directory_lock
    with directory_lock(directory):
        owner_path = Path(directory)/'owner.json'
        owner = read(owner_path)
        if owner:
            previous = read(owner['session_path'])
            if previous is None:
                raise EngineError(label + '的上次会话记录缺失，无法确认占用已释放。', 'recovery_required',
                                  resource=str(resource), session=owner.get('session'))
            if live(previous):
                raise EngineError(label + '仍被另一个游戏会话使用。', busy_code,
                                  resource=str(resource), session=owner.get('session'), project=previous.get('project'))
            if launch_identity_missing(previous):
                raise EngineError('上次启动在记录游戏身份前中断，尚不能确认' + label + '占用。',
                                  'recovery_required', resource=str(resource), session=owner.get('session'))
        if session is not None:
            from ..mcstudio.sessions import session_path
            write(owner_path, {'session': session['session'],
                              'session_path': str(session_path(session['project'], session['session'])/'session.json')})
        yield

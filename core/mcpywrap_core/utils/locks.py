"""Non-blocking process and thread locks, released by the OS on process exit."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import hashlib
import os
import threading


class LockBusy(ValueError):
    code = 'busy'
    hint = '另一个操作正在使用此资源，请稍后重试。'


_guard = threading.Lock()
_locks = {}
_local = threading.local()
_storage = ContextVar('mcpy_lock_storage', default=None)


@contextmanager
def lock_storage(directory):
    """Host-selected coordination storage, for filesystems without OS file locks.

All callers coordinating the same workspace must use the same storage backend.
This moves only lock files, never project files or build output. The logical
resource key remains its canonical public path.
"""
    token = _storage.set(Path(directory).resolve())
    try:
        yield
    finally:
        _storage.reset(token)


def lock_file_path(resource, default):
    """Map any logical lock to the same host-owned storage policy."""
    storage = _storage.get()
    if storage is None:
        return Path(default)
    key = os.path.normcase(str(Path(resource).resolve()))
    return storage / hashlib.sha256(key.encode('utf-8')).hexdigest() / 'service.lock'


@contextmanager
def directory_lock(root, *, reentrant=False):
    root = Path(root).resolve()
    key = os.path.normcase(str(root))
    with _guard:
        lock = _locks.setdefault(key, threading.RLock())
    if not lock.acquire(blocking=False):
        raise LockBusy('资源正在使用：' + str(root))
    held = getattr(_local, 'held', None)
    if held is None:
        held = _local.held = set()
    stream = None
    nested = key in held
    try:
        if nested and not reentrant:
            raise LockBusy('资源正在使用：' + str(root))
        if not nested:
            physical = lock_file_path(root, root/'service.lock')
            physical.parent.mkdir(parents=True, exist_ok=True)
            stream = physical.open('a+b')
            stream.seek(0, 2)
            if not stream.tell():
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise LockBusy('资源正在使用：' + str(root)) from exc
            held.add(key)
        yield
    finally:
        if stream is not None:
            stream.close()
        if not nested:
            held.discard(key)
        lock.release()

"""Non-blocking process and thread locks, released by the OS on process exit."""
from contextlib import contextmanager
from pathlib import Path
import os
import threading


class LockBusy(ValueError):
    code = 'busy'
    hint = '另一个操作正在使用此资源，请稍后重试。'


_guard = threading.Lock()
_locks = {}
_local = threading.local()


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
            root.mkdir(parents=True, exist_ok=True)
            stream = (root / 'service.lock').open('a+b')
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

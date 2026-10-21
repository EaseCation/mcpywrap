"""Bounded, incremental local session logs for any CLI consumer."""
import codecs
import time

from . import sessions

CHUNK = 64 * 1024
HISTORY_LIMIT = 256 * 1024
SOURCES = ('game', 'engine', 'worker')
ACTIVE = ('starting', 'running', 'pending')


class LogCursor:
    def __init__(self, path, tail):
        self.path, self.tail = path, tail
        self.stream = None
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.identity = None
        self.missing = False

    def read(self):
        """Read at most one bounded chunk; keep decoder state across writes."""
        try:
            info = self.path.stat()
        except FileNotFoundError:
            self.missing = True
            return '', False
        identity = (info.st_dev, info.st_ino)
        reset = self.stream is not None and (identity != self.identity or info.st_size < self.stream.tell())
        if reset:
            self.close()
            self.decoder.reset()
        if self.stream is None:
            self.stream = self.path.open('rb')
            self.identity = identity
            if self.tail and not reset:
                self.stream.seek(max(0, info.st_size - HISTORY_LIMIT))
                truncated = self.stream.tell() > 0
                data = self.stream.read(HISTORY_LIMIT)
                lines = data.splitlines(keepends=True)
                if truncated and lines:
                    lines = lines[1:]
                data = b''.join(lines[-self.tail:])
                return self.decoder.decode(data), reset
            self.stream.seek(0 if reset or self.missing else info.st_size)
        return self.decoder.decode(self.stream.read(CHUNK)), reset

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


def follow(project, *, session=None, group=None, source='all', tail=100, interval=.25):
    """Yield JSON-serializable events until every selected session has ended.

    Group membership is refreshed from its public service. This function only
    reads logs and session state; disconnecting a consumer never stops a game.
    """
    if bool(session) == bool(group) or source not in (*SOURCES, 'all'):
        raise ValueError('指定有效的 session/group 与日志来源')
    if type(tail) is not int or not 0 <= tail <= 10000:
        raise ValueError('tail 必须在 0..10000 之间')
    sources = SOURCES if source == 'all' else (source,)
    cursors, states = {}, {}
    members, next_status = [], 0
    def event(kind, **data):
        return dict(schema_version=1, event=kind, **data)
    try:
        while True:
            if time.monotonic() >= next_status:
                if group:
                    from ..runtime.groups import status
                    members = status(project, group)['members']
                else:
                    members = [dict(sessions.read(project, session), session=session)]
                next_status = time.monotonic() + 1
            active = False
            for member in members:
                sid = member.get('session')
                if not sid:
                    active = active or member.get('state') in ACTIVE
                    continue
                state = member.get('state', 'unknown')
                active = active or state in ACTIVE
                if states.get(sid) != state:
                    states[sid] = state
                    yield event('state', session=sid, role=member.get('role'), state=state)
                directory = sessions.session_path(project, sid)
                for name in sources:
                    key = (sid, name)
                    if key not in cursors:
                        cursors[key] = LogCursor(directory/(name + '.log'), tail)
                    cursor = cursors[key]
                    text, reset = cursor.read()
                    if reset:
                        yield event('reset', session=sid, source=name)
                    if text:
                        yield event('log', session=sid, role=member.get('role'), source=name, text=text)
            if not active:
                # Drain a final burst in bounded chunks after process exit.
                pending = True
                while pending:
                    pending = False
                    for (sid, name), cursor in cursors.items():
                        text, _ = cursor.read()
                        if text:
                            pending = True
                            yield event('log', session=sid, source=name, text=text)
                yield event('end')
                return
            time.sleep(interval)
    finally:
        for cursor in cursors.values():
            cursor.close()

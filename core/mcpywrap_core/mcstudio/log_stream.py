"""Bounded, incremental local session logs for any CLI consumer."""
import codecs
import os
import time

from . import sessions

CHUNK = 64 * 1024
HISTORY_LIMIT = 256 * 1024
SOURCES = ('game', 'engine', 'worker')
ACTIVE = ('starting', 'running', 'pending')


class LogCursor:
    def __init__(self, path, tail, contains=None):
        self.path, self.tail = path, tail
        self.contains = contains
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.identity = None
        self.position = 0
        self.missing = False

    def read(self):
        """Read at most one bounded chunk; keep decoder state across writes."""
        try:
            # Identify the opened file, not a previous path.stat() result. Close
            # each read so Windows writers can rename/delete their log files.
            with self.path.open('rb') as stream:
                info = os.fstat(stream.fileno())
                identity = (info.st_dev, info.st_ino)
                initial = self.identity is None
                was_missing = self.missing
                reset = not initial and (was_missing or identity != self.identity or info.st_size < self.position)
                if reset:
                    self.position = 0
                    self.decoder.reset()
                self.identity = identity
                self.missing = False
                if initial and self.tail and not was_missing:
                    stream.seek(max(0, info.st_size - HISTORY_LIMIT))
                    truncated = stream.tell() > 0
                    data = stream.read(HISTORY_LIMIT)
                    self.position = stream.tell()
                    lines = data.splitlines(keepends=True)
                    if truncated and lines:
                        lines = lines[1:]
                    if self.contains is not None:
                        incomplete=lines.pop() if lines and not lines[-1].endswith((b'\n',b'\r')) else b''
                        lines=[line for line in lines if self.contains in line.decode('utf-8',errors='replace')][-self.tail:]
                        if incomplete: lines.append(incomplete)
                        return self.decoder.decode(b''.join(lines)), reset
                    return self.decoder.decode(b''.join(lines[-self.tail:])), reset
                if initial:
                    self.position = 0 if was_missing else info.st_size
                stream.seek(self.position)
                data = stream.read(CHUNK)
                self.position = stream.tell()
                return self.decoder.decode(data), reset
        except FileNotFoundError:
            self.missing = True
            return '', False

    def finish(self):
        return self.decoder.decode(b'', final=True)

    def close(self):
        self.decoder.reset()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def follow(project, *, session=None, group=None, source='all', tail=100, interval=.25, contains=None):
    """Yield JSON-serializable events until every selected session has ended.

    Group membership is refreshed from its public service. This function only
    reads logs and session state; disconnecting a consumer never stops a game.
    """
    if bool(session) == bool(group) or source not in (*SOURCES, 'all'):
        raise ValueError('指定有效的 session/group 与日志来源')
    if type(tail) is not int or not 0 <= tail <= 10000:
        raise ValueError('tail 必须在 0..10000 之间')
    sources = SOURCES if source == 'all' else (source,)
    cursors, states, roles = {}, {}, {}
    members, next_status = [], 0
    def event(kind, **data):
        return dict(schema_version=1, event=kind, **data)
    def read_events(sid, name, cursor):
        text, reset = cursor.read()
        if reset:
            yield event('reset', session=sid, source=name)
        if text:
            yield event('log', session=sid, role=roles.get(sid), source=name, text=text)
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
                roles[sid] = member.get('role')
                active = active or state in ACTIVE
                if states.get(sid) != state:
                    states[sid] = state
                    yield event('state', session=sid, role=member.get('role'), state=state)
                directory = sessions.session_path(project, sid)
                for name in sources:
                    key = (sid, name)
                    if key not in cursors:
                        cursors[key] = LogCursor(directory/(name + '.log'), tail, contains)
                    yield from read_events(sid, name, cursors[key])
            if not active:
                # Drain a final burst in bounded chunks after process exit.
                pending = True
                while pending:
                    pending = False
                    for (sid, name), cursor in cursors.items():
                        for item in read_events(sid, name, cursor):
                            pending = True
                            yield item
                for (sid, name), cursor in cursors.items():
                    text = cursor.finish()
                    if text:
                        yield event('log', session=sid, role=roles.get(sid), source=name, text=text)
                yield event('end')
                return
            time.sleep(interval)
    finally:
        for cursor in cursors.values():
            cursor.close()

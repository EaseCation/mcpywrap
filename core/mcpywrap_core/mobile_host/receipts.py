"""Private durable receipts: reconnecting may resend a result, never replay a tool stage."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from . import profiles
from ..remote.protocol import RemoteError


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


class Receipts:
    def __init__(self, profile):
        self.owner = profile['installation_id'] + ':' + profile['client_id']
        self.path = profiles.location().parent / 'host-operations.sqlite3'

    @contextmanager
    def database(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Create privately before SQLite opens the database, including on a permissive umask.
        fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        db = sqlite3.connect(str(self.path), timeout=10)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS operations (owner TEXT, id TEXT, request TEXT, created REAL, PRIMARY KEY(owner,id))')
            db.execute('CREATE TABLE IF NOT EXISTS observations (owner TEXT, id TEXT, snapshot TEXT, observed REAL, PRIMARY KEY(owner,id))')
            db.execute('CREATE TABLE IF NOT EXISTS stages (owner TEXT, operation TEXT, id TEXT, fingerprint TEXT, result TEXT, PRIMARY KEY(owner,operation,id))')
            db.commit()
            yield db
        finally:
            db.close()

    def submitted(self, operation_id, request):
        with self.database() as db, db:
            db.execute('INSERT INTO operations VALUES (?, ?, ?, ?)', (self.owner, operation_id, encoded(request), time.time()))

    def observed(self, operation_id, job):
        snapshot = {key: job[key] for key in ('state', 'error', 'code', 'hint') if key in job}
        observation=job.get('observation') or {}
        if observation:
            snapshot['session_state']=observation.get('state')
            snapshot['session']=observation.get('session')
            snapshot['session_observed_at']=observation.get('observed_at')
        snapshot['ok'] = True if job.get('state') == 'completed' else False if job.get('state') in ('failed','cancelled','interrupted') else None
        with self.database() as db, db:
            db.execute('INSERT OR REPLACE INTO observations VALUES (?, ?, ?, ?)',
                       (self.owner, operation_id, encoded(snapshot), time.time()))

    def recent(self):
        with self.database() as db:
            rows = db.execute('SELECT o.id,o.request,o.created,s.snapshot,s.observed FROM operations o '
                              'LEFT JOIN observations s ON o.owner=s.owner AND o.id=s.id '
                              'WHERE o.owner=? ORDER BY o.created DESC LIMIT 20', (self.owner,)).fetchall()
        return [dict(operation_id=row[0], request_id=json.loads(row[1])['request_id'],
                     operation=json.loads(row[1])['operation'], project=json.loads(row[1])['project'], created=row[2],
                     **(json.loads(row[3]) if row[3] else {'state':'submitted_unobserved','ok':None}),
                     observed_at=row[4], age_ms=max(0,int((time.time()-row[4])*1000)) if row[4] is not None else None, cached=True) for row in rows]

    def execute(self, operation_id, step, execute):
        fingerprint = hashlib.sha256(encoded(step).encode()).hexdigest()
        key = (self.owner, operation_id, step['id'])
        with self.database() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT fingerprint,result FROM stages WHERE owner=? AND operation=? AND id=?', key).fetchone()
            if row:
                db.rollback()
                if row[0] != fingerprint:
                    raise RemoteError('宿主准备阶段内容发生变化，拒绝重放', 'preparation_changed')
                if row[1] is not None:
                    return json.loads(row[1])
                raise RemoteError('此准备阶段可能仍在执行，或结果因中断而未知；不会再次执行', 'preparation_unknown',
                                  hint='先检查原 CLI 和项目脚本输出；确认后取消原任务，再决定是否开始新操作。')
            db.execute('INSERT INTO stages VALUES (?, ?, ?, ?, NULL)', (*key, fingerprint))
            db.commit()  # Must reach disk BEFORE any script, pip or Git side effect.
        result = execute(step)
        with self.database() as db, db:
            db.execute('UPDATE stages SET result=? WHERE owner=? AND operation=? AND id=?', (encoded(result), *key))
        return result

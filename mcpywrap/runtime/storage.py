"""Small atomic records shared by the local lifecycle services."""
from pathlib import Path
import json
import os
import time
import uuid


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def write(path, data):
    write_bytes(path, (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def write_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    try:
        with temporary.open('wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        for attempt in range(10):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if os.name != 'nt' or attempt == 9:
                    raise
                time.sleep(.02)
    finally:
        temporary.unlink(missing_ok=True)


def identifier(value, label='ID'):
    if not isinstance(value, str) or len(value) != 32 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('无效的 ' + label)
    return value

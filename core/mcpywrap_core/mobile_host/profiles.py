"""Private credentials and verified shared-workspace bindings."""
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit


def location():
    configured=os.environ.get('MCPY_HOST_CONFIG')
    if configured is not None:
        if not configured.strip(): raise ValueError('MCPY_HOST_CONFIG 不能为空')
        return Path(configured).expanduser()
    return Path.home()/'.config/mcpywrap/hosts.json'


def endpoint(value):
    url = urlsplit(value)
    if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost') or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
        raise ValueError('本机宿主地址必须是 http://127.0.0.1:<端口>')
    if not url.port:
        raise ValueError('请使用 App 提供的端口')
    return value.rstrip('/')


def read():
    try:
        path = location()
    except RuntimeError:
        # A desktop process may have no user-profile environment at all. It has no
        # default binding to inspect; an explicit configuration must still fail closed.
        if 'MCPY_HOST_CONFIG' in os.environ: raise
        return []
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('format') != 1 or not isinstance(data.get('hosts'), list):
        raise ValueError('宿主连接配置损坏；请重新配对')
    for record in data['hosts']:
        try: record['last_service'] = json.loads(service_cache_path(record).read_text(encoding='utf-8'))
        except (OSError, ValueError): pass
    return data['hosts']


def write_private(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.'+path.name+'-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=True)
            stream.flush(); os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def write(hosts):
    write_private(location(), {'format': 1, 'hosts': [{k:v for k,v in h.items() if k!='last_service'} for h in hosts]})


def bind(record):
    import re
    if not re.fullmatch(r'[A-Za-z0-9-]{1,80}',record.get('installation_id','')): raise ValueError('宿主标识无效')
    token=record.get('token','')
    if not isinstance(token,str) or not token or len(token)>256 or any(ord(c)<33 or ord(c)>126 for c in token): raise ValueError('宿主凭据格式无效')
    record = dict(record, endpoint=endpoint(record['endpoint']), workspace=str(Path(record['workspace']).resolve()))
    from ..utils.locks import directory_lock
    with directory_lock(location().parent/'connections.lock'):
        write([h for h in read() if h['workspace'] != record['workspace']] + [record])


def select(project):
    project = Path(project).resolve()
    candidates = [h for h in read() if project == Path(h['workspace']) or Path(h['workspace']) in project.parents]
    return max(candidates, key=lambda h: len(h['workspace'])) if candidates else None


def project_path(profile, project):
    return Path(project).resolve().relative_to(Path(profile['workspace']).resolve()).as_posix()


def service_cache_path(profile):
    import hashlib
    identity = str(profile.get('installation_id'))+':'+str(profile.get('client_id'))
    return location().parent / ('service-'+hashlib.sha256(identity.encode()).hexdigest()+'.json')


def observe_service(profile, info):
    """观察缓存独立落盘，避免并行只读查询覆盖新增的配对凭据。"""
    import time
    snapshot = {key: info[key] for key in ('core_version','protocol_version','launch_preconditions','background_execution','recovery_uri') if key in info}
    snapshot['observed_at'] = time.time()
    profile['last_service'] = snapshot
    try: write_private(service_cache_path(profile), snapshot)
    except OSError: pass  # 只读查询不因可丢弃缓存写入失败而失败。


def cached_service(profile):
    """Keep the original observation and compute cache age at read time (seconds → ms)."""
    import time
    value=profile.get('last_service')
    if not value: return None
    value=dict(value)
    observed=value.get('observed_at')
    value['age_ms']=max(0,int((time.time()-observed)*1000)) if isinstance(observed,(int,float)) else None
    value['cached']=True
    return value


def unbind(workspace):
    workspace = str(Path(workspace).resolve())
    from ..utils.locks import directory_lock
    with directory_lock(location().parent/'connections.lock'):
        write([h for h in read() if h['workspace'] != workspace])

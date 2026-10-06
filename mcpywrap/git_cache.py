"""用户级不可变源码快照；项目解析与游戏运行不得写入该缓存。"""
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tarfile
import tempfile
import time

from .source_files import _git, _relative, digest, long_path, windows_checkout_digest
from .dependencies import DependencyError


def cache_root():
    explicit = os.environ.get('MCPY_CACHE_DIR')
    if explicit:
        return long_path(Path(explicit).expanduser().resolve())
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local')
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library/Caches'
    else:
        base = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')
    return long_path(base / 'mcpywrap')


@contextmanager
def _source_lock(path, timeout=200):
    """跨进程锁；进程退出由OS释放，不靠删锁文件抢占。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        acquired = False
        start = time.monotonic()
        try:
            while not acquired:
                stream.seek(0)
                try:
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError:
                    if time.monotonic() - start > timeout:
                        raise DependencyError('等待Git源码缓存锁超时，请检查其他同步进程')
                    time.sleep(.1)
            # Windows允许锁住EOF之外的区间；先取得锁再写初始化字节，避免竞态。
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            yield
        finally:
            if acquired:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _verified(container, url, commit):
    try:
        record = json.loads((container / 'source.json').read_text('utf-8'))
        content = container / 'content'
        if record['git'] != url or record['rev'] != commit or (digest(content) != record['sha256'] and
                windows_checkout_digest(content, crlf=False) != record['sha256']):
            raise ValueError('源码摘要不符')
        if not content.is_dir() or content.is_symlink():
            raise ValueError('源码目录缺失或是链接')
        return content
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DependencyError(f'共享Git缓存损坏: {container}；移走该条目后重新 sync') from exc


def fetch_snapshot(url, ref):
    """只由显式add/sync调用；分支在add时解析一次，项目中保存实际提交。"""
    if not isinstance(url, str) or not url.startswith(('https://', 'file://')):
        raise DependencyError('Git来源须为HTTPS或file://')
    if not isinstance(ref, str) or not ref or ref.startswith('-') or any(c.isspace() for c in ref):
        raise DependencyError('无效Git引用')
    origin = hashlib.sha256(url.encode('utf-8')).hexdigest()
    base = cache_root()
    snapshots = base / 'git' / origin
    snapshots.mkdir(parents=True, exist_ok=True)
    with _source_lock(base / 'locks' / (origin + '.lock')):
        if re.fullmatch('[0-9a-f]{40}', ref) and (snapshots / ref).exists():
            return _verified(snapshots / ref, url, ref), ref
        with tempfile.TemporaryDirectory(prefix='fetch-', dir=snapshots) as temporary:
            stage = Path(temporary)
            repo, package = stage / 'repo', stage / 'snapshot'
            content = package / 'content'
            _git('init', '--bare', repo)
            _git('-C', repo, 'fetch', '--depth=1', '--no-tags', url, ref)
            commit = _git('-C', repo, 'rev-parse', 'FETCH_HEAD^{commit}').decode().strip()
            if not re.fullmatch('[0-9a-f]{40}', commit) or (re.fullmatch('[0-9a-f]{40}', ref) and commit != ref):
                raise DependencyError('Git返回的提交不符合声明')
            final = snapshots / commit
            if final.exists():
                return _verified(final, url, commit), commit
            content.mkdir(parents=True)
            seen = set()
            with tarfile.open(fileobj=io.BytesIO(_git('-C', repo, 'archive', '--format=tar', commit))) as archive:
                for member in archive:
                    name = _relative(member.name.rstrip('/'), 'Git归档路径')
                    if any(p in ('.mcpy', '.git') for p in Path(name).parts):
                        raise DependencyError('Git源码不能包含工具缓存或嵌套Git元数据')
                    target = content / name
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        if name.lower() in seen or target.exists():
                            raise DependencyError('Git归档存在大小写冲突或重复文件')
                        seen.add(name.lower())
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.extractfile(member) as stream:
                            target.write_bytes(stream.read())
                    else:
                        raise DependencyError('Git依赖不支持符号链接或特殊文件')
            (package / 'source.json').write_text(json.dumps({'git': url, 'rev': commit, 'sha256': digest(content)}, indent=2), encoding='utf-8')
            os.replace(package, final)
            return final / 'content', commit

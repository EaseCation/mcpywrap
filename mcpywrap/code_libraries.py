"""固定 Git 提交的游戏代码库；获取只发生在显式 sync 中。"""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile

from .dependencies import DependencyError, read_project, validate_game_files

LOCK_FILE = 'mcpy-code-libraries.lock.json'


def _relative(value, label):
    if not isinstance(value, str) or not value or '\\' in value:
        raise DependencyError(f'{label} 必须为非空 POSIX 相对路径')
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ('', '.', '..') or ':' in p or p.endswith((' ', '.')) or
                                re.search(r'[\x00-\x1f<>"|?*]', p) or
                                re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?', p, re.I)
                                for p in value.split('/')):
        raise DependencyError(f'{label} 不得越界: {value}')
    return path.as_posix()


def declarations(root):
    config = read_project(root)
    settings = config.get('tool', {}).get('mcpywrap', {})
    entries = settings.get('code_libraries', [])
    if not isinstance(entries, list):
        raise DependencyError('code_libraries 必须是表数组')
    if entries and settings.get('project_type', 'addon') != 'addon':
        raise DependencyError('code_libraries 应声明在 Addon 中；地图可依赖该 Addon')
    result, names = [], set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'name', 'git', 'rev', 'subdir', 'target'}:
            raise DependencyError('代码库需要且仅接受 name/git/rev/subdir/target')
        name, url, rev = entry['name'], entry['git'], entry['rev']
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name) or name.lower() in names:
            raise DependencyError('代码库 name 无效或重复')
        names.add(name.lower())
        if not isinstance(url, str) or not url.startswith(('https://', 'file://')):
            raise DependencyError('代码库 git 仅支持 HTTPS 或 file:// 本地仓库')
        if not isinstance(rev, str) or not re.fullmatch('[0-9a-f]{40}', rev):
            raise DependencyError('代码库 rev 必须是完整的40位小写提交 SHA')
        record = dict(entry)
        for field in ('subdir', 'target'):
            record[field] = _relative(record[field], field)
        result.append(record)
    targets = [r['target'].lower() for r in result]
    for i, a in enumerate(targets):
        if any(a == b or a.startswith(b + '/') or b.startswith(a + '/') for b in targets[i + 1:]):
            raise DependencyError('代码库安装目标重叠')
    return result


def identity(entry):
    return hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()


def digest(directory):
    h = hashlib.sha256()
    for path in sorted(Path(directory).rglob('*')):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise DependencyError(f'代码库不允许链接: {path}')
        if path.is_file():
            rel = path.relative_to(directory).as_posix().encode('utf-8')
            data = path.read_bytes()
            h.update(len(rel).to_bytes(8, 'big') + rel + len(data).to_bytes(8, 'big') + data)
    return h.hexdigest()


def _git(*args):
    try:
        result = subprocess.run(['git', '-c', 'core.hooksPath=', *map(str, args)],
                                capture_output=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DependencyError(f'无法获取代码库: {exc}') from exc
    if result.returncode:
        raise DependencyError(result.stderr.decode('utf-8', errors='replace').strip())
    return result.stdout


def sync_libraries(root):
    root = Path(root)
    entries = declarations(root)
    cache = root / '.mcpy' / 'libraries'
    cache.mkdir(parents=True, exist_ok=True)
    lock = {'version': 1, 'libraries': []}
    old_lock = root / LOCK_FILE
    expected = {}
    if old_lock.exists():
        try:
            expected = {identity(r['declaration']): r['sha256'] for r in json.loads(old_lock.read_text('utf-8'))['libraries']}
        except (ValueError, KeyError, TypeError) as exc:
            raise DependencyError(f'代码库锁文件损坏: {old_lock}') from exc
    for entry in entries:
        key = identity(entry)
        installed = cache / key
        if installed.is_dir() and key in expected and digest(installed) == expected[key]:
            lock['libraries'].append({'declaration': entry, 'sha256': expected[key]})
            continue
        # 临时仓库不检出文件、不运行依赖代码、hooks 或安装脚本。
        with tempfile.TemporaryDirectory(prefix='fetch-', dir=cache) as temporary:
            temp = Path(temporary)
            repo, content = temp / 'repo', temp / 'content'
            _git('init', '--bare', repo)
            _git('-C', repo, 'fetch', '--depth=1', '--no-tags', entry['git'], entry['rev'])
            actual = _git('-C', repo, 'rev-parse', 'FETCH_HEAD^{commit}').decode().strip()
            if actual != entry['rev']:
                raise DependencyError('Git 返回的提交与声明不符')
            archive = _git('-C', repo, 'archive', '--format=tar', actual, entry['subdir'])
            content.mkdir()
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                for member in tar:
                    member_path = PurePosixPath(_relative(member.name.rstrip('/'), 'archive'))
                    if not member_path.is_relative_to(PurePosixPath(entry['subdir'])):
                        continue
                    relative = member_path.relative_to(entry['subdir'])
                    if not relative.parts:
                        continue
                    target = content.joinpath(*relative.parts)
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with tar.extractfile(member) as stream:
                            target.write_bytes(stream.read())
                    else:
                        raise DependencyError('代码库包含链接或特殊文件，拒绝安装')
            if not any(content.rglob('*.py')):
                raise DependencyError('代码库子目录没有 Python 源码')
            tree = _git('-C', repo, 'ls-tree', '--name-only', actual).decode().splitlines()
            licenses = [n for n in tree if re.fullmatch(r'(LICENSE|COPYING|NOTICE)(\.[\w-]+)?', n, re.I)]
            for name in licenses:
                (content / ('MCPY_UPSTREAM_' + name)).write_bytes(_git('-C', repo, 'show', actual + ':' + name))
            validate_game_files(root, [content])
            value = digest(content)
            if key in expected and expected[key] != value:
                raise DependencyError('固定提交的代码库内容与锁文件摘要不符')
            if installed.exists():
                # 回退到旧提交：用重新获取的内容验证旧缓存，而不是逐文件覆盖。
                if digest(installed) != value:
                    raise DependencyError(f'代码库缓存已损坏，请移走后重新 sync: {installed}')
            else:
                os.replace(content, installed)
            lock['libraries'].append({'declaration': entry, 'sha256': value})
    fd, filename = tempfile.mkstemp(prefix='.code-lock-', dir=root)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(lock, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(filename, old_lock)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)
    return len(entries)


def resolve_libraries(root):
    entries = declarations(root)
    if not entries:
        return []
    try:
        lock = json.loads((Path(root) / LOCK_FILE).read_text('utf-8'))
        if lock.get('version') != 1:
            raise ValueError('不支持的锁文件版本')
        records = lock['libraries']
        if [r['declaration'] for r in records] != entries:
            raise ValueError('声明已经改变')
        result = []
        for entry, record in zip(entries, records):
            path = Path(root) / '.mcpy' / 'libraries' / identity(entry)
            if not path.is_dir() or digest(path) != record['sha256']:
                raise ValueError(f"{entry['name']} 缓存缺失或内容已改变")
            validate_game_files(root, [path])
            result.append(dict(entry, source=path))
        return result
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DependencyError(f'{root}: 代码库不可用: {exc}；请显式运行 mcpy sync') from exc


def prepare_libraries(packs):
    mounts = []
    for pack in packs:
        pack.code_libraries = resolve_libraries(pack.path)
        if pack.code_libraries and (not pack.behavior_pack_dir or not Path(pack.behavior_pack_dir).is_dir()):
            raise DependencyError(f'声明代码库的 Addon 需要行为包及 manifest: {pack.path}')
        mounts.extend(pack.code_libraries)
    targets = []
    for lib in mounts:
        target = lib['target'].lower()
        if any(target == other or target.startswith(other + '/') or other.startswith(target + '/') for other in targets):
            raise DependencyError('不同 Addon 的代码库安装目标重叠')
        targets.append(target)
        for pack in packs:
            folder = pack.behavior_pack_dir
            if folder:
                destination = Path(folder) / lib['target']
                if (destination.exists() or destination.with_suffix('.py').exists() or
                        any(p.is_file() for p in destination.parents if p != Path(folder).parent and p.is_relative_to(folder))):
                    raise DependencyError(f'代码库目标与手写内容冲突: {destination}')
    return bool(mounts)


def library_source(pack, kind, relative):
    if kind == 'behavior':
        for library in getattr(pack, 'code_libraries', []):
            prefix = library['target'] + '/'
            if relative.startswith(prefix):
                return library['source'] / relative[len(prefix):]
    return None

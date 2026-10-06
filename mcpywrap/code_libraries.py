"""固定 Git 提交的游戏代码库；获取只发生在显式 sync 中。"""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from .dependencies import DependencyError, read_project, validate_game_files
from .source_files import _relative, digest, long_path, windows_checkout_digest

LOCK_FILE = 'mcpy-code-libraries.lock.json'


def declarations(root, config=None):
    config = read_project(root) if config is None else config
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


def prepare_sync(root, config=None):
    """获取并验证候选配置，返回锁数据；尚不修改配置或锁文件。"""
    root = Path(root)
    entries = declarations(root, config)
    cache = long_path(root / '.mcpy' / 'libraries')
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
        if installed.is_dir() and key in expected and expected[key] in (digest(installed), windows_checkout_digest(installed, crlf=False)):
            lock['libraries'].append({'declaration': entry, 'sha256': digest(installed)})
            continue
        # 临时仓库不检出文件、不运行依赖代码、hooks 或安装脚本。
        with tempfile.TemporaryDirectory(prefix='fetch-', dir=cache) as temporary:
            temp = Path(temporary)
            from .git_cache import fetch_snapshot
            import shutil
            source, actual = fetch_snapshot(entry['git'], entry['rev'])
            payload = source / entry['subdir']
            if not payload.is_dir() or not any(payload.rglob('*.py')):
                raise DependencyError('代码库子目录没有 Python 源码')
            content = temp / 'content'
            shutil.copytree(payload, content)
            for file in source.iterdir():
                if file.is_file() and re.fullmatch(r'(LICENSE|COPYING|NOTICE)(\.[\w-]+)?', file.name, re.I):
                    (content / ('MCPY_UPSTREAM_' + file.name)).write_bytes(file.read_bytes())
            validate_game_files(root, [content])
            value = digest(content)
            if key in expected and expected[key] not in (value, windows_checkout_digest(content, crlf=False)):
                raise DependencyError('固定提交的代码库内容与锁文件摘要不符')
            if installed.exists():
                # 回退到旧提交：用重新获取的内容验证旧缓存，而不是逐文件覆盖。
                if digest(installed) != value:
                    raise DependencyError(f'代码库缓存已损坏，请移走后重新 sync: {installed}')
            else:
                os.replace(content, installed)
            lock['libraries'].append({'declaration': entry, 'sha256': value})
    return lock


def write_lock(root, lock):
    root = Path(root)
    fd, filename = tempfile.mkstemp(prefix='.code-lock-', dir=root)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            json.dump(lock, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(filename, root / LOCK_FILE)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def sync_libraries(root):
    lock = prepare_sync(root)
    write_lock(root, lock)
    return len(lock['libraries'])


def resolve_libraries(root, config=None, lock=None):
    entries = declarations(root, config)
    if not entries:
        return []
    try:
        lock = json.loads((Path(root) / LOCK_FILE).read_text('utf-8')) if lock is None else lock
        if lock.get('version') != 1:
            raise ValueError('不支持的锁文件版本')
        records = lock['libraries']
        if [r['declaration'] for r in records] != entries:
            raise ValueError('声明已经改变')
        result = []
        for entry, record in zip(entries, records):
            path = long_path(Path(root) / '.mcpy' / 'libraries' / identity(entry))
            if not path.is_dir() or record['sha256'] not in (digest(path), windows_checkout_digest(path, crlf=False)):
                raise ValueError(f"{entry['name']} 缓存缺失或内容已改变")
            validate_game_files(root, [path])
            result.append(dict(entry, source=path))
        return result
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise DependencyError(f'{root}: 代码库不可用: {exc}；请显式运行 mcpy sync') from exc


def prepare_libraries(packs, overrides=None):
    mounts = []
    for pack in packs:
        config, lock = (overrides or {}).get(str(Path(pack.path).resolve()), (None, None))
        pack.code_libraries = resolve_libraries(pack.path, config, lock)
        if pack.code_libraries and (not pack.behavior_pack_dir or not Path(pack.behavior_pack_dir).is_dir()):
            raise DependencyError(f'声明代码库的 Addon 需要行为包及 manifest: {pack.path}')
        mounts.extend(dict(item, owner=pack) for item in pack.code_libraries)
        if getattr(pack, 'code_target', None):
            mounts.append({'target': pack.code_target, 'owner': pack, 'registered': True})
    targets = []
    for lib in mounts:
        target = lib['target'].lower()
        if any(target == other or target.startswith(other + '/') or other.startswith(target + '/') for other in targets):
            raise DependencyError('不同 Addon 的代码库安装目标重叠')
        targets.append(target)
        for pack in packs:
            if lib.get('registered') and pack is lib['owner']:
                continue
            folder = pack.behavior_pack_dir
            if folder:
                destination = Path(folder) / lib['target']
                if (destination.exists() or destination.with_suffix('.py').exists() or
                        any(p.is_file() for p in destination.parents if p != Path(folder).parent and p.is_relative_to(folder))):
                    raise DependencyError(f'代码库目标与手写内容冲突: {destination}')
    return bool(mounts)


def remove_library(root, name):
    """兼容已有叶子代码库声明；保留源缓存和入口。"""
    from .dependencies import write_project
    root = Path(root)
    config = read_project(root)
    entries = declarations(root, config)
    if not any(entry['name'] == name for entry in entries):
        raise DependencyError('未声明此代码库: ' + name)
    config['tool']['mcpywrap']['code_libraries'] = [e for e in entries if e['name'] != name]
    lock_path = root / LOCK_FILE
    before = lock_path.read_bytes() if lock_path.exists() else None
    try:
        if before is not None:
            lock = json.loads(before)
            lock['libraries'] = [r for r in lock['libraries'] if r['declaration']['name'] != name]
            write_lock(root, lock)
        write_project(root, config)
    except Exception:
        if before is not None:
            lock_path.write_bytes(before)
        raise


def library_source(pack, kind, relative):
    if kind == 'behavior':
        for library in getattr(pack, 'code_libraries', []):
            prefix = library['target'] + '/'
            if relative.startswith(prefix):
                return library['source'] / relative[len(prefix):]
    return None

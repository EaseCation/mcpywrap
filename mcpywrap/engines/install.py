"""Verified, local assembly of a game-free runtime and an official developer APK."""
import hashlib
import errno
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.parse import urljoin, urlsplit, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from http.client import HTTPException
import uuid
import zipfile

from .host import EngineError, describe, require_macos

CATALOG_ENV = 'MCPY_RUNTIME_CATALOG'
DEFAULT_CATALOG = ('https://github.com/EaseCation/mcpelauncher-manifest/releases/download/'
                   'mcpy-runtime-v0.4.0/catalog.json')
# Public constant from the official ApkDownload component, verified 2026-10-05.
# https://mcdev.webapp.163.com/static/js/4.05713153ba17aea6db53.js
CDN_CONSTANT = 'mEE7Cot48r9j2AvEL2N6jpXEc'


def home():
    return Path(os.environ.get('MCPY_ENGINE_HOME', '~/Library/Application Support/mcpy')).expanduser().resolve()


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def read_json(path):
    with Path(path).open(encoding='utf-8') as stream:
        return json.load(stream)


def write_json(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            stream.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
            stream.flush(); os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def selected():
    path = home()/'current.json'
    return read_json(path) if path.is_file() else None


def _hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)


def _version(value):
    return tuple((list(map(int, value.split('.'))) + [0, 0, 0])[:3])


def _scheme(value):
    # Windows 盘符路径不是 URL scheme；本地目录和下载文件共用判断。
    return '' if os.path.isabs(str(value)) else urlsplit(str(value)).scheme


def catalog(location=None):
    location = location or os.environ.get(CATALOG_ENV)
    if not location:
        pending = home()/'install-plan.json'
        current = read_json(pending) if pending.is_file() else selected()
        if current:
            validate_catalog(current['catalog'])
            return current['catalog'], current['catalog_base']
        location = DEFAULT_CATALOG
    scheme = _scheme(location)
    if scheme == 'https':
        try:
            with urlopen(str(location), timeout=20) as response:
                raw = response.read(1024 * 1024 + 1)
        except (OSError, URLError, HTTPException) as error:
            raise EngineError('获取运行包发布目录失败：' + str(error), 'catalog_download_failed',
                              '请检查网络后重试；默认发布源已内置，无需手动填写。') from None
        if len(raw) > 1024 * 1024:
            raise EngineError('发布目录过大', 'invalid_catalog')
        data, base = json.loads(raw), str(location)
    elif not scheme:
        path = Path(location).expanduser().resolve()
        data, base = read_json(path), str(path)
    else:
        raise EngineError('发布目录须为本地文件或 HTTPS 地址', 'invalid_catalog')
    validate_catalog(data)
    return data, base


def validate_catalog(data):
    try:
        runtime, profile = data['runtime'], data['profile']
        if data.get('apk_source') not in (None, 'netease-pe'): raise ValueError('不支持的 APK 发现来源')
        if data['schema'] != 1 or runtime['platform'] != 'darwin-arm64':
            raise ValueError('平台或 schema 不兼容')
        if not re.fullmatch('[A-Za-z0-9_.-]{1,100}', runtime['id']) or runtime['id'] in ('.', '..'):
            raise ValueError('运行包 ID 无效')
        if runtime['archive_root'] != 'McpyRuntime.app' or not _hash(runtime['sha256']):
            raise ValueError('运行包清单无效')
        if profile['package_name'] != 'com.netease.mctest' or not _hash(profile['apk']['sha256']):
            raise ValueError('开发者 APK 身份无效')
        if not re.fullmatch(r'dev_launcher_[0-9.]+\.apk', profile['apk']['filename']):
            raise ValueError('APK 文件名无效')
        if not profile['files'] or any(not _hash(h) for h in profile['files'].values()):
            raise ValueError('缺少引擎文件摘要')
        for name in profile['files']:
            safe_member(name)
        for size in (runtime['size'], profile['apk']['size'], profile['unpacked_size']):
            if type(size) is not int or size <= 0:
                raise ValueError('文件大小无效')
        if type(profile['file_count']) is not int or profile['file_count'] <= 0:
            raise ValueError('资源文件数无效')
        if not isinstance(runtime['url'], str) or not runtime['url']:
            raise ValueError('缺少运行包下载地址')
        if not re.fullmatch(r'[0-9]+(?:\.[0-9]+){0,2}', runtime['minimum_macos']):
            raise ValueError('最低系统版本无效')
        _version(runtime['minimum_macos'])
    except (KeyError, TypeError, ValueError) as error:
        raise EngineError('无效的发布目录：' + str(error), 'invalid_catalog') from None


def locate(base, value):
    if _scheme(value):
        if _scheme(value) != 'https':
            raise EngineError('下载地址须使用 HTTPS', 'invalid_catalog')
        return value
    return urljoin(base, value) if _scheme(base) else str((Path(base).parent/value).resolve())


def safe_member(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        raise EngineError('归档含不安全路径：' + name, 'unsafe_archive')
    return path


def _check_download_storage(error):
    if isinstance(error, OSError) and error.errno in (errno.ENOSPC, errno.EDQUOT, errno.EACCES, errno.EROFS):
        raise EngineError('无法保存下载文件：' + str(error), 'download_storage_failed',
                          '请检查可用空间和目录权限后重试；已安装版本和世界不受影响。') from None


def fetch(source, target, expected, size, progress=None):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size == size and digest(target) == expected:
        return target
    if not _scheme(source):
        path = Path(source)
        if path.stat().st_size != size or digest(path) != expected:
            raise EngineError('本地发行文件摘要不匹配', 'integrity_error')
        return path
    if urlsplit(source).hostname == 'g79.gdl.netease.com' and size >= 128*1024*1024:
        return _fetch_ranges(source, target, expected, size, progress)
    part = target.with_suffix(target.suffix + '.part')
    for attempt in range(3):
        offset = part.stat().st_size if part.exists() else 0
        if offset >= size:
            if offset == size and digest(part) == expected:
                part.replace(target); return target
            part.unlink(); offset = 0
        if progress: progress(offset, size)
        headers = {'Range': 'bytes=%d-' % offset, 'User-Agent': 'mcpywrap'}
        try:
            with urlopen(Request(source, headers=headers), timeout=30) as response:
                if response.status == 206:
                    content_range = response.headers.get('Content-Range', '')
                    if not content_range.startswith('bytes %d-' % offset) or not content_range.endswith('/%d' % size):
                        raise EngineError('续传响应与预期文件不一致', 'download_changed')
                elif response.status == 200:
                    offset = 0
                else:
                    raise EngineError('下载响应异常', 'download_failed')
                with part.open('ab' if offset else 'wb') as stream:
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        offset += len(block)
                        if offset > size:
                            raise EngineError('下载文件超过清单大小', 'integrity_error')
                        stream.write(block)
                        if progress: progress(offset, size)
            if offset != size:
                raise OSError('下载连接提前结束')
            break
        except HTTPError as error:
            if error.code not in (408, 429, 500, 502, 503, 504):
                raise EngineError('下载服务器返回 HTTP %d。' % error.code, 'download_failed',
                                  '请稍后重试；若资源已下架，请反馈所选版本，或通过 --apk 导入匹配资源。') from None
            last_error = error
        except (OSError, URLError, HTTPException) as error:
            _check_download_storage(error)
            last_error = error
        if attempt == 2:
            raise EngineError('网络下载失败：' + str(last_error), 'download_failed',
                              '已保留下载进度；检查网络后重新运行即可续传，无需填写发布源。') from None
        time.sleep(attempt + 1)
    if digest(part) != expected:
        raise EngineError('下载文件 SHA-256 不匹配；未安装该文件。', 'integrity_error',
                          '请检查发布来源或导入匹配 APK；已有世界不受影响。')
    part.replace(target)
    return target



def _fetch_ranges(source, target, expected, size, progress=None, *, chunk_size=16*1024*1024, workers=8, source_identity=None):
    """Resume verified-size CDN ranges, adapted from the validated APK downloader."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    part = target.with_suffix(target.suffix + '.part')
    ledger = target.with_suffix(target.suffix + '.ranges.json')
    count = (size + chunk_size - 1) // chunk_size
    identity = {'sha256': expected, 'size': size, 'chunk_size': chunk_size}
    if source_identity: identity['source'] = source_identity
    done = set()
    if ledger.is_file():
        try:
            state = read_json(ledger)
            valid = (isinstance(state, dict) and all(state.get(k) == v for k, v in identity.items())
                     and isinstance(state.get('done'), list)
                     and all(type(i) is int and 0 <= i < count for i in state['done']))
        except (ValueError, TypeError):
            valid = False
        if not valid:
            part.unlink(missing_ok=True); ledger.unlink()
        else:
            done = set(state.get('done', []))
            length = part.stat().st_size if part.is_file() else 0
            done = {i for i in done if min(size, (i+1)*chunk_size) <= length}
    elif part.is_file() and expected is not None:
        length = part.stat().st_size
        if length == size and digest(part) == expected:
            part.replace(target); return target
        # Reuse complete chunks of a previous sequential download.
        if length < size: done = set(range(length // chunk_size))
    write_json(ledger, dict(identity, done=sorted(done)))
    with part.open('a+b') as stream: stream.truncate(size)
    amounts = {i: min(chunk_size, size-i*chunk_size) if i in done else 0 for i in range(count)}
    cancelled, lock = threading.Event(), threading.Lock()
    last_update = [0.0]
    if progress: progress(sum(amounts.values()), size)

    def update(index, amount):
        with lock:
            amounts[index] = amount
            now = time.monotonic()
            if progress and now-last_update[0] >= .1:
                progress(sum(amounts.values()), size); last_update[0] = now

    def transfer(index):
        start, end = index*chunk_size, min(size, (index+1)*chunk_size)-1
        for attempt in range(3):
            if cancelled.is_set(): return None
            update(index, 0)
            try:
                headers = {'Range': 'bytes=%d-%d' % (start, end), 'User-Agent': 'mcpywrap'}
                if source_identity: headers['If-Range'] = source_identity['validator']
                request = Request(source, headers=headers)
                with urlopen(request, timeout=30) as response:
                    if response.status != 206 or response.headers.get('Content-Range') != 'bytes %d-%d/%d' % (start, end, size):
                        raise EngineError('网易 CDN 分段响应与清单不匹配', 'download_changed')
                    at = start
                    with part.open('r+b') as stream:
                        stream.seek(start)
                        read = getattr(response, 'read1', response.read)
                        while not cancelled.is_set():
                            block = read(256*1024)
                            if not block: break
                            if at+len(block) > end+1:
                                raise EngineError('下载分段超过预期大小', 'integrity_error')
                            stream.write(block); at += len(block); update(index, at-start)
                        stream.flush(); os.fsync(stream.fileno())
                    if cancelled.is_set(): return None
                    if at != end+1: raise OSError('下载分段提前结束')
                return index
            except HTTPError as error:
                if error.code not in (408, 429, 500, 502, 503, 504):
                    raise EngineError('网易下载服务器返回 HTTP %d' % error.code, 'download_failed') from None
                last_error = error
            except (OSError, URLError, HTTPException) as error:
                _check_download_storage(error)
                last_error = error
            if attempt == 2:
                raise EngineError('网易 APK 下载中断：' + str(last_error), 'download_failed',
                                  '已保留完成的分段，重新运行即可续传。') from None
            cancelled.wait(attempt + 1)

    pool = ThreadPoolExecutor(max_workers=workers)
    futures = []
    try:
        futures = [pool.submit(transfer, i) for i in range(count) if i not in done]
        for future in as_completed(futures):
            index = future.result()
            if index is not None:
                done.add(index)
                write_json(ledger, dict(identity, done=sorted(done)))
    except BaseException:
        cancelled.set()
        for future in futures: future.cancel()
        raise
    finally:
        pool.shutdown(wait=True)
    if expected is not None and digest(part) != expected:
        part.unlink(missing_ok=True); ledger.unlink(missing_ok=True)
        raise EngineError('下载文件 SHA-256 不匹配；未安装该文件。', 'integrity_error')
    part.replace(target); ledger.unlink(missing_ok=True)
    if progress: progress(size, size)
    return target


def official_apk_url(profile):
    from .official import discover, signed_url
    for channel in ('pe', 'pe_old'):
        item = discover(channel)
        if item['version'] == profile['apk']['version']:
            return signed_url(item['url'])
    raise EngineError('此旧版本已不在网易下载频道中。', 'version_unavailable',
                      '可继续使用本地已有版本；新安装请使用当前官方版本。')


def verify_runtime(app, integrity, profile=None):
    app = Path(app)
    files = read_json(integrity)['files']
    if not files:
        raise EngineError('运行包缺少文件清单', 'integrity_error')
    actual = {p.relative_to(app).as_posix() for p in app.rglob('*') if p.is_file()}
    if actual != set(files):
        raise EngineError('运行包文件清单不匹配', 'integrity_error')
    for name, expected in files.items():
        safe_member(name)
        path = app/name
        if path.is_symlink() or not _hash(expected) or digest(path) != expected:
            raise EngineError('运行包文件损坏：' + name, 'integrity_error')
    meta = read_json(app/'Contents/Resources/runtime.json')
    if meta.get('platform') != 'darwin-arm64' or meta.get('launch_protocol') != 1 or meta.get('client_python_protocol') != 1:
        raise EngineError('运行包不支持当前启动协议', 'runtime_incompatible')
    contract = meta.get('game_compatibility') or {}
    if profile is not None and meta.get('game_profile') != profile:
        if (contract.get('elf_rules_schema') != 1 or contract.get('package_name') != profile.get('package_name')
                or contract.get('abi') != 'arm64-v8a'):
            raise EngineError('运行包与 APK 兼容配置不匹配', 'runtime_incompatible')
    exe = app/'Contents/MacOS/mcpelauncher-client'
    with exe.open('rb') as stream:
        if struct.unpack('<II', stream.read(8)) != (0xfeedfacf, 0x100000c):
            raise EngineError('启动器不是原生 arm64 Mach-O', 'runtime_incompatible')
    if os.name != 'nt' and not os.access(exe, os.X_OK):
        raise EngineError('启动器没有执行权限', 'integrity_error')
    return meta


def preflight_runtime(app, game, profile, metadata, runtime_id):
    """结构匹配在安装选择/启动之前完成；不运行游戏，也不改写旧版本。"""
    contract = metadata.get('game_compatibility') or {}
    if contract.get('elf_rules_schema') != 1:
        return None
    rules_hash = contract.get('rules_sha256')
    if not _hash(rules_hash):
        raise EngineError('运行包缺少自动兼容规则摘要', 'runtime_incompatible')
    game, app = Path(game), Path(app)
    expected = profile['files'].get('lib/arm64-v8a/libminecraftpe.so')
    if not _hash(expected):
        raise EngineError('APK 缺少原生核心库摘要', 'runtime_incompatible')
    report = game.parent/'compatibility'/(rules_hash+'.json')
    if report.is_file():
        cached = read_json(report)
        if cached.get('schema') == 1 and cached.get('elf_sha256') == expected and cached.get('rules_sha256') == rules_hash:
            return str(report)
    script = app/'Contents/Resources/launcher/analyze_developer_binary.py'
    try:
        process = subprocess.run([sys.executable, '-B', str(script), str(game/'lib/arm64-v8a/libminecraftpe.so'),
                                  '--output', str(report)], capture_output=True, text=True, encoding='utf-8', timeout=120)
        result = json.loads(process.stdout)
        if not isinstance(result, dict):
            raise ValueError('Invalid compatibility response')
        returncode = process.returncode
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        result = {'error': '自动兼容检查未完成：' + type(error).__name__}
        returncode = 1
    if returncode or not result.get('ok'):
        diagnostic = {'schema': 1, 'stage': 'native_compatibility', 'runtime': runtime_id,
                      'engine_version': profile['apk']['version'], 'elf_sha256': expected,
                      'rules_sha256': rules_hash, 'error': result.get('error', '结构检查失败')}
        report.parent.mkdir(parents=True, exist_ok=True)
        failure = report.with_name(rules_hash+'-failure.json')
        write_json(failure, diagnostic)
        raise EngineError('此开发包暂未通过启动器兼容性检查，已保留现有可用版本。',
                          'unsupported_engine_structure', '请反馈诊断文件：'+str(failure), diagnostic_path=str(failure))
    cached = read_json(report)
    if cached.get('elf_sha256') != expected or cached.get('rules_sha256') != rules_hash:
        raise EngineError('兼容检查结果与输入文件不一致', 'integrity_error')
    return str(report)


def extract_runtime(archive, stage):
    seen, total = set(), 0
    with tarfile.open(archive, 'r:*') as stream:
        for item in stream:
            name = safe_member(item.name)
            key = str(name).casefold()
            if key in seen or not (item.isfile() or item.isdir()):
                raise EngineError('运行包含重复路径或特殊文件', 'unsafe_archive')
            seen.add(key); total += item.size
            if total > 512 * 1024 * 1024 or len(seen) > 10000:
                raise EngineError('运行包解压规模异常', 'unsafe_archive')
            target = stage.joinpath(*name.parts)
            if item.isdir(): target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with stream.extractfile(item) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)
                target.chmod(item.mode & 0o755)


def verify_game(game, profile, installed=True):
    if installed and read_json(Path(game)/'installed.json') != {'profile': profile, 'apk_sha256': profile['apk']['sha256']}:
        raise EngineError('资源安装记录不匹配', 'game_incomplete', '重新执行 mcpy engine install 修复。')
    files = [p for p in Path(game).rglob('*') if p.is_file() and p.name != 'installed.json']
    if (len(files) != profile['file_count'] or sum(p.stat().st_size for p in files) != profile['unpacked_size']
            or any(p.is_symlink() for p in files)):
        raise EngineError('游戏资源不完整', 'game_incomplete', '重新执行 mcpy engine install 修复。')
    for name, expected in profile['files'].items():
        path = Path(game)/name
        if not path.is_file() or path.is_symlink() or digest(path) != expected:
            raise EngineError('游戏资源缺失或损坏：' + name, 'game_incomplete', '重新执行 mcpy engine install。')


def extract_apk(apk, stage, profile, progress=None):
    seen, members, total = set(), [], 0
    with zipfile.ZipFile(apk) as archive:
        for entry in archive.infolist():
            if entry.filename != 'AndroidManifest.xml' and not entry.filename.startswith(('assets/', 'lib/arm64-v8a/')):
                continue
            path = safe_member(entry.filename)
            key = str(path).casefold()
            if key in seen or stat.S_ISLNK(entry.external_attr >> 16):
                raise EngineError('APK 含重复路径或链接', 'unsafe_archive')
            seen.add(key); total += entry.file_size; members.append((entry, path))
        if total != profile['unpacked_size']:
            raise EngineError('APK 展开大小与兼容配置不一致', 'integrity_error')
        done = 0
        for entry, path in members:
            target = stage.joinpath(*path.parts)
            if entry.is_dir(): target.mkdir(parents=True, exist_ok=True); continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
            done += entry.file_size
            if progress: progress(done, total)
    verify_game(stage, profile, installed=False)


def diagnose(check_files=False):
    host = describe()
    data = {'ok': False, 'host': host, 'backend': host['backend'], 'state': 'unsupported_platform',
            'home': str(home()), 'runtime': None, 'game': None}
    if host['backend'] != 'macos-arm64':
        data['hint'] = 'Windows 使用 MC Studio；其他平台可配置 Windows 远程服务。'
        return data
    try:
        current = selected()
    except (OSError, ValueError) as error:
        data.update(state='installation_invalid', error=str(error), hint='运行 mcpy engine install --catalog <发布目录> 修复。')
        return data
    if not current:
        data.update(state='setup_required', hint='运行 mcpy engine install，或在终端执行 mcpy run 获取引导。')
        return data
    try:
        cat = current['catalog']; validate_catalog(cat)
        runtime = cat['runtime']; profile = cat['profile']
        app = home()/'runtimes'/runtime['id']/'McpyRuntime.app'
        game = home()/'engines'/profile['apk']['sha256']/'game'
        data.update(runtime=str(app), game=str(game), runtime_id=runtime['id'], engine_version=profile['apk']['version'],
                    profile=profile, minimum_macos=runtime['minimum_macos'])
        if _version(host['macos_version']) < _version(runtime['minimum_macos']):
            raise EngineError('macOS 版本低于运行包要求', 'os_too_old')
        if not (app/'Contents/Resources/runtime.json').is_file():
            raise EngineError('尚未安装所选运行包', 'runtime_missing')
        metadata = read_json(app/'Contents/Resources/runtime.json')
        data['cppconfig_protocol'] = metadata.get('cppconfig_protocol', 0)
        if not (game/'installed.json').is_file():
            raise EngineError('尚未安装所选 APK 资源', 'game_missing')
        if check_files:
            verify_runtime(app, app.parent/'McpyRuntime.integrity.json', profile)
            verify_game(game, profile)
        data.update(ok=True, state='ready', hint=None)
    except (OSError, ValueError, KeyError) as error:
        data.update(state=getattr(error, 'code', 'installation_invalid'), error=str(error),
                    hint='运行 mcpy engine install 修复；世界不会被删除。')
    return data


def _valid(check, *args):
    try:
        check(*args)
        return True
    except (OSError, ValueError, KeyError):
        return False


def _replace(stage, destination):
    backup = destination.with_name('.replaced-' + uuid.uuid4().hex)
    if destination.exists(): destination.rename(backup)
    try:
        stage.rename(destination)
    except BaseException:
        if backup.exists(): backup.rename(destination)
        raise
    if backup.exists():
        # A successful verified replacement must not become a failed install
        # merely because the old, unused files could not be removed.
        try:
            shutil.rmtree(backup)
        except OSError:
            from ..command_context import report_warning
            report_warning('安装已完成，旧资源暂未清理：' + str(backup))


def _require_idle(destination):
    import psutil
    for process in psutil.process_iter(['exe', 'cmdline']):
        try:
            if ((process.info['exe'] or '').startswith(str(destination) + os.sep)
                    or any(str(destination) in arg for arg in process.info['cmdline'] or [])):
                raise EngineError('资源正在使用，无法修复。', 'busy', '先 stop 对应游戏会话，再重试安装。')
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def _remaining_download(target, expected, size):
    """Count additional space, without treating a sparse range file as downloaded."""
    if target.is_file() and target.stat().st_size == size and digest(target) == expected:
        return 0
    part = target.with_suffix(target.suffix + '.part')
    ledger = target.with_suffix(target.suffix + '.ranges.json')
    if not part.is_file():
        return size
    if ledger.is_file():
        try:
            state = read_json(ledger)
        except (ValueError, TypeError):
            return size
        if not isinstance(state, dict) or (state.get('sha256'), state.get('size'), state.get('chunk_size')) != (expected, size, 16*1024*1024):
            return size
    elif part.stat().st_size >= size:
        return 0 if part.stat().st_size == size and digest(part) == expected else size
    info = part.stat()
    allocated = getattr(info, 'st_blocks', 0) * 512
    return max(0, size - min(info.st_size, allocated))


def _phase(progress, label):
    callback = getattr(progress, 'phase', None)
    if callback:
        callback(label)


def install(location=None, apk=None, progress=None):
    host = require_macos()
    _phase(progress, '获取版本信息')
    cat, base = catalog(location); validate_catalog(cat)
    runtime, profile = cat['runtime'], cat['profile']
    if _version(host['macos_version']) < _version(runtime['minimum_macos']):
        raise EngineError('此运行包要求 macOS ' + runtime['minimum_macos'] + ' 或更新版本', 'os_too_old')
    root = home(); root.mkdir(parents=True, exist_ok=True)
    from ..remote.service import directory_lock
    with directory_lock(root/'install-lock'):
        if cat.get('apk_source') == 'netease-pe' and not apk:
            from .official import prepare_latest
            import copy
            profile, downloaded = prepare_latest(root, progress)
            cat = copy.deepcopy(cat); cat['profile'] = profile
            apk = str(downloaded)
        destination = root/'runtimes'/runtime['id']
        game = root/'engines'/profile['apk']['sha256']/'game'
        marker = destination/'release.json'
        if marker.is_file() and read_json(marker)['sha256'] != runtime['sha256']:
            raise EngineError('同一运行包 ID 的内容发生变化，拒绝覆盖。', 'release_changed', '发行方应为每次构建使用新的不可变版本号。')
        _phase(progress, '检查本地资源')
        runtime_valid = _valid(verify_runtime, destination/'McpyRuntime.app', destination/'McpyRuntime.integrity.json', profile)
        game_valid = _valid(verify_game, game, profile)
        if not runtime_valid: _require_idle(destination)
        if not game_valid: _require_idle(game)
        required = 0
        if not game_valid:
            apk_meta = profile['apk']
            required = profile['unpacked_size']
            if not apk:
                required += _remaining_download(root/'cache'/apk_meta['filename'], apk_meta['sha256'], apk_meta['size'])
        required += 0 if runtime_valid else 512 * 1024 * 1024
        if shutil.disk_usage(root).free < required:
            raise EngineError('安装所需可用空间不足，约需 %.1f GB。' % (required / 1e9), 'disk_space')
        # Retain a failed first installation's source for deterministic retry/resume.
        write_json(root/'install-plan.json', {'catalog': cat, 'catalog_base': base})
        if not runtime_valid:
            _phase(progress, '下载启动器')
            source = fetch(locate(base, runtime['url']), root/'cache'/runtime['sha256'], runtime['sha256'], runtime['size'], progress)
            destination.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix='.runtime-', dir=destination.parent))
            try:
                _phase(progress, '校验并安装启动器')
                extract_runtime(source, stage)
                meta = verify_runtime(stage/'McpyRuntime.app', stage/'McpyRuntime.integrity.json', profile)
                if meta['minimum_macos'] != runtime['minimum_macos']:
                    raise EngineError('运行包系统要求与发布目录不一致', 'runtime_incompatible')
                signing = subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(stage/'McpyRuntime.app')], capture_output=True)
                if signing.returncode:
                    raise EngineError('运行包签名校验失败', 'integrity_error')
                write_json(stage/'release.json', runtime)
                _replace(stage, destination)
            finally:
                if stage.exists(): shutil.rmtree(stage)
        apk_meta = profile['apk']
        if apk:
            apk_path = Path(apk).expanduser().resolve()
            if apk_path.stat().st_size != apk_meta['size'] or digest(apk_path) != apk_meta['sha256']:
                raise EngineError('APK 与所选开发者版本不匹配', 'apk_mismatch', '需要 ' + apk_meta['filename'])
        elif not game_valid:
            cached = root/'cache'/apk_meta['filename']
            if cached.is_file() and cached.stat().st_size == apk_meta['size'] and digest(cached) == apk_meta['sha256']:
                apk_path = cached
            else:
                _phase(progress, '下载游戏资源')
                apk_path = fetch(official_apk_url(profile), cached, apk_meta['sha256'], apk_meta['size'], progress)
        if not game_valid:
            game.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix='.apk-', dir=game.parent))
            try:
                _phase(progress, '提取游戏资源')
                extract_apk(apk_path, stage, profile, progress)
                write_json(stage/'installed.json', {'profile': profile, 'apk_sha256': apk_meta['sha256']})
                _replace(stage, game)
            finally:
                if stage.exists(): shutil.rmtree(stage)
        _phase(progress, '检查运行兼容性')
        metadata = verify_runtime(destination/'McpyRuntime.app', destination/'McpyRuntime.integrity.json', profile)
        preflight_runtime(destination/'McpyRuntime.app', game, profile, metadata, runtime['id'])
        write_json(root/'current.json', {'catalog': cat, 'catalog_base': base})
        (root/'install-plan.json').unlink(missing_ok=True)
    result = diagnose()
    if result.get('ok'): _phase(progress, '游戏环境已就绪')
    return result

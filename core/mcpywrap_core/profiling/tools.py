"""固定版本的 Tracy 工具包：清单校验、多镜像续传下载、解压校验与可执行文件定位。

游戏内置 Tracy 0.11.1（协议 69），分析器必须同版本；不使用系统或 Homebrew 中的其他版本。
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path

from ..engines.host import EngineError

MANIFEST_ENV = 'MCPY_TRACY_MANIFEST'  # 开发与测试：替换内置清单
MIRROR_ENV = 'MCPY_TRACY_MIRROR'  # 逗号分隔的镜像基址，优先于清单中的镜像
EXECUTABLES = ('tracy-profiler', 'tracy-capture', 'tracy-csvexport', 'mcpy-tracy-report')
PREFIX = 'mcpy-tracy/'
ROUNDS = 3
BACKOFF = (2, 5)
RETRY_HINT = ('已保留下载进度，网络恢复后重新运行 mcpy profile install 即可续传；'
              '也可设置 MCPY_TRACY_MIRROR 指定镜像，或用 --from 导入已下载的工具包。')


def manifest():
    path = os.environ.get(MANIFEST_ENV)
    source = Path(path).expanduser() if path else Path(__file__).with_name('tools.json')
    try:
        data = json.loads(source.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise EngineError('无法读取 Tracy 工具清单：' + str(error), 'profiler_manifest_invalid') from None
    validate(data)
    return data


def validate(data):
    ok = (isinstance(data, dict) and data.get('schema') == 1 and isinstance(data.get('protocol'), int)
          and isinstance(data.get('tracy_version'), str) and isinstance(data.get('build'), str)
          and isinstance(data.get('mirrors'), list) and all(isinstance(m, str) for m in data['mirrors'])
          and isinstance(data.get('platforms'), dict))
    for entry in (data.get('platforms') or {}).values() if ok else ():
        ok = ok and (isinstance(entry, dict) and isinstance(entry.get('filename'), str)
                     and re.fullmatch(r'[A-Za-z0-9._-]+\.zip', entry['filename']) is not None
                     and isinstance(entry.get('size'), int) and entry['size'] > 0
                     and isinstance(entry.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', entry['sha256']) is not None)
    if not ok:
        raise EngineError('Tracy 工具清单格式无效', 'profiler_manifest_invalid')


def platform_tag():
    machine = platform.machine().lower()
    if sys.platform == 'darwin':
        if machine != 'arm64':
            # Rosetta 中的 Python 也需要识别为 Apple Silicon
            try:
                machine = 'arm64' if subprocess.check_output(
                    ['/usr/sbin/sysctl', '-n', 'hw.optional.arm64'], text=True,
                    stderr=subprocess.DEVNULL).strip() == '1' else machine
            except (OSError, subprocess.CalledProcessError):
                pass
        return 'macos-arm64' if machine == 'arm64' else None
    if os.name == 'nt' and machine in ('amd64', 'x86_64'):
        return 'windows-x64'
    return None


def tools_home():
    if os.environ.get('MCPY_ENGINE_HOME'):
        root = Path(os.environ['MCPY_ENGINE_HOME'])
    elif sys.platform == 'darwin':
        root = Path('~/Library/Application Support/mcpy')
    elif os.name == 'nt':
        root = Path(os.environ.get('LOCALAPPDATA') or '~/AppData/Local') / 'mcpy'
    else:
        root = Path(os.environ.get('XDG_DATA_HOME') or '~/.local/share') / 'mcpy'
    return root.expanduser().resolve() / 'tools' / 'tracy'


def _entry(data):
    tag = platform_tag()
    entry = data['platforms'].get(tag) if tag else None
    if not entry:
        raise EngineError('当前平台暂无 Tracy %s 工具包' % data['tracy_version'], 'unsupported_platform',
                          '支持 Apple Silicon macOS 与 Windows x64；其他平台可用同版本源码自行构建后通过 --from 导入。')
    return tag, entry


def install_dir(data=None, tag=None):
    data = data or manifest()
    return tools_home() / ('%s-%s' % (data['tracy_version'], data['build'])) / (tag or platform_tag() or 'unsupported')


def executable(name, data=None):
    suffix = '.exe' if os.name == 'nt' else ''
    return install_dir(data) / (name + suffix)


def _installed(directory, data, entry):
    try:
        marker = json.loads((directory / 'installed.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    suffix = '.exe' if os.name == 'nt' else ''
    return (marker.get('archive_sha256') == entry['sha256'] and marker.get('protocol') == data['protocol']
            and all((directory / (name + suffix)).is_file() for name in EXECUTABLES))


def status():
    data = manifest()
    tag = platform_tag()
    entry = data['platforms'].get(tag) if tag else None
    directory = install_dir(data, tag)
    return {'tracy_version': data['tracy_version'], 'protocol': data['protocol'], 'build': data['build'],
            'platform': tag, 'available': bool(entry),
            'installed': bool(entry) and _installed(directory, data, entry), 'path': str(directory)}


def installed_identity():
    try:
        return json.loads((install_dir() / 'installed.json').read_text(encoding='utf-8')).get('archive_sha256')
    except (OSError, ValueError):
        return None


def require(name):
    """返回已安装工具的路径；缺失时给出明确的安装命令，不在此处隐式联网。"""
    data = manifest()
    tag, entry = _entry(data)
    directory = install_dir(data, tag)
    if not _installed(directory, data, entry):
        raise EngineError('Tracy %s 工具未安装' % data['tracy_version'], 'profiler_tools_missing',
                          '运行 mcpy profile install；网络受限时可用 --from 导入工具包。')
    return executable(name, data)


def sources(data, entry):
    mirrors = [m.strip() for m in os.environ.get(MIRROR_ENV, '').split(',') if m.strip()] + data['mirrors']
    result = []
    for mirror in dict.fromkeys(mirrors):
        if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', mirror):
            result.append(mirror.rstrip('/') + '/' + entry['filename'])
        else:
            result.append(str(Path(mirror).expanduser().resolve() / entry['filename']))
    return result


def download(urls, cache, entry, progress=None, sleep=time.sleep):
    """依次尝试各镜像，多轮退避重试；同一文件的未完成部分在镜像之间续传。"""
    from ..engines.install import fetch
    errors = []
    for attempt in range(ROUNDS):
        for url in urls:
            try:
                return fetch(url, cache, entry['sha256'], entry['size'], progress)
            except EngineError as error:
                if error.code == 'download_storage_failed':
                    raise
                if error.code in ('integrity_error', 'download_changed'):
                    cache.with_suffix(cache.suffix + '.part').unlink(missing_ok=True)
                errors.append('%s: %s' % (url, error))
            except OSError as error:
                errors.append('%s: %s' % (url, error))
        if attempt < ROUNDS - 1:
            sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])
    raise EngineError('Tracy 工具包下载失败', 'download_failed', RETRY_HINT, attempts=errors[-6:])


def _extract(archive, directory, data, tag, entry):
    from ..engines.install import digest, safe_member
    stage = directory.with_name(directory.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                if member.is_dir():
                    continue
                if not member.filename.startswith(PREFIX):
                    raise EngineError('工具包含意外路径：' + member.filename, 'unsafe_archive')
                relative = safe_member(member.filename[len(PREFIX):])
                target = stage.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, target.open('wb') as stream:
                    shutil.copyfileobj(source, stream)
                if os.name != 'nt':
                    mode = (member.external_attr >> 16) & 0o777
                    target.chmod(0o755 if mode & 0o111 else 0o644)
        info = json.loads((stage / 'BUILDINFO.json').read_text(encoding='utf-8'))
        if (info.get('tracy_version'), info.get('protocol'), info.get('platform')) != (data['tracy_version'], data['protocol'], tag):
            raise EngineError('工具包版本与清单不一致', 'integrity_error')
        suffix = '.exe' if os.name == 'nt' else ''
        for name in EXECUTABLES:
            path = stage / (name + suffix)
            if not path.is_file() or info.get('files', {}).get(path.name) != digest(path):
                raise EngineError('工具包内容校验失败：' + path.name, 'integrity_error')
        (stage / 'installed.json').write_text(json.dumps(
            {'archive_sha256': entry['sha256'], 'tracy_version': data['tracy_version'], 'protocol': data['protocol'],
             'build': data['build'], 'platform': tag}, indent=2) + '\n', encoding='utf-8')
        if directory.exists():
            shutil.rmtree(directory)
        stage.replace(directory)
    except zipfile.BadZipFile:
        raise EngineError('工具包不是有效的 ZIP', 'integrity_error') from None
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def install(from_archive=None, force=False, progress=None):
    data = manifest()
    tag, entry = _entry(data)
    directory = install_dir(data, tag)
    result = {'tracy_version': data['tracy_version'], 'protocol': data['protocol'], 'build': data['build'],
              'platform': tag, 'path': str(directory)}
    if not force and _installed(directory, data, entry):
        return dict(result, installed=True, changed=False)
    cache = tools_home() / 'cache' / entry['filename']
    if from_archive:
        from ..engines.install import fetch
        archive = fetch(str(Path(from_archive).expanduser().resolve()), cache, entry['sha256'], entry['size'])
    else:
        archive = download(sources(data, entry), cache, entry, progress)
    directory.parent.mkdir(parents=True, exist_ok=True)
    _extract(archive, directory, data, tag, entry)
    return dict(result, installed=True, changed=True)

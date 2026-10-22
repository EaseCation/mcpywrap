"""Transactional, offline installation of a trusted pure-Python core wheel.

The host authenticates its release catalog and downloads the artifact. SHA-256
checks integrity against that trusted catalog; it is NOT publisher authentication.
No pip, project code execution, network access or Android-specific implementation.
"""
from contextlib import contextmanager
from email.parser import BytesParser
import hashlib
from importlib import metadata
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import sys
import tempfile
import zipfile

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

MAX_WHEEL_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_FILES = 20000
_SLOT = re.compile(r'^[0-9a-f]{64}$')


class UpdateError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _atomic_json(path, value):
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class CoreStore:
    def __init__(self, root, *, host_api=1, core_api=1, dependency_version=None):
        self.root = Path(root).resolve()
        self.host_api, self.core_api = host_api, core_api
        self.dependency_version = dependency_version or metadata.version
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root/'releases').mkdir(exist_ok=True)

    @contextmanager
    def _lock(self):
        # Must live on host-private lock-capable storage, not /sdcard/FUSE.
        with (self.root/'update.lock').open('a+b') as stream:
            stream.seek(0, 2)
            if not stream.tell():
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise UpdateError('update_busy', '核心升级正在进行，或宿主锁存储不可用。') from error
            yield

    def _slot(self, identity):
        if not isinstance(identity, str) or not _SLOT.fullmatch(identity):
            raise UpdateError('invalid_release', '无效的核心版本标识。')
        path = self.root/'releases'/identity
        if path.is_symlink() or path.parent.is_symlink():
            raise UpdateError('invalid_release', '核心版本目录不能是链接。')
        return path

    def selection(self):
        path = self.root/'selection.json'
        if not path.exists():
            return {'format': 1, 'current': None, 'previous': None}
        value = json.loads(path.read_text(encoding='utf-8'))
        if value.get('format') != 1:
            raise UpdateError('invalid_selection', '不兼容的核心选择记录。')
        for key in ('current', 'previous'):
            if value.get(key) is not None:
                self._slot(value[key])
        return value

    def _inspect(self, data, expected_sha256, expected_version=None):
        if len(data) > MAX_WHEEL_BYTES or hashlib.sha256(data).hexdigest() != expected_sha256:
            raise UpdateError('digest_mismatch', '核心下载内容与受信发布摘要不符。')
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_FILES or sum(info.file_size for info in infos) > MAX_EXPANDED_BYTES:
                raise UpdateError('archive_limit', '核心包超过解压限制。')
            seen, files = set(), {}
            for info in infos:
                name = info.filename.rstrip('/')
                parts = name.split('/')
                if (not name or any(part in ('', '.', '..') for part in parts) or
                        '\\' in name or ':' in name or any(ord(c) < 32 for c in name) or
                        PurePosixPath(name).is_absolute() or name.casefold() in seen or
                        stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1):
                    raise UpdateError('unsafe_wheel', '核心包包含不安全或重复的路径。')
                seen.add(name.casefold())
                if info.is_dir():
                    continue
                if Path(name).suffix.lower() in ('.so', '.pyd', '.dll', '.exe', '.dylib', '.apk', '.dex', '.jar', '.pth'):
                    raise UpdateError('native_payload', 'Python 核心升级不允许替换原生代码或导入启动脚本。')
                files[name] = archive.read(info)
        metadata_paths = [name for name in files if name.count('/') == 1 and name.endswith('.dist-info/METADATA')]
        if len(metadata_paths) != 1:
            raise UpdateError('invalid_wheel', '核心包必须包含唯一的发行元数据。')
        prefix = metadata_paths[0].split('/')[0]
        if any(name.split('/')[0] not in ('mcpywrap_core', 'mcpywrap_host', prefix) for name in files):
            raise UpdateError('invalid_wheel', '核心包不能安装到其他 Python 命名空间。')
        package = BytesParser().parsebytes(files[metadata_paths[0]])
        wheel = BytesParser().parsebytes(files.get(prefix+'/WHEEL', b''))
        version = package.get('Version')
        if canonicalize_name(package.get('Name', '')) != 'mcpywrap-core' or not version:
            raise UpdateError('invalid_wheel', '这不是 mcpywrap 核心包。')
        if expected_version is not None and Version(version) != Version(expected_version):
            raise UpdateError('version_mismatch', '核心版本与受信发布信息不符。')
        if wheel.get('Root-Is-Purelib') != 'true' or wheel.get_all('Tag') != ['py3-none-any']:
            raise UpdateError('native_payload', '核心更新只接受 py3-none-any wheel。')
        requires_python = package.get('Requires-Python')
        if not requires_python or not SpecifierSet(requires_python).contains(platform.python_version(), prereleases=True):
            raise UpdateError('python_incompatible', '此核心需要不同的 Python 运行时。')
        contract = json.loads(files.get('mcpywrap_core/core-contract.json', b'{}'))
        if (contract.get('format') != 1 or contract.get('core_api') != self.core_api or
                contract.get('requires_host_api') != self.host_api or
                contract.get('entrypoint') != 'mcpywrap_core.api:Core'):
            raise UpdateError('host_incompatible', '此核心需要不同的宿主/核心 API。')
        requirements = []
        for declaration in package.get_all('Requires-Dist', []):
            requirement = Requirement(declaration)
            if requirement.marker and not requirement.marker.evaluate({'extra': ''}):
                continue
            if requirement.url or requirement.extras:
                raise UpdateError('dependency_incompatible', '基础依赖不允许 URL 或隐式额外依赖。')
            try:
                installed = self.dependency_version(requirement.name)
            except metadata.PackageNotFoundError as error:
                raise UpdateError('dependency_incompatible', '宿主缺少核心依赖：' + requirement.name) from error
            if not requirement.specifier.contains(installed, prereleases=True):
                raise UpdateError('dependency_incompatible', '宿主依赖版本不满足：' + declaration)
            requirements.append(declaration)
        for required in ('mcpywrap_core/__init__.py', 'mcpywrap_core/api.py'):
            if required not in files:
                raise UpdateError('invalid_wheel', '核心入口缺失：' + required)
        # The pinned bootstrap is not replaced by core updates, even though the
        # normal desktop distribution includes it for the same host API.
        files = {name: content for name, content in files.items() if not name.startswith('mcpywrap_host/')}
        return {'version': version, 'sha256': expected_sha256, 'contract': contract,
                'requires_dist': requirements}, files

    def stage(self, wheel, *, expected_sha256, expected_version):
        """Verify/install only. No import, setup.py, pip or active-version mutation."""
        target = self._slot(expected_sha256)
        with Path(wheel).open('rb') as stream:
            data = stream.read(MAX_WHEEL_BYTES + 1)
        receipt, files = self._inspect(data, expected_sha256, expected_version)
        with self._lock():
            if target.exists():
                return self.verify(expected_sha256)
            stage = Path(tempfile.mkdtemp(prefix='.staging-', dir=self.root))
            try:
                for name, content in files.items():
                    path = stage/name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
                (stage/'source.whl').write_bytes(data)
                _atomic_json(stage/'receipt.json', receipt)
                os.replace(stage, target)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        return receipt

    def verify(self, identity):
        path = self._slot(identity)
        with (path/'source.whl').open('rb') as stream:
            data = stream.read(MAX_WHEEL_BYTES + 1)
        receipt, files = self._inspect(data, identity)
        for name, expected in files.items():
            item = path/name
            if item.is_symlink() or any(parent.is_symlink() for parent in item.parents if parent != self.root):
                raise UpdateError('release_modified', '核心文件被替换为链接。')
            if not item.is_file() or item.read_bytes() != expected:
                raise UpdateError('release_modified', '已安装核心内容被修改：' + name)
        expected_names = set(files) | {'source.whl', 'receipt.json'}
        # Cache bytecode is disabled for imports below; reject injected modules,
        # namespace directories and files as well as changed original bytes.
        actual = {p.relative_to(path).as_posix() for p in path.rglob('*') if p.is_file() or p.is_symlink()}
        expected_dirs = {parent.as_posix() for name in files for parent in PurePosixPath(name).parents if parent.as_posix() != '.'}
        actual_dirs = {p.relative_to(path).as_posix() for p in path.rglob('*') if p.is_dir()}
        if actual != expected_names or actual_dirs != expected_dirs:
            raise UpdateError('release_modified', '已安装核心包含额外或缺失的文件。')
        return receipt

    @staticmethod
    def _fresh_process():
        if any(name in ('mcpywrap', 'mcpywrap_core') or name.startswith(('mcpywrap.', 'mcpywrap_core.')) for name in sys.modules):
            raise UpdateError('restart_required', '核心已载入；请在新的核心进程中切换版本。')

    def _load(self, identity, health_check=None, configure=None):
        self._fresh_process()
        receipt = self.verify(identity)
        sys.path.insert(0, str(self._slot(identity)))
        # Immutable installed releases must not acquire new pyc files.
        sys.dont_write_bytecode = True
        try:
            from mcpywrap_core.api import Core
            core = configure(Core) if configure is not None else Core()
            info = core.describe()
            if (Version(info['version']) != Version(receipt['version']) or
                    info['core_api'] != self.core_api or info['host_api'] != self.host_api):
                raise ValueError('导入后的核心身份与发布契约不符')
            if health_check is not None:
                health_check(core)
            return core
        except Exception as error:
            # Do not hot-swap sys.modules or import an old core in this process.
            raise UpdateError('health_check_failed', '候选核心启动失败；请结束此核心进程，旧选择记录保持可恢复。') from error

    def activate(self, identity, *, health_check=None, configure=None):
        """Fresh worker only: verify + import + health check, then atomic selection."""
        self._fresh_process()
        with self._lock():
            previous = self.selection()
            core = self._load(identity, health_check, configure)
            if previous['current'] != identity:
                _atomic_json(self.root/'selection.json', {'format': 1, 'current': identity,
                    'previous': previous['current']})
            return core

    def load_selected(self, *, health_check=None, configure=None):
        """Return None for bundled core. A failed selection schedules rollback.

        The host must terminate the failed worker, then start a fresh one. This
        method never runs two core versions in a single interpreter.
        """
        self._fresh_process()
        with self._lock():
            selection = self.selection()
            identity = selection['current']
            if identity is None:
                return None
            try:
                return self._load(identity, health_check, configure)
            except Exception:
                _atomic_json(self.root/'selection.json', {'format': 1,
                    'current': selection['previous'], 'previous': None})
                raise

    def rollback(self):
        """Select the previous release (or bundled core) for the next worker."""
        with self._lock():
            selection = self.selection()
            previous = selection['previous']
            if previous is not None:
                self.verify(previous)
            result = {'format': 1, 'current': previous, 'previous': None}
            _atomic_json(self.root/'selection.json', result)
            return dict(result, restart_required=True)

"""只读发现游戏引擎；选择结果在一次操作内复用，不保存机器路径。"""
import ctypes
import os
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import tomli
from packaging.version import InvalidVersion, Version


EXE_NAME = 'Minecraft.Windows.exe'
FIELDS = {
    'game_executable_path': 'MCPY_GAME_EXECUTABLE',
    'mcs_download_path': 'MCPY_MCS_DOWNLOAD_PATH',
    'engine_version': 'MCPY_ENGINE_VERSION',
}


class DiscoveryError(ValueError):
    pass


@dataclass(frozen=True)
class Engine:
    executable: str
    version: str
    engine_dir: str
    download_dir: Optional[str]
    source: str


@dataclass
class DiscoveryResult:
    candidates: list = field(default_factory=list)
    selected: Optional[Engine] = None
    diagnostics: list = field(default_factory=list)
    error: Optional[str] = None

    def require_engine(self):
        if self.error or self.selected is None:
            details = '; '.join(d['message'] for d in self.diagnostics)
            raise DiscoveryError(self.error or details or '未发现游戏引擎')
        return self.selected

    def to_dict(self):
        return asdict(self)


def canonical(path):
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def _issue(diagnostics, source, path, message):
    diagnostics.append({'source': source, 'path': str(path), 'message': message})


def registry_values(name, diagnostics=None):
    """只读取已知的当前用户键；两个视图中的相同路径只返回一次。"""
    diagnostics = diagnostics if diagnostics is not None else []
    if os.name != 'nt':
        _issue(diagnostics, 'registry', '', 'MC Studio 自动发现仅支持 Windows')
        return []
    import winreg
    result, seen = [], set()
    key_path = r'Software\Netease\MCStudio'
    for label, view in [('registry64', winreg.KEY_WOW64_64KEY),
                        ('registry32', winreg.KEY_WOW64_32KEY)]:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                                winreg.KEY_READ | view) as key:
                value, kind = winreg.QueryValueEx(key, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError('注册表值不是非空字符串')
            if kind == winreg.REG_EXPAND_SZ:
                value = os.path.expandvars(value)
            identity = canonical(value) if name in ('DownloadPath', 'InstallLocation') else value
            if identity not in seen:
                seen.add(identity)
                result.append((value, label))
        except (OSError, ValueError) as exc:
            _issue(diagnostics, label, key_path + '\\' + name, str(exc))
    return result


def fixed_drives():
    """只枚举固定磁盘，不访问网络盘或递归搜索磁盘。"""
    if os.name != 'nt':
        return []
    kernel = ctypes.windll.kernel32
    mask = kernel.GetLogicalDrives()
    if not mask:
        raise OSError('无法枚举固定磁盘')
    return [f'{chr(65 + i)}:\\' for i in range(26)
            if mask & (1 << i) and kernel.GetDriveTypeW(ctypes.c_wchar_p(f'{chr(65 + i)}:\\')) == 3]


def discovery_options(project_dir=None, overrides=None, environ=None, cwd=None):
    """逐字段合并 CLI、环境变量、项目配置，并保留各自路径基准。"""
    cwd = Path(cwd or os.getcwd()).resolve()
    project_dir = Path(project_dir or cwd).resolve()
    environ = os.environ if environ is None else environ
    overrides = overrides or {}
    config_file = project_dir / 'pyproject.toml'
    config = {}
    try:
        if config_file.exists():
            with config_file.open('rb') as stream:
                document = tomli.load(stream)
            config = document.get('tool', {}).get('mcpywrap', {})
            if not isinstance(config, dict):
                raise ValueError('tool.mcpywrap 必须是 TOML 表')
    except (OSError, ValueError, AttributeError) as exc:
        raise DiscoveryError(f'无法读取 {config_file}: {exc}') from exc
    options = {}
    for name, env_name in FIELDS.items():
        value, base = config.get(name), project_dir
        if env_name in environ:
            value, base = environ[env_name], cwd
        if overrides.get(name) is not None:
            value, base = overrides[name], cwd
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise DiscoveryError(f'{name} 必须是非空字符串')
        if name == 'engine_version':
            try:
                Version(value)
            except InvalidVersion as exc:
                raise DiscoveryError(f'无效的 engine_version: {value}') from exc
        else:
            path = Path(os.path.expandvars(value)).expanduser()
            value = str((base / path).resolve())
        options[name] = value
    return options


def _is_file(path):
    return stat.S_ISREG(Path(path).stat().st_mode)


def _is_dir(path):
    return stat.S_ISDIR(Path(path).stat().st_mode)


def _scan(root, source, diagnostics):
    root = Path(root).resolve()
    directory = root / 'game' / 'MinecraftPE_Netease'
    candidates = []
    try:
        entries = sorted(directory.iterdir(), key=lambda p: str(p).casefold())
    except OSError as exc:
        _issue(diagnostics, source, directory, f'无法读取引擎目录: {exc}')
        return candidates
    for entry in entries:
        try:
            if not _is_dir(entry):
                continue
            if entry.name.casefold().startswith('pclauncher'):
                _issue(diagnostics, source, entry, '跳过 PCLauncher 目录')
                continue
            Version(entry.name)
            exe = entry / EXE_NAME
            if not _is_file(exe):
                raise ValueError(f'{exe} 不是普通文件')
            candidates.append(Engine(str(exe), entry.name, str(entry), str(root), source))
        except InvalidVersion:
            _issue(diagnostics, source, entry, '跳过无效版本目录')
        except (OSError, ValueError) as exc:
            _issue(diagnostics, source, entry, f'跳过不完整或不可访问的引擎: {exc}')
    if not candidates:
        _issue(diagnostics, source, directory, '此目录没有完整且版本有效的游戏引擎')
    return candidates


def _sorted(candidates):
    # 两次稳定排序：版本降序，同版本按路径升序。
    return sorted(sorted(candidates, key=lambda c: canonical(c.executable)),
                  key=lambda c: Version(c.version), reverse=True)


def _download_from_exe(exe):
    if (exe.parent.parent.name.casefold() == 'minecraftpe_netease'
            and exe.parent.parent.parent.name.casefold() == 'game'):
        return str(exe.parent.parent.parent.parent)
    return None


def discover_engines(project_dir=None, overrides=None, instance_version=None):
    result = DiscoveryResult()
    try:
        options = discovery_options(project_dir, overrides)
        requested = options.get('engine_version') or instance_version
        if requested:
            try:
                requested_version = Version(requested)
            except (InvalidVersion, TypeError) as exc:
                raise DiscoveryError(f'无效的实例版本: {requested}') from exc
        else:
            requested_version = None
        explicit_root = options.get('mcs_download_path')
        if explicit_root and not _is_dir(explicit_root):
            raise DiscoveryError(f'mcs_download_path 不是目录: {explicit_root}')

        def matches(candidate):
            return requested_version is None or Version(candidate.version) == requested_version

        if options.get('game_executable_path'):
            exe = Path(options['game_executable_path'])
            if exe.name.casefold() != EXE_NAME.casefold() or not _is_file(exe):
                raise DiscoveryError(f'game_executable_path 必须指向有效的 {EXE_NAME}: {exe}')
            try:
                version = str(Version(exe.parent.name))
            except InvalidVersion:
                # 非标准目录不得把旧实例版本当作显式版本声明。
                version = options.get('engine_version')
                if not version:
                    raise DiscoveryError('非版本目录中的 EXE 需要显式配置 engine_version')
            inferred_root = _download_from_exe(exe)
            if explicit_root and inferred_root and canonical(explicit_root) != canonical(inferred_root):
                raise DiscoveryError('mcs_download_path 与游戏 EXE 所属下载目录冲突')
            root = explicit_root or inferred_root
            if not root:
                for path, source in registry_values('DownloadPath', result.diagnostics):
                    try:
                        if _is_dir(path):
                            root = str(Path(path).resolve())
                            break
                    except OSError as exc:
                        _issue(result.diagnostics, source, path, str(exc))
            candidate = Engine(str(exe), version, str(exe.parent), root, 'explicit')
            result.candidates = [candidate]
            if not matches(candidate):
                raise DiscoveryError(f'EXE 目录版本 {version} 与要求的版本 {requested} 冲突')
            result.selected = candidate
            return result

        seen_roots, seen_exes = set(), set()

        def collect(roots):
            found = []
            for root, source in roots:
                identity = canonical(root)
                if identity in seen_roots:
                    continue
                seen_roots.add(identity)
                for candidate in _scan(root, source, result.diagnostics):
                    identity = canonical(candidate.executable)
                    if identity not in seen_exes:
                        seen_exes.add(identity)
                        found.append(candidate)
            found = _sorted(found)
            result.candidates.extend(found)
            return next((c for c in found if matches(c)), None)

        if explicit_root:
            result.selected = collect([(explicit_root, 'explicit')])
        else:
            result.selected = collect(registry_values('DownloadPath', result.diagnostics))
            if result.selected is None:
                try:
                    roots = [(str(Path(d) / 'MCStudioDownload'), 'disk') for d in sorted(fixed_drives())]
                    result.selected = collect(roots)
                except OSError as exc:
                    _issue(result.diagnostics, 'disk', '', str(exc))
        if result.selected is None:
            available = ', '.join(dict.fromkeys(c.version for c in _sorted(result.candidates))) or '无'
            raise DiscoveryError(
                f'未找到版本 {requested}；可用版本: {available}' if requested else
                '未发现完整的游戏引擎；请检查 mcpy doctor 的诊断或指定 game_executable_path / mcs_download_path')
    except (ValueError, OSError) as exc:
        result.error = str(exc)
    return result


def resource_issues(engine, purpose='run'):
    """资源就绪性独立于 EXE 发现；不创建目录或下载资源。"""
    issues = []

    def check(path, directory=False):
        try:
            valid = _is_dir(path) if directory else _is_file(path)
            if not valid:
                issues.append(f'资源类型不正确: {path}')
        except OSError as exc:
            issues.append(f'缺少资源或无法访问: {path} ({exc})')

    if not engine.download_dir:
        issues.append('无法定位下载资源目录；请设置 mcs_download_path 或 MCPY_MCS_DOWNLOAD_PATH')
    else:
        root = Path(engine.download_dir)
        check(root, directory=True)
        if purpose == 'run':
            check(root / 'componentcache' / 'support' / 'steve' / 'steve.png')
        elif purpose == 'editor':
            check(root / 'MCX64Editor' / 'MC_Editor.exe')
            check(root / 'EngineAssert', directory=True)
    if purpose == 'run':
        appdata = os.environ.get('APPDATA')
        if not appdata:
            issues.append('未设置 APPDATA，无法定位游戏用户数据目录')
        else:
            check(Path(appdata) / 'MinecraftPE_Netease' / 'games' / 'com.netease', directory=True)
    return issues


def studio_installation(purpose='editor'):
    """编辑器与 Safaia 独立检查启动器安装，不与游戏候选混淆。"""
    diagnostics = []
    for path, source in registry_values('InstallLocation', diagnostics):
        target = (Path(path) / 'data' / 'inner_res' if purpose == 'editor'
                  else Path(path) / 'safaia' / 'safaia_server.exe')
        try:
            if (_is_dir(target) if purpose == 'editor' else _is_file(target)):
                return str(Path(path).resolve()), []
        except OSError as exc:
            _issue(diagnostics, source, target, str(exc))
    return None, [f'{d["path"]}: {d["message"]}' for d in diagnostics] or ['未找到 MC Studio 安装资源']


def require_resources(engine, purpose='run'):
    issues = resource_issues(engine, purpose)
    if issues:
        raise DiscoveryError('\n'.join(issues))


def engine_options(function):
    """多个 CLI 共用同一组参数与内部配置字段名。"""
    import click
    for flag, name, help_text in [
        ('--game-executable', 'game_executable_path', '指定 Minecraft.Windows.exe'),
        ('--mcs-download-path', 'mcs_download_path', '指定 MC Studio 下载目录'),
        ('--engine-version', 'engine_version', '固定完整引擎版本，不自动回退'),
    ]:
        function = click.option(flag, name, default=None, help=help_text)(function)
    return function

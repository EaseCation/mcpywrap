"""Local-world incremental reload targets and game-side scripts."""
import base64
import ctypes
from ctypes import wintypes
from pathlib import Path
import re


KINDS = ('python', 'ui', 'shader', 'material', 'particle')
RESOURCE_DIRS = {'ui': 'ui', 'shader': 'shaders', 'material': 'materials',
                 'particle': 'particles'}


def target_from_file(project, kind, filename):
    if kind not in KINDS:
        raise ValueError('未知的热更类型')
    root = Path(project).resolve()
    path = Path(filename).expanduser().resolve()
    roots = [root]
    if (root/'pyproject.toml').is_file():
        from ..dependencies import DependencyService
        manager = DependencyService(root).resolve()
        roots.extend(Path(pack.path).resolve() for pack in manager.get_all_dependencies().values())
    if not path.is_file() or not any(path.is_relative_to(item) for item in roots):
        raise ValueError('热更文件必须位于当前项目或已装配的依赖包内且已存在')
    pack = next((parent for parent in path.parents if (parent/'manifest.json').is_file()), None)
    if pack is None or not any(pack.is_relative_to(item) for item in roots):
        raise ValueError('热更文件不属于项目中的 Addon 包')
    relative = path.relative_to(pack)
    if kind == 'python':
        if path.suffix.lower() != '.py':
            raise ValueError('Python 热更只接受 .py 文件')
        parts = relative.with_suffix('').parts
        return '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)
    folder = RESOURCE_DIRS[kind]
    if not relative.parts or relative.parts[0].lower() != folder:
        raise ValueError('文件不在对应资源目录中: ' + folder)
    if kind in ('ui', 'particle') and path.suffix.lower() != '.json':
        raise ValueError('此类资源热更只接受 .json 文件')
    if kind == 'material' and path.suffix.lower() != '.material':
        raise ValueError('Material 热更只接受 .material 文件')
    return relative.relative_to(folder).as_posix()


def module_source(project, target):
    root = Path(project).resolve()
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*', target):
        raise ValueError('无效的 Python 模块名')
    roots = [root]
    if (root/'pyproject.toml').is_file():
        from ..dependencies import DependencyService
        manager = DependencyService(root).resolve()
        roots.extend(Path(pack.path).resolve() for pack in manager.get_all_dependencies().values())
    matches = []
    for source_root in roots:
        for manifest in source_root.rglob('manifest.json'):
            pack = manifest.parent
            if pack.relative_to(source_root).parts[:1] not in (('behavior_pack',), ('behavior_packs',)):
                continue
            candidate = pack.joinpath(*target.split('.')).with_suffix('.py')
            if candidate.is_file() and candidate.is_relative_to(source_root):
                matches.append(candidate)
            package = pack.joinpath(*target.split('.'))/'__init__.py'
            if package.is_file() and package.is_relative_to(source_root):
                matches.append(package)
    if len(matches) != 1:
        raise ValueError('Python 模块必须唯一对应当前项目包内的 .py 文件')
    source = matches[0].read_bytes()
    if len(source) > 24000:
        raise ValueError('热更模块源码超过 24 KiB')
    return source


def reload_code(kind, target, source=None):
    if kind not in KINDS or kind == 'ui':
        raise ValueError('此热更类型不通过游戏 Python 通道执行')
    if not isinstance(target, str) or not target or len(target) > 512:
        raise ValueError('热更目标无效')
    if kind == 'python' and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*', target):
        raise ValueError('无效的 Python 模块名')
    literal = repr(target)
    if kind == 'python':
        if not isinstance(source, bytes):
            raise ValueError('Python 热更缺少模块源码')
        encoded = base64.b64encode(source).decode('ascii')
        body = '''import sys, base64
_m_module = sys.modules.get(%s)
if _m_module is None:
    _result = {'ok': False, 'reason': 'module_not_loaded', 'target': %s}
else:
    _m_source = base64.b64decode('%s')
    exec compile(_m_source, '<mcpy-reload:%s>', 'exec') in _m_module.__dict__, _m_module.__dict__
    _result = {'ok': True, 'target': %s}
''' % (literal, literal, encoded, target, literal)
    elif kind == 'shader':
        body = '''try:
    import clientlevel
except ImportError:
    _result = {'ok': False, 'unsupported': True}
else:
    if not hasattr(clientlevel, 'reload_one_shader'):
        _result = {'ok': False, 'unsupported': True}
    else:
        _result = {'ok': bool(clientlevel.reload_one_shader(%s, True)), 'target': %s}
''' % (literal, literal)
    elif kind == 'material':
        name = 'materials/' + target
        body = '''try:
    import clientlevel
except ImportError:
    _result = {'ok': False, 'unsupported': True}
else:
    if not hasattr(clientlevel, 'reload_one_material_file'):
        _result = {'ok': False, 'unsupported': True}
    else:
        _result = {'ok': bool(clientlevel.reload_one_material_file(%s, True)), 'target': %s}
''' % (repr(name), literal)
    else:
        name = 'particles/' + target
        body = '''try:
    import _particle_system
except ImportError:
    _result = {'ok': False, 'unsupported': True}
else:
    if not hasattr(_particle_system, 'load'):
        _result = {'ok': False, 'unsupported': True}
    else:
        _result = {'ok': bool(_particle_system.load(%s)), 'target': %s}
''' % (repr(name), literal)
    return '# coding: utf-8\n' + body


def reload_ui(project, session):
    from . import sessions
    from .processes import checked_process
    data = sessions.read(project, session)
    if data.get('mode') != 'local' or data['state'] != 'running':
        raise ValueError('JSON UI 热更只支持运行中的本地世界')
    process = checked_process(data['game'])
    if not process:
        raise ValueError('游戏进程已退出')
    from .window import GameWindow
    window = GameWindow(data['game'])
    hwnd = window.hwnd
    window.close()
    user32 = ctypes.windll.user32
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    user32.MapVirtualKeyW.restype = wintypes.UINT
    for message, key in ((0x100, 0x11), (0x100, 0x52), (0x101, 0x52), (0x101, 0x11)):
        scan = user32.MapVirtualKeyW(key, 0)
        lparam = 1 | (scan << 16) | ((1 << 30) | (1 << 31) if message == 0x101 else 0)
        if not user32.PostMessageW(hwnd, message, key, lparam):
            raise ValueError('JSON UI 重载快捷键投递失败')
    return {'state': 'triggered', 'kind': 'ui', 'effect_verified': False}


def reload_session(project, session, kind, target=None, source=None):
    from . import sessions
    from .runtime_debug import control_request
    data = sessions.read(project, session)
    if data.get('mode') != 'local':
        raise ValueError('热更只支持 Windows 本地测试世界')
    engine_version = Path(data.get('game', {}).get('executable', '')).parent.name
    if kind == 'shader' and engine_version in ('3.9.0.401155', '3.10.0.420447'):
        return {'state': 'unsupported', 'kind': kind, 'target': target,
                'error': '此引擎版本的 Shader 重载未经安全验证或曾阻塞游戏线程'}
    if kind == 'ui':
        return reload_ui(project, session)
    if not target:
        raise ValueError('此热更类型需要文件或模块目标')
    source = (source if source is not None else module_source(project, target)) if kind == 'python' else None
    if source is not None and (not isinstance(source, bytes) or len(source) > 24000):
        raise ValueError('热更模块源码必须是字节内容且不超过 24 KiB')
    result = control_request(project, session, 'reload', kind=kind, target=target,
                             **({'source': base64.b64encode(source).decode('ascii')} if source else {}))
    value = result.get('value')
    if result.get('state') == 'completed' and isinstance(value, dict):
        if value.get('unsupported'):
            result.update(state='unsupported', error='目标引擎未提供此重载接口')
        elif value.get('ok') is False:
            result.update(state='failed', error=value.get('reason', '游戏重载接口报告失败'))
    result.update(kind=kind, target=target)
    return result

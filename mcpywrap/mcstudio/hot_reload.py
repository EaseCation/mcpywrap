"""Local-world incremental reload targets and game-side scripts."""
import base64
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
    from ..engines.backend import get_backend
    backend = get_backend(data.get('backend', 'windows'))
    reason = backend.reload_restriction(data, 'ui')
    if reason:
        return {'state': 'unsupported', 'kind': 'ui', 'error': reason, 'effect_verified': False}
    if not checked_process(data['game']): raise ValueError('游戏进程已退出')
    from .runtime_debug import control_request
    code = backend.ui_reload_code()
    result = control_request(project, session, 'execute', code=code, side='client')
    if result.get('state') == 'completed':
        value = result.get('value')
        if isinstance(value, dict) and value.get('unsupported'):
            result.update(state='unsupported', error='当前运行包没有可用的 JSON UI 重载接口，请安装支持的运行包并启动新实例。')
        elif not isinstance(value, dict) or value.get('ok') is not True:
            result.update(state='failed', error='引擎未接受 JSON UI 重载请求')
        else:
            result.update(state='triggered', hint='已请求异步重载 UI 定义；已有自定义控件可能失效，请重新打开界面并按 Mod 原有逻辑创建控件和绑定回调。')
    result.update(kind='ui', effect_verified=False)
    return result


def reload_session(project, session, kind, target=None, source=None, side='client'):
    from . import sessions
    from .runtime_debug import control_request
    if kind not in KINDS: raise ValueError('未知的热更类型')
    if side not in ('client', 'server') or (side == 'server' and kind != 'python'):
        raise ValueError('服务端热更仅支持 Python 模块')
    data = sessions.read(project, session)
    if data.get('mode') != 'local':
        raise ValueError('热更只支持运行中的本地测试世界')
    if data['state'] != 'running': raise ValueError('游戏会话未运行')
    from ..engines.backend import get_backend
    backend = get_backend(data.get('backend', 'windows'))
    reason = backend.reload_restriction(data, kind)
    if reason:
        return {'state': 'unsupported', 'kind': kind, 'target': target,
                'error': reason, 'effect_verified': False}
    backend.deploy(project, data)
    if kind == 'ui':
        return backend.reload_ui(project, session)
    if not target:
        raise ValueError('此热更类型需要文件或模块目标')
    source = (source if source is not None else module_source(project, target)) if kind == 'python' else None
    if source is not None and (not isinstance(source, bytes) or len(source) > 24000):
        raise ValueError('热更模块源码必须是字节内容且不超过 24 KiB')
    result = control_request(project, session, 'reload', kind=kind, target=target, side=side,
                             **({'source': base64.b64encode(source).decode('ascii')} if source else {}))
    actual_side = result.get('side')
    if kind == 'python' and (actual_side not in (None, side) or
                            (result.get('state') == 'completed' and actual_side is None)):
        result.update(state='unknown', code='reload_side_mismatch', expected_side=side,
                      error='worker 返回的执行端侧与请求不一致；副作用未确认，请检查会话，不要自动重试。')
    value = result.get('value')
    if result.get('state') == 'completed' and isinstance(value, dict):
        if value.get('unsupported'):
            result.update(state='unsupported', error='目标引擎未提供此重载接口')
        elif value.get('ok') is False:
            result.update(state='failed', error=value.get('reason', '游戏重载接口报告失败'))
    if kind != 'python':
        result['effect_verified'] = False
        if result.get('state') == 'completed':
            result.update(state='triggered', hint='已提交资源重载，请检查实际效果；新增资源未被识别时，请重新部署并重载世界。')
    result.update(kind=kind, target=target)
    return result


class SessionWatcher:
    """Shared CLI/Qt watch service: existing builder, debounced changes, explicit sides."""
    def __init__(self, project, session, report=print, sides=('client',)):
        import queue
        import threading
        if not sides or any(side not in ('client', 'server') for side in sides):
            raise ValueError('无效的热更端侧')
        self.sides = tuple(dict.fromkeys(sides))
        self.project, self.session, self.report = Path(project).resolve(), session, report
        self.pending = queue.Queue()
        self.stopping = threading.Event()
        self.thread = None
        self.watcher = None

    def start(self):
        import threading
        from . import sessions
        from ..builders.project_builder import AddonProjectBuilder
        from ..builders.watcher import ProjectWatcher
        from ..dependencies import read_project
        data = sessions.read(self.project, self.session)
        if data.get('mode') != 'local' or data['state'] != 'running':
            raise ValueError('自动热更需要运行中的本地世界')
        config = read_project(self.project)
        if config.get('tool', {}).get('mcpywrap', {}).get('project_type', 'addon') != 'addon':
            raise ValueError('自动热更仅支持 Addon 项目')
        from ..engines.backend import get_backend
        self.target = get_backend(data.get('backend', 'windows')).watch_directory(self.project, data)
        success, error = AddonProjectBuilder(self.project, self.target).build()
        if not success: raise ValueError(error)
        self.watcher = ProjectWatcher(str(self.project), str(self.target), self.changed)
        try:
            self.watcher.setup_from_config(config.get('project', {}).get('name', 'project'), config.get('project', {}).get('dependencies', []))
            self.watcher.start()
        except Exception:
            self.watcher.stop(); raise
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        self.report('自动热更已开启（' + ', '.join(self.sides) + '）：新增模块、注册逻辑和资源改动请重载世界。', 'info')

    def changed(self, src, dest, success, output, is_python, is_dependency=False, dependency_name=None, event_type=None):
        if not success: self.report('构建失败：' + output, 'error')
        elif event_type == 'deleted': self.report('文件已删除，请重新部署并重载世界：' + src, 'warning')
        elif dest: self.pending.put(dest)

    def _loop(self):
        import queue
        from ..commands.dev_cmd import changed_reload_targets
        from . import sessions
        while not self.stopping.is_set():
            try: first = self.pending.get(timeout=.2)
            except queue.Empty: continue
            if self.stopping.wait(.6): break
            paths = {first}
            while True:
                try: paths.add(self.pending.get_nowait())
                except queue.Empty: break
            try:
                if sessions.read(self.project, self.session)['state'] != 'running':
                    self.report('会话已退出，停止热更。', 'info'); break
                targets = changed_reload_targets(self.target, paths)
                if not targets: self.report('资源已构建，请重新部署并重载世界。', 'info')
                for (kind, target), path in targets.items():
                    if kind != 'python':
                        self.report('资源变更 ' + path + '；请手动热更或重载世界。', 'info'); continue
                    source = Path(path).read_bytes()
                    for side in self.sides:
                        if self.stopping.is_set(): break
                        result = reload_session(self.project, self.session, kind, target, source, side)
                        value = result.get('value') or {}
                        if value.get('reason') == 'module_not_loaded':
                            self.report(side + ' 未加载 ' + target + '，跳过；新增入口请重载世界。', 'info')
                        else:
                            self.report(side + ' ' + target + ': ' + str(result.get('error') or result['state']),
                                        'success' if result['state'] == 'completed' else 'error')
            except Exception as error:
                self.report('热更失败：' + str(error), 'error')

    def stop(self):
        self.stopping.set()
        if self.watcher: self.watcher.stop()
        if self.thread:
            self.thread.join(timeout=30)
            if self.thread.is_alive(): raise ValueError('热更调用尚未返回，请稍后再关闭')

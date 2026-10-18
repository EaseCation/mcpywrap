"""Observe source changes; only the deployment service may write runtime files."""
from pathlib import Path
import queue
import threading
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ..dependencies import DependencyService
from ..engines.host import EngineError
from ..mcstudio import sessions
from . import groups


class SessionWatcher:
    def __init__(self, project, session=None, report=print, sides=('client',), group=None):
        if not sides or any(side not in ('client', 'server') for side in sides):
            raise ValueError('无效的热更端侧')
        if bool(session) == bool(group):
            raise ValueError('监控必须指定一个会话或联调组')
        self.project = Path(project).resolve()
        self.session, self.group, self.report, self.sides = session, group, report, tuple(dict.fromkeys(sides))
        self.pending = queue.Queue()
        self.stopping = threading.Event()
        self.thread = None
        self.observer = None
        self.started = threading.Event()
        self.start_error = None

    def start(self):
        try:
            if self.group:
                record = groups.status(self.project, self.group)
                if record['kind'] != 'local' or record['state'] != 'ready':
                    raise EngineError('联调组尚未确认两名玩家就绪。', 'group_not_ready')
            else:
                record = sessions.read(self.project, self.session)
                if record.get('mode') != 'local' or record['state'] != 'running':
                    raise ValueError('自动热更需要运行中的本地世界')
                group = groups.membership(self.project, self.session)
                if group:
                    raise EngineError('联调成员请通过组入口监控，未启动单会话监控。', 'group_required',
                                      '使用 runtime watch --group ' + group['group'])
            manager = DependencyService(self.project).resolve()
            paths = {Path(pack.path).resolve() for pack in manager.get_all_dependencies().values()}
            paths.add(self.project)
            owner = self
            class Handler(FileSystemEventHandler):
                def on_any_event(self, event):
                    if event.event_type not in ('created', 'modified', 'deleted', 'moved'):
                        return
                    for value in (event.src_path, getattr(event, 'dest_path', None)):
                        if not value:
                            continue
                        path = Path(value).resolve()
                        try:
                            relative = path.relative_to(owner.project)
                            if relative.parts and relative.parts[0] in ('.runtime', '.mcpy', '.git', 'build', 'dist'):
                                continue
                        except ValueError:
                            pass
                        if path.suffix in ('.pyc', '.pyo') or '__pycache__' in path.parts:
                            continue
                        owner.pending.put(str(path))
            self.observer = Observer()
            for path in sorted(paths):
                self.observer.schedule(Handler(), str(path), recursive=True)
            self.observer.start()
            self.thread = threading.Thread(target=self._owned_loop, daemon=True)
            self.thread.start()
            if not self.started.wait(5):
                raise EngineError('监控启动超时。', 'watch_timeout')
            if self.start_error:
                raise self.start_error
            self.report('自动热更已开启；依赖或包结构变化需要重新运行。', 'info')
        except BaseException:
            self.stop()
            raise

    def _owned_loop(self):
        from ..utils.locks import directory_lock
        try:
            with directory_lock(self.project/'.runtime/watch-locks'/(self.group or self.session)):
                self.started.set()
                self._loop()
        except BaseException as error:
            self.start_error = error
            self.started.set()
            self.stopping.set()
        finally:
            if self.observer:
                self.observer.stop()

    def _loop(self):
        from .targets import changed_reload_targets
        from ..mcstudio.hot_reload import reload_session
        next_check = 0
        while not self.stopping.is_set():
            if time.monotonic() >= next_check:
                next_check = time.monotonic() + 2
                if self.group:
                    state = groups.status(self.project, self.group)
                    if state['state'] != 'ready':
                        self.report('联调组成员不再全部就绪，监控已停止。', 'warning')
                        break
                elif sessions.read(self.project, self.session)['state'] != 'running':
                    break
            try:
                first = self.pending.get(timeout=.2)
            except queue.Empty:
                continue
            if self.stopping.wait(.5):
                break
            paths = {first}
            while True:
                try:
                    paths.add(self.pending.get_nowait())
                except queue.Empty:
                    break
            try:
                if self.group:
                    state = groups.status(self.project, self.group)
                    if state['state'] != 'ready':
                        self.report('联调组成员不再全部就绪，监控已停止。', 'warning'); break
                elif sessions.read(self.project, self.session)['state'] != 'running':
                    break
                if any(Path(p).name in ('pyproject.toml', 'manifest.json', 'pack_manifest.json', 'mcpy-git.lock.json') for p in paths):
                    self.report('依赖或包声明发生变化，请重新运行；未更新运行文件。', 'warning')
                    continue
                targets = changed_reload_targets(self.project, [p for p in paths if Path(p).is_file()])
                if any(not Path(p).exists() for p in paths):
                    self.report('文件已删除，请重新运行以更新完整内容。', 'warning')
                for (kind, target), filename in targets.items():
                    if kind != 'python':
                        self.report('资源已变化，请选择对应的手动重载动作。', 'info'); continue
                    source = Path(filename).read_bytes()
                    if self.group:
                        side = 'both' if len(self.sides) == 2 else self.sides[0]
                        result = groups.reload(self.project, self.group, kind, target, source, side)
                        self.report(str(result), 'success' if result.get('ok') else 'warning')
                    else:
                        for side in self.sides:
                            result = reload_session(self.project, self.session, kind, target, source, side)
                            self.report(str(result), 'info')
            except (OSError, ValueError) as error:
                self.report(str(error), 'error')
        self.stopping.set()

    def stop(self):
        self.stopping.set()
        if self.observer:
            self.observer.stop(); self.observer.join(timeout=5)
            self.observer = None
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=20)
            if self.thread.is_alive():
                raise EngineError('热更请求尚未结束，请等待结果后关闭监控。', 'busy')

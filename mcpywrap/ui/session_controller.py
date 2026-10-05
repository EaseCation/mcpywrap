"""One GUI session owner shared by every view; engine behavior stays in backends."""
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot, QTimer
from ..mcstudio import sessions
from ..mcstudio.processes import checked_process
from .session_tools import TaskThread
from .log_view import SessionLogs


class SessionController(QObject):
    changed = Signal()
    started = Signal(object)
    stopped = Signal(object)
    failed = Signal(str)
    watch_message = Signal(str, str)

    def __init__(self, project, backend, parent=None, engine_overrides=None):
        super().__init__(parent)
        self.project, self.backend = str(Path(project).resolve()), backend
        self.engine_overrides = {key: value for key, value in (engine_overrides or {}).items() if value is not None}
        self.session, self.owns_session, self.data = None, False, {}
        self.task, self.watcher = None, None
        self.workspace_busy = False
        self.watch_side = 'client'
        self.logs = SessionLogs(self)
        self.status = backend.label + ' · 未启动'
        self._last_error = None
        self.watch_message.connect(self.log)
        self.timer = QTimer(self); self.timer.timeout.connect(self.poll); self.timer.start(500)

    @property
    def busy(self): return self.task is not None

    @property
    def available(self): return not self.busy and not self.workspace_busy

    def set_workspace_busy(self, value):
        self.workspace_busy = value; self.changed.emit()

    @Slot(str, str)
    def log(self, message, level='info'):
        tag = {'error': 'ERROR', 'warning': 'WARN', 'success': 'SUCCESS'}.get(level, 'INFO')
        text = '[%s] [%s] %s\n' % (datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3], tag, message)
        self.logs.append('operations', text)

    def report_result(self, result):
        if not isinstance(result, dict):
            if result is not None: self.log(str(result))
            return
        for key in ('stdout', 'stderr', 'error', 'hint'):
            if result.get(key): self.log(result[key], 'info' if key in ('stdout', 'hint') else 'error')
        if result.get('value') is not None: self.log(str(result['value']))
        elif result.get('state'): self.log(result['state'])

    def run_task(self, function, success=None, failure=None, report=True):
        if not self.available:
            self.log('请等待当前操作完成。', 'warning'); return False
        self._success, self._failure, self._report = success, failure, report
        self._result, self._error = None, None
        self.task = TaskThread(function, self)
        self.task.result.connect(self._received)
        self.task.failed.connect(self._failed)
        self.task.finished.connect(self._finished)
        self.changed.emit(); self.task.start()
        return True

    @Slot(object)
    def _received(self, result): self._result = result

    @Slot(str)
    def _failed(self, message): self._error = message

    @Slot()
    def _finished(self):
        task, self.task = self.task, None
        result, error, success, failure = self._result, self._error, self._success, self._failure
        report = self._report
        task.deleteLater()
        if error:
            self.log(error, 'error')
            if failure: failure()
            self.failed.emit(error)
        else:
            if report: self.report_result(result)
            if success: success(result)
        self.changed.emit()

    def start(self, identity=None, auth_context=None):
        if self.session:
            self.log('请先保存退出当前游戏。', 'warning'); return False
        options = {'overrides': self.engine_overrides} if self.engine_overrides else {}
        return self.run_task(lambda: self.backend.start_session(self.project, identity, auth_context, **options), self.attach, report=False)

    @Slot(object)
    def attach(self, result):
        self.session = result['session']
        self.owns_session = not result.get('already_running', False)
        self.data = result
        self.logs.bind(self.project, self.session)
        self.log('游戏会话已启动：' + self.session, 'success')
        self.started.emit(result); self.changed.emit(); self.poll()

    @Slot()
    def poll(self):
        try:
            self.logs.poll()
            if not self.session: return
            self.data = sessions.read(self.project, self.session)
            state = self.data['state']
            self.status = self.backend.label + ' · ' + ('世界已就绪' if self.data.get('world_ready') else state) + ' · ' + self.session[:8]
            if state not in ('starting', 'running') and not self.busy:
                alive = self.data.get('game') and checked_process(self.data['game'])
                if alive:
                    self.status = '游戏仍运行，请保存退出：' + str(self.data.get('error') or state)
                elif self.watcher:
                    self.set_watching(False)
                else:
                    self._end_session()
            self._last_error = None
        except (OSError, ValueError) as error:
            self.status = str(error)
            if self._last_error != self.status:
                self.log(self.status, 'error'); self._last_error = self.status
        self.changed.emit()

    def _end_session(self):
        self.logs.finish()
        self.session, self.owns_session = None, False
        self.status = self.backend.label + ' · 已退出'
        if self.data.get('error'): self.log(self.data['error'], 'error')
        self.changed.emit()

    def stop(self):
        if not self.session or not self.available: return False
        session, watcher = self.session, self.watcher
        def perform():
            if watcher: watcher.stop()
            return sessions.stop(self.project, session)
        def finished(result):
            self.watcher = None; self._end_session(); self.stopped.emit(result)
        return self.run_task(perform, finished)

    def restart(self):
        if not self.session or not self.available: return False
        session, watcher = self.session, self.watcher
        def perform():
            if watcher: watcher.stop()
            data = sessions.read(self.project, session)
            sessions.stop(self.project, session)
            overrides = self.engine_overrides or data.get('engine_overrides') or {}
            return self.backend.start_session(self.project, data['level_id'],
                                              **({'overrides': overrides} if overrides else {}))
        def finished(result):
            self.watcher = None; self.logs.finish(); self.attach(result)
        def failed():
            self.watcher = None; self.poll()
        return self.run_task(perform, finished, failed, report=False)

    def execute(self, code, side='client'):
        if not self.session or not code.strip(): return False
        from ..mcstudio.runtime_debug import control_request
        session = self.session
        return self.run_task(lambda: control_request(self.project, session, 'execute', code=code, side=side))

    def reload_file(self, filename, side='client'):
        if not self.session: return False
        from ..commands.dev_cmd import changed_reload_targets
        from ..mcstudio.hot_reload import reload_session
        session = self.session
        def perform():
            targets = changed_reload_targets(self.project, [str(filename)])
            if not targets: raise ValueError('此文件不能直接热更，请重新部署并重载世界。')
            (kind, target), _ = next(iter(targets.items()))
            return reload_session(self.project, session, kind, target,
                source=Path(filename).read_bytes() if kind == 'python' else None, side=side)
        return self.run_task(perform)

    def set_watch_side(self, side):
        if side not in ('client', 'server', 'both'): raise ValueError('无效的热更端侧')
        if self.watcher: return
        self.watch_side = side; self.changed.emit()

    def set_watching(self, enabled):
        if not self.available: return False
        if not enabled:
            if not self.watcher: return False
            watcher = self.watcher
            def finished(_): self.watcher = None
            return self.run_task(watcher.stop, finished, report=False)
        if self.watcher or not self.session: return False
        from ..mcstudio.hot_reload import SessionWatcher
        sides = ('client', 'server') if self.watch_side == 'both' else (self.watch_side,)
        self.watcher = SessionWatcher(self.project, self.session, self.watch_message.emit, sides=sides)
        def failed(): self.watcher = None
        return self.run_task(self.watcher.start, failure=failed, report=False)

    def dispose(self):
        if self.busy or self.watcher or (self.session and self.owns_session):
            raise RuntimeError('请先完成会话操作、停止监控并保存退出拥有的游戏')
        self.timer.stop(); self.logs.finish()

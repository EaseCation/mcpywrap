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
        self.owned_sessions = set()
        self.group = None
        self.preparing_session = None
        self.members = []
        self.group_data = {}
        self.all_logs = False
        self.task, self.watcher = None, None
        self.workspace_busy = False
        self.watch_side = 'client'
        self.logs = SessionLogs(self)
        self.status = backend.label + ' · 未启动'
        self._last_error = None
        self.failure_diagnostic = {}
        self.failure_session = None
        self.failure_group = None
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
        self.task.starting.connect(self._preparing)
        self.task.result.connect(self._received)
        self.task.diagnostic.connect(self._diagnosed)
        self.task.failed.connect(self._failed)
        self.task.finished.connect(self._finished)
        self.changed.emit(); self.task.start()
        return True

    @Slot(object)
    def _preparing(self, data):
        if not data.get('start_owned'):
            return
        if data['state'] == 'starting':
            if self.preparing_session != data['session']:
                self.preparing_session = data['session']
                self.logs.bind(self.project, self.preparing_session)
                self.log('正在准备游戏：' + self.preparing_session)
            script = data.get('script') or {}
            self.status = '准备中' + (' · ' + script['script'] if script else '')
        self.changed.emit()

    def cancel_preparation(self):
        if not self.preparing_session:
            return False
        data = sessions.read(self.project, self.preparing_session)
        if data['state'] != 'starting':
            self.log('准备已结束，请等待启动结果后使用停止操作。', 'info')
            return False
        (sessions.session_path(self.project, self.preparing_session)/'stop').touch()
        self.log('已请求取消本次准备。', 'warning')
        return True

    @Slot(object)
    def _received(self, result):
        self._result = result
        if isinstance(result, dict) and result.get('ok') is False:
            self.failure_diagnostic = result
            self.failure_session = result.get('session')
            self.failure_group = result.get('group')

    @Slot(object)
    def _diagnosed(self, value):
        self.failure_diagnostic = value
        self.failure_session = self.preparing_session or (value.get('details') or {}).get('session')
        self.failure_group = (value.get('details') or {}).get('group') or value.get('group')

    def restore_startup_problem(self, items):
        if self.backend.id != 'windows' or not self.available or self.session:
            return False
        if not any(item.get('last_session') for item in items):
            return False
        from ..runtime.deployment_service import startup_problem
        def found(value):
            if value:
                from ..runtime.diagnostics import format_diagnostic
                self._diagnosed(value)
                self.status = '需要处理旧部署冲突'
                self.log(format_diagnostic(value), 'warning')
            else:
                self.failure_diagnostic = {}
                self.failure_session = self.failure_group = None
                self.status = self.backend.label + ' · 未启动'
        def failed():
            self.status = '旧部署检查失败，请查看操作日志'
        self.status = '正在检查上次启动的部署问题…'
        return self.run_task(lambda: startup_problem(self.project, items=items), found, failed, report=False)

    def deployment_preview(self, action='inspect', from_project=None):
        from ..runtime.deployment_service import preview
        group = self.group or self.failure_group
        return preview(self.project, action, from_project,
                       session=None if group else self.failure_session, group=group)

    def deployment_apply(self, value, from_project=None):
        from ..runtime.deployment_service import execute
        group = self.group or self.failure_group
        session = None if group else self.failure_session
        return self.run_task(lambda: execute(self.project, value['action'], from_project,
            session=session, group=group,
            expect=value['plan_digest']), self.attach if value['action']=='migrate' else None)

    @Slot(str)
    def _failed(self, message): self._error = message

    @Slot()
    def _finished(self):
        task, self.task = self.task, None
        result, error, success, failure = self._result, self._error, self._success, self._failure
        report = self._report
        task.deleteLater()
        preparing = self.preparing_session
        if self.preparing_session:
            self.logs.poll()
            self.preparing_session = None
        if error:
            if preparing:
                self.status = '准备未完成'
                if self.session:
                    self.bind_logs()
                    self.poll()
            self.log(error, 'error')
            if failure: failure()
            self.failed.emit(error)
        else:
            if report: self.report_result(result)
            if success: success(result)
            if isinstance(result, dict) and result.get('session') and result.get('ok', True) and result.get('state')!='preview':
                self.failure_diagnostic = {}
                self.failure_session = None
                self.failure_group = None
        self.changed.emit()

    def start(self, identity=None, auth_context=None, world_config=None, clients=1):
        active = self.session and (self.data.get('state') in ('starting', 'running') or
                                   self.data.get('state') == 'failed' and bool(self.data.get('game')))
        if active and clients == 1:
            self.log('请先停止当前游戏；重要进度请先在游戏内保存。', 'warning'); return False
        options = {'overrides': self.engine_overrides} if self.engine_overrides else {}
        if world_config is not None: options['world_config'] = world_config
        if clients != 1:
            options['clients'] = clients
            if active:
                if self.group_data.get('kind') == 'local':
                    host = next(m for m in self.members if m['role'] == 'host')
                    identity = sessions.read(self.project, host['session']).get('level_id') or identity
                else:
                    identity = self.data.get('level_id') or identity
        return self.run_task(lambda: self.backend.start_session(self.project, identity, auth_context, **options), self.attach, report=False)

    @Slot(object)
    def attach(self, result):
        if not result.get('group') and result.get('session'):
            from ..runtime import groups
            record = groups.membership(self.project, result['session'])
            if record:
                result = dict(groups.status(self.project, record['group']), session=result['session'],
                              owned_sessions=[] if result.get('already_running') else [result['session']])
        previous_group, previous_owned = self.group, self.owned_sessions
        previous_role = next((m['role'] for m in self.members if m.get('session') == self.session), None)
        self.group = result.get('group')
        self.members = result.get('members', [])
        self.group_data = result if self.group else {}
        self.session = result.get('session') or next((m.get('session') for m in self.members if m.get('session')), None)
        if self.group and self.group == previous_group and previous_role:
            self.session = next((m['session'] for m in self.members if m['role'] == previous_role), self.session)
        self.owned_sessions = (set(result.get('owned_sessions', ())) if self.group else
                               {self.session} if self.session and not result.get('already_running', False) else set())
        if self.group and self.group == previous_group:
            active_ids = {member.get('session') for member in self.members}
            self.owned_sessions.update(previous_owned & active_ids)
        self.owns_session = self.session in self.owned_sessions
        self.data = result
        if self.session:
            self.bind_logs()
        self.log(('联调组已记录，仍有成员需要处理：' if result.get('ok') is False else '游戏会话已启动：')
                 + str(self.group or self.session), 'warning' if result.get('ok') is False else 'success')
        if result.get('error'): self.log(result['error'], 'error')
        if result.get('hint'): self.log(result['hint'], 'info')
        for message in result.get('warnings', []): self.log(message, 'info')
        self.started.emit(result); self.changed.emit(); self.poll()

    def bind_logs(self):
        if self.all_logs and self.group:
            self.logs.bind_group(self.project, self.members)
        elif self.session:
            self.logs.bind(self.project, self.session)

    def select_member(self, session):
        if self.busy or not any(m.get('session') == session for m in self.members):
            return
        self.session = session
        try:
            self.data = sessions.read(self.project, session)
        except ValueError:
            self.data = {'session': session, 'state': 'failed', 'mode': 'network'}
        self.owns_session = session in self.owned_sessions
        self.bind_logs(); self.poll()

    def set_all_logs(self, enabled):
        self.all_logs = enabled
        self.bind_logs()

    def connect(self, host, port=19132, clients=2):
        from ..mcstudio.network import ServerTarget
        from ..runtime import groups
        target = ServerTarget(host, port)
        operation = (lambda: groups.start_network(self.project, self.backend, target, self.engine_overrides)) if clients == 2 else (
            lambda: self.backend.connect(target, project_dir=self.project, engine_overrides=self.engine_overrides, detach=True))
        return self.run_task(operation, self.attach, report=False)

    def group_action(self, action):
        if not self.group or not self.available:
            return False
        from ..runtime import groups
        group = self.group
        def perform():
            if self.watcher:
                self.watcher.stop()
            return groups.restart(self.project, group=group) if action == 'restart' else groups.stop(self.project, group)
        def finished(result):
            self.watcher = None
            if action == 'restart': self.attach(result)
            else: self.poll()
        return self.run_task(perform, finished)

    @Slot()
    def poll(self):
        try:
            self.logs.poll()
            if self.preparing_session and self.busy:
                data = sessions.read(self.project, self.preparing_session)
                script = data.get('script') or {}
                self.status = '准备中' + (' · ' + script['script'] if script else '')
                self.changed.emit()
                return
            if self.group:
                from ..runtime import groups
                self.group_data = groups.status(self.project, self.group)
                self.members = self.group_data['members']
            if not self.session: return
            self.data = sessions.read(self.project, self.session)
            state = self.data['state']
            role = next((m['role'] for m in self.members if m.get('session') == self.session), '')
            self.status = self.backend.label + ' · ' + role + ' · ' + ('世界已就绪' if state == 'running' and self.data.get('world_ready') else state) + ' · ' + self.session[:8]
            if self.group:
                if self.group_data['state'] != 'ready' and self.watcher and not self.busy:
                    self.set_watching(False)
                self.changed.emit()
                return
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
            self.watcher = None
            if self.group:
                self.poll()
            else:
                self._end_session()
            self.stopped.emit(result)
        return self.run_task(perform, finished)

    def interrupt_group(self):
        if not self.group or not self.available:
            return False
        from ..runtime import groups
        group, owned, watcher = self.group, tuple(self.owned_sessions), self.watcher
        def perform():
            if watcher:
                watcher.stop()
            groups.stop_owned(self.project, group, owned)
        def finished(_):
            self.watcher = None
            self.poll()
        return self.run_task(perform, finished, report=False)

    def restart(self):
        if not self.session or not self.available: return False
        session, watcher = self.session, self.watcher
        def perform():
            if watcher: watcher.stop()
            if self.group:
                from ..runtime import groups
                return groups.restart(self.project, session=session)
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
        from ..runtime.targets import changed_reload_targets
        from ..mcstudio.hot_reload import reload_session
        session = self.session
        def perform():
            targets = changed_reload_targets(self.project, [str(filename)])
            if not targets: raise ValueError('此文件不能直接热更，请重新部署并重载世界。')
            (kind, target), _ = next(iter(targets.items()))
            if self.group:
                from ..runtime import groups
                return groups.reload(self.project, self.group, kind, target,
                    source=Path(filename).read_bytes() if kind == 'python' else None, side=side)
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
        self.watcher = SessionWatcher(self.project, None if self.group else self.session,
                                      self.watch_message.emit, sides=sides, group=self.group)
        def failed(): self.watcher = None
        return self.run_task(self.watcher.start, failure=failed, report=False)

    def dispose(self):
        if self.busy or self.watcher:
            raise RuntimeError('请先完成当前操作并停止监控')
        self.timer.stop(); self.logs.finish()

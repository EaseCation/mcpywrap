"""Small presentation components; all actions are dispatched by SessionController."""
from pathlib import Path
from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox,
                              QComboBox, QPlainTextEdit, QLineEdit, QFileDialog, QInputDialog, QLabel)
from .log_view import LogView

ROLE_LABELS = {'host': '主机·玩家 1', 'guest': '客户端 2', 'client1': '客户端 1', 'client2': '客户端 2'}


def select_reload_file(controller, parent, side=None):
    path, _ = QFileDialog.getOpenFileName(parent, '选择要热更的文件', controller.project,
                                         'Python 模块 (*.py)' if controller.group else
                                         '开发文件 (*.py *.json *.material *.vertex *.fragment)')
    if not path: return
    if side is None and Path(path).suffix == '.py':
        choices = ['client', 'server', 'both'] if controller.group else ['client', 'server']
        side, accepted = QInputDialog.getItem(parent, '热更端侧',
            '联调组 client 更新两名玩家；server 只更新主机服务端。' if controller.group else '模块在哪一端运行？', choices, 0, False)
        if not accepted: return
    controller.reload_file(path, side or 'client')


class SessionControls(QWidget):
    def __init__(self, controller, parent=None, compact=False):
        super().__init__(parent)
        self.controller = controller
        layout = QVBoxLayout(self)
        self.group_panel = QWidget()
        group_row = QVBoxLayout(self.group_panel) if compact else QHBoxLayout(self.group_panel)
        self.member = QComboBox()
        self.member.setToolTip('Python、输入和截图的当前目标')
        self.member.currentIndexChanged.connect(self.select_member)
        self.group_status = QLabel()
        self.all_logs = QCheckBox('合并日志')
        self.all_logs.toggled.connect(controller.set_all_logs)
        self.group_restart = QPushButton('重启联调组')
        self.group_stop = QPushButton('停止联调组')
        self.group_restart.clicked.connect(lambda: controller.group_action('restart'))
        self.group_stop.clicked.connect(lambda: controller.group_action('stop'))
        for widget in (self.member, self.group_status, self.all_logs, self.group_restart, self.group_stop):
            group_row.addWidget(widget)
        layout.addWidget(self.group_panel)
        row = QVBoxLayout() if compact else QHBoxLayout()
        layout.addLayout(row)
        row.setContentsMargins(6, 6, 6, 6) if compact else row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.reload_btn = QPushButton('热更文件…')
        self.reload_btn.setToolTip('更新已加载模块；注册逻辑或资源结构变化请重载世界')
        self.restart_btn = QPushButton('重载世界')
        self.restart_btn.setToolTip('停止游戏、重新部署 Mod，再打开同一世界；重要进度请先在游戏内保存')
        self.stop_btn = QPushButton('停止游戏')
        self.watch = QCheckBox('自动热更')
        self.side = QComboBox(); self.side.addItems(['client', 'server', 'both'])
        self.side.setToolTip('监控端侧；both 仅适合可以安全重复执行的公共模块')
        for widget in (self.reload_btn, self.restart_btn, self.stop_btn, self.watch, self.side): row.addWidget(widget)
        self.reload_btn.clicked.connect(lambda: select_reload_file(controller, self))
        self.restart_btn.clicked.connect(controller.restart); self.stop_btn.clicked.connect(controller.stop)
        self.watch.toggled.connect(self.toggle_watch); self.side.currentTextChanged.connect(controller.set_watch_side)
        controller.changed.connect(self.refresh); self.refresh()

    @Slot(int)
    def select_member(self, index):
        value = self.member.itemData(index)
        if value:
            self.controller.select_member(value)

    @Slot(bool)
    def toggle_watch(self, enabled):
        self.controller.set_watching(enabled); self.refresh()

    @Slot()
    def refresh(self):
        c = self.controller
        self.group_panel.setVisible(bool(c.group))
        self.member.blockSignals(True)
        self.member.clear()
        states = {'waiting_for_join': '等待点击卡片加入', 'verified': '已确认加入',
                  'wrong_world': '未加入指定主机', 'host_disconnected': '与主机失联'}
        for member in c.members:
            state = member.get('connection_state', member.get('state', 'pending'))
            label = ROLE_LABELS.get(member['role'], member['role'])
            if member.get('player_name'):
                label += ' · ' + member['player_name']
            self.member.addItem(label + ' · ' + states.get(state, state), member.get('session'))
        selected = self.member.findData(c.session)
        if selected >= 0: self.member.setCurrentIndex(selected)
        self.member.blockSignals(False)
        self.member.setEnabled(c.available)
        self.group_status.setWordWrap(True)
        self.group_status.setText('两名玩家已确认加入' if c.group_data.get('connection_verified') else
                                 '联调组已停止' if c.group_data.get('state') == 'exited' else
                                 c.group_data.get('hint') or '连接或成员尚未全部确认')
        self.group_restart.setEnabled(c.available); self.group_stop.setEnabled(c.available)
        selected_member = next((m for m in c.members if m.get('session') == c.session), {})
        self.restart_btn.setText('重试客户端' if c.group and selected_member.get('role') != 'host' else '重载世界')
        self.stop_btn.setText('停止客户端' if c.group and selected_member.get('role') != 'host' else '停止游戏')
        active = bool(c.session) and c.available
        running = active and c.data.get('state') == 'running'
        local = c.group_data.get('kind') == 'local' if c.group else c.data.get('mode', 'local') == 'local'
        ready = not c.group or c.group_data.get('connection_verified', False)
        self.reload_btn.setEnabled(running and local and ready)
        self.reload_btn.setText('热更 Python…' if c.group else '热更文件…')
        host_with_guest = selected_member.get('role') == 'host' and any(
            m.get('role') == 'guest' and m.get('state') in ('starting', 'running') for m in c.members)
        self.restart_btn.setEnabled(active and not host_with_guest)
        self.stop_btn.setEnabled(active and not host_with_guest and (c.data.get('state') in ('starting', 'running') or bool(c.data.get('game'))))
        self.stop_btn.setToolTip('主机仍有客机，请使用停止联调组' if host_with_guest else '')
        self.watch.setEnabled(running and local and ready and 'watch' in c.backend.capabilities)
        self.watch.blockSignals(True); self.watch.setChecked(c.watcher is not None); self.watch.blockSignals(False)
        self.side.blockSignals(True); self.side.setCurrentText(c.watch_side); self.side.blockSignals(False)
        self.side.setEnabled(not c.watcher and c.available)


class PythonConsole(QWidget):
    submitted = Signal()

    def __init__(self, controller, compact=False, parent=None):
        super().__init__(parent)
        self.controller = controller
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.target_label = QLabel()
        self.target_label.setWordWrap(True)
        layout.addWidget(self.target_label)
        self.code = QLineEdit() if compact else QPlainTextEdit()
        self.code.setPlaceholderText("print('hello from game')")
        layout.addWidget(self.code)
        row = QHBoxLayout(); self.side = QComboBox(); self.side.addItems(['client', 'server'])
        self.send = QPushButton('执行 Python'); self.reload = QPushButton('热更文件…')
        for widget in (self.side, self.send, self.reload): row.addWidget(widget)
        layout.addLayout(row)
        self.send.clicked.connect(self.execute)
        self.reload.clicked.connect(lambda: select_reload_file(controller, self, self.side.currentText()))
        if compact: self.code.returnPressed.connect(self.execute)
        self.output = LogView(controller.logs, source='operations', toolbar=False)
        self.output.setMinimumHeight(90); layout.addWidget(self.output)
        controller.changed.connect(self.refresh); self.refresh()

    @Slot()
    def execute(self):
        source = self.code.text() if isinstance(self.code, QLineEdit) else self.code.toPlainText()
        if self.controller.execute(source, self.side.currentText()): self.submitted.emit()

    @Slot()
    def refresh(self):
        active = (bool(self.controller.session) and self.controller.available and
                  self.controller.data.get('state') == 'running' and self.controller.data.get('world_ready', True))
        member = next((m for m in self.controller.members if m.get('session') == self.controller.session), {})
        target = ROLE_LABELS.get(member.get('role'), '')
        self.target_label.setText('当前目标：' + ' · '.join(filter(None, (target, self.controller.session or '未选择'))))
        server_enabled = self.controller.data.get('mode') != 'network'
        self.side.model().item(1).setEnabled(server_enabled)
        if not server_enabled and self.side.currentText() == 'server': self.side.setCurrentText('client')
        self.send.setEnabled(active)
        # Group reload is an explicit action in SessionControls, never a side
        # effect of the console whose target is one selected member.
        self.reload.setVisible(not bool(self.controller.group))
        self.reload.setEnabled(active and self.controller.data.get('mode') == 'local')

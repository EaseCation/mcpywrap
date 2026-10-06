"""Small presentation components; all actions are dispatched by SessionController."""
from pathlib import Path
from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox,
                              QComboBox, QPlainTextEdit, QLineEdit, QFileDialog, QInputDialog)
from .log_view import LogView


def select_reload_file(controller, parent, side=None):
    path, _ = QFileDialog.getOpenFileName(parent, '选择要热更的文件', controller.project,
                                         '开发文件 (*.py *.json *.material *.vertex *.fragment)')
    if not path: return
    if side is None and Path(path).suffix == '.py':
        side, accepted = QInputDialog.getItem(parent, '热更端侧', '模块在哪一端运行？', ['client', 'server'], 0, False)
        if not accepted: return
    controller.reload_file(path, side or 'client')


class SessionControls(QWidget):
    def __init__(self, controller, parent=None, compact=False):
        super().__init__(parent)
        self.controller = controller
        row = QVBoxLayout(self) if compact else QHBoxLayout(self)
        row.setContentsMargins(6, 6, 6, 6) if compact else row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.reload_btn = QPushButton('热更文件…')
        self.reload_btn.setToolTip('更新已加载模块；注册逻辑或资源结构变化请重载世界')
        self.restart_btn = QPushButton('重载世界')
        self.restart_btn.setToolTip('保存退出、重新部署 Mod，再打开同一世界')
        self.stop_btn = QPushButton('保存退出')
        self.watch = QCheckBox('自动热更')
        self.side = QComboBox(); self.side.addItems(['client', 'server', 'both'])
        self.side.setToolTip('监控端侧；both 仅适合可以安全重复执行的公共模块')
        for widget in (self.reload_btn, self.restart_btn, self.stop_btn, self.watch, self.side): row.addWidget(widget)
        self.reload_btn.clicked.connect(lambda: select_reload_file(controller, self))
        self.restart_btn.clicked.connect(controller.restart); self.stop_btn.clicked.connect(controller.stop)
        self.watch.toggled.connect(self.toggle_watch); self.side.currentTextChanged.connect(controller.set_watch_side)
        controller.changed.connect(self.refresh); self.refresh()

    @Slot(bool)
    def toggle_watch(self, enabled):
        self.controller.set_watching(enabled); self.refresh()

    @Slot()
    def refresh(self):
        c = self.controller
        active = bool(c.session) and c.available
        for button in (self.reload_btn, self.restart_btn, self.stop_btn): button.setEnabled(active)
        self.watch.setEnabled(active and 'watch' in c.backend.capabilities)
        self.watch.blockSignals(True); self.watch.setChecked(c.watcher is not None); self.watch.blockSignals(False)
        self.side.blockSignals(True); self.side.setCurrentText(c.watch_side); self.side.blockSignals(False)
        self.side.setEnabled(not c.watcher and c.available)


class PythonConsole(QWidget):
    submitted = Signal()

    def __init__(self, controller, compact=False, parent=None):
        super().__init__(parent)
        self.controller = controller
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
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
        active = bool(self.controller.session) and self.controller.available
        self.send.setEnabled(active); self.reload.setEnabled(active)

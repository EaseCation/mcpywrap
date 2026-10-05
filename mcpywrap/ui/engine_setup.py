"""Qt installation dialog using the same engine service as CLI/TUI."""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                            QPushButton, QFileDialog, QProgressBar, QWidget, QToolButton)
from PySide6.QtCore import Slot, QTimer, Qt
from .session_tools import TaskThread


class EngineSetupDialog(QDialog):
    def __init__(self, backend, parent=None, auto_install=False):
        super().__init__(parent)
        self.backend, self.task = backend, None
        self.auto_install, self.ready = auto_install, False
        self.setWindowTitle('准备本地运行环境')
        self.resize(520, 240)
        layout = QVBoxLayout(self)
        description = QLabel(backend.setup_description); description.setWordWrap(True)
        layout.addWidget(description)
        self.advanced_button = QToolButton()
        self.advanced_button.setText('高级安装选项')
        self.advanced_button.setCheckable(True)
        self.advanced_button.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        layout.addWidget(self.advanced_button)
        self.advanced = QWidget()
        advanced_layout = QVBoxLayout(self.advanced); advanced_layout.setContentsMargins(0, 0, 0, 0)
        self.catalog = QLineEdit(); self.catalog.setPlaceholderText('可选：自定义发布目录；留空使用默认来源')
        advanced_layout.addWidget(self.catalog)
        self.apk = QLineEdit(); self.apk.setPlaceholderText('开发者 APK 路径；留空从网易下载匹配版本')
        row = QHBoxLayout(); row.addWidget(self.apk)
        browse = QPushButton('选择 APK'); browse.clicked.connect(self.browse_apk); row.addWidget(browse)
        advanced_layout.addLayout(row)
        layout.addWidget(self.advanced); self.advanced.hide()
        self.advanced_button.toggled.connect(self.show_advanced)
        self.progress = QProgressBar(); self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.status = QLabel('首次安装需要下载并提取资源；已有世界不会被删除。'); self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.install_button = QPushButton('安装／修复'); self.install_button.clicked.connect(self.install)
        layout.addWidget(self.install_button)
        self.done_button = QPushButton('关闭'); self.done_button.clicked.connect(self.accept); layout.addWidget(self.done_button)
        if auto_install: QTimer.singleShot(0, self.install)

    def show_advanced(self, expanded):
        self.advanced.setVisible(expanded)
        self.advanced_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.adjustSize()

    def browse_apk(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择开发者 APK', '', 'Android APK (*.apk)')
        if path: self.apk.setText(path)

    def install(self):
        if self.task and self.task.isRunning(): return
        location, apk = self.catalog.text().strip() or None, self.apk.text().strip() or None
        # A single install is serialized by the engine service. No game/GUI-specific downloader.
        self.task = TaskThread(lambda: self.backend.install(location, apk, self.update_progress), self)
        self.task.progress.connect(self.show_progress)
        self.task.result.connect(self.show_result)
        self.task.failed.connect(self.status.setText)
        self.task.finished.connect(self.install_finished)
        self.ready = False
        self.install_button.setEnabled(False); self.advanced.setEnabled(False)
        self.status.setText('正在自动下载并准备游戏环境…')
        self.task.start()

    @Slot(int, int)
    def show_progress(self, done, total):
        self.progress.setValue(done * 100 // max(1, total))

    @Slot(object)
    def show_result(self, result):
        self.ready = bool(result.get('ok'))
        self.status.setText('资源已就绪。' if self.ready else str(result))

    @Slot()
    def install_finished(self):
        self.install_button.setEnabled(True); self.advanced.setEnabled(True)
        if self.ready and self.auto_install: self.accept()

    def update_progress(self, done, total):
        # Qt int is 32-bit; report KiB for multi-GB APKs.
        self.task.progress.emit(done // 1024, max(1, total // 1024))

    def closeEvent(self, event):
        if self.task and self.task.isRunning():
            self.status.setText('安装仍在进行，请等待完成；下载中断后可以续传。')
            event.ignore()
        else: super().closeEvent(event)

    def done(self, result):
        if self.task and self.task.isRunning():
            self.status.setText('请等待安装结束后关闭。')
            return
        super().done(result)

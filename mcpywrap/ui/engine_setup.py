"""Qt installation dialog using the same engine service as CLI/TUI."""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                            QPushButton, QFileDialog, QProgressBar)
from PySide6.QtCore import Slot
from .session_tools import TaskThread


class EngineSetupDialog(QDialog):
    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend, self.task = backend, None
        self.setWindowTitle('准备本地运行环境')
        self.resize(620, 330)
        layout = QVBoxLayout(self)
        description = QLabel(backend.setup_description); description.setWordWrap(True)
        layout.addWidget(description)
        self.catalog = QLineEdit(); self.catalog.setPlaceholderText('发行目录 catalog.json 的 HTTPS 地址或本地路径；留空复用当前配置')
        layout.addWidget(self.catalog)
        self.apk = QLineEdit(); self.apk.setPlaceholderText('开发者 APK 路径；留空从网易下载匹配版本')
        row = QHBoxLayout(); row.addWidget(self.apk)
        browse = QPushButton('选择 APK'); browse.clicked.connect(self.browse_apk); row.addWidget(browse)
        layout.addLayout(row)
        self.progress = QProgressBar(); self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.status = QLabel('首次安装需要下载并提取资源；已有世界不会被删除。'); self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.install_button = QPushButton('安装／修复'); self.install_button.clicked.connect(self.install)
        layout.addWidget(self.install_button)
        self.done_button = QPushButton('关闭'); self.done_button.clicked.connect(self.accept); layout.addWidget(self.done_button)

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
        self.install_button.setEnabled(False); self.status.setText('正在校验、下载并组装…')
        self.task.start()

    @Slot(int, int)
    def show_progress(self, done, total):
        self.progress.setValue(done * 100 // max(1, total))

    @Slot(object)
    def show_result(self, result):
        self.status.setText('资源已就绪。关闭此窗口后即可启动实例。' if result.get('ok') else str(result))

    @Slot()
    def install_finished(self):
        self.install_button.setEnabled(True)

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

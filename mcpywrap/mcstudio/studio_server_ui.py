"""Legacy TCP entry point; the renderer/window are shared with managed sessions.

New Windows/macOS sessions use SessionLogWindow and never instantiate this
transport. Kept for explicit --port usage and older direct-launch callers.
"""
import argparse
import subprocess
import sys
import signal
import atexit
import threading
import click
from PySide6.QtCore import Slot, QTimer
from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout, QPushButton, QComboBox
from .studio_server import StudioLogServer
from ..ui.log_view import LogBuffer
from ..ui.log_window import LogWindow

def set_windows_dark_titlebar(hwnd):
    """为 Windows 10/11 窗口设置深色标题栏"""
    if sys.platform != 'win32':
        return False
    from ctypes import windll, c_int, c_void_p, c_uint, byref, sizeof
    try:
        set_attribute = windll.dwmapi.DwmSetWindowAttribute
        set_attribute.argtypes = [c_void_p, c_uint, c_void_p, c_uint]
        set_attribute.restype = c_int
        enabled = c_int(1)
        return any(set_attribute(hwnd, attribute, byref(enabled), sizeof(enabled)) == 0
                   for attribute in (20, 19))
    except (AttributeError, OSError):
        return False


class StudioLoggerUI(LogWindow):
    def __init__(self, host='0.0.0.0', port=8000):
        model = LogBuffer()
        controls = QWidget(); row = QHBoxLayout(controls); row.setContentsMargins(0, 0, 0, 0)
        super().__init__(model, controls, title='MC Studio 日志控制台')
        self.model = model
        self.log_server = StudioLogServer(host, port)
        for label, command in [('热更行为包', 'reload_pack'), ('重载存档', 'restart_local_game')]:
            button = QPushButton(label); row.addWidget(button)
            button.clicked.connect(lambda checked=False, command=command: self.log_server.broadcast_command(command))
        self.command = QComboBox(); self.command.setEditable(True)
        self.command.lineEdit().setPlaceholderText('旧版 Studio 命令，回车发送')
        self.command.lineEdit().returnPressed.connect(self.send_input_command)
        row.addWidget(self.command)
        self.log_server.log_received_signal.connect(self.receive)
        self.log_server.client_connected_signal.connect(self.connected)
        self.log_server.client_disconnected_signal.connect(self.disconnected)
        self.server_thread = threading.Thread(target=self.log_server.start, daemon=True)
        self.server_thread.start()
        self.status_label.setText('等待 Studio 日志连接')

    @Slot(str, list)
    def receive(self, text, segments):
        self.model.append('game', text)

    @Slot()
    def connected(self): self.status_label.setText('已连接客户端')

    @Slot()
    def disconnected(self): self.status_label.setText('客户端已断开')

    @Slot()
    def send_input_command(self):
        text = self.command.currentText().strip()
        args = text.split()
        if args:
            self.log_server.broadcast_command(*args)
            if self.command.findText(text) < 0: self.command.addItem(text)
            self.command.setCurrentText('')

    def closeEvent(self, event):
        self.log_server.running = False
        self.log_server.shutdown()
        self.server_thread.join(timeout=1)
        super().closeEvent(event)


def run_studio_server_ui(host='0.0.0.0', port=8000):
    app = QApplication.instance() or QApplication(sys.argv)
    window = StudioLoggerUI(host, port); window.show()
    if sys.platform == 'win32': set_windows_dark_titlebar(int(window.winId()))
    signal.signal(signal.SIGINT, lambda *_: window.close())
    timer = QTimer(); timer.timeout.connect(lambda: None); timer.start(500)
    return app.exec()

def run_studio_server_ui_subprocess(host='0.0.0.0', port=8000):
    """以子进程方式启动UI，不阻塞主进程，并在主进程结束时自动退出"""
    studio_server_process = subprocess.Popen([
        sys.executable, "-c",
        f"from mcpywrap.mcstudio.studio_server_ui import run_studio_server_ui; run_studio_server_ui(host='{host}', port={port})"
    ])

    # 注册退出处理函数，确保主进程结束时清理子进程
    def cleanup_processes():
        if studio_server_process and studio_server_process.poll() is None:
            try:
                click.echo(click.style('💡 正在关闭日志服务器...', fg='cyan'))
                if sys.platform == 'win32':
                    studio_server_process.send_signal(signal.CTRL_C_EVENT)
                else:
                    studio_server_process.terminate()

                # 使用try-except处理等待过程中的中断
                try:
                    studio_server_process.wait(timeout=2)
                except (KeyboardInterrupt, subprocess.TimeoutExpired):
                    # 如果等待超时或被中断，强制结束进程
                    studio_server_process.kill()
            except Exception as e:
                print(f"关闭子进程时出错: {e}")

    atexit.register(cleanup_processes)

    return studio_server_process

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Legacy Studio TCP log viewer')
    parser.add_argument('-p', '--port', type=int, default=8000)
    parser.add_argument('-a', '--address', default='0.0.0.0')
    args = parser.parse_args()
    raise SystemExit(run_studio_server_ui(args.address, args.port))

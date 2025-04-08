# -*- coding: utf-8 -*-
import argparse
import subprocess
import sys
import os
import threading
import signal
import atexit
from ctypes import windll, c_int, byref, sizeof

import click
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QComboBox, QFrame, QStyleFactory,
    QCheckBox, QDesktopWidget
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, pyqtSlot, QSettings, QTimer
from PyQt5.QtGui import QFont, QPalette, QColor


def set_windows_dark_titlebar(hwnd):
    """为 Windows 10/11 窗口设置深色标题栏"""
    try:
        # Windows 10 1809+ 和 Windows 11 支持的 API
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20

        # 对于较早的 Windows 10 版本，使用旧的值
        if windll.ntdll.RtlGetVersion(byref(c_int())) < 0:  # 如果 RtlGetVersion 失败
            DWMWA_USE_IMMERSIVE_DARK_MODE = 19

        # 设置暗色模式
        windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            byref(c_int(1)),
            sizeof(c_int)
        )
        return True
    except Exception as e:
        print(f"设置暗色标题栏失败: {e}")
        return False

# 导入日志服务器类
from .studio_server import StudioLogServer

class TextRedirector(QObject):
    """重定向文本输出到UI"""
    text_updated = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.buffer = ""

    def write(self, text):
        # 过滤掉命令提示符
        if text.strip() == ">":
            return
        if text.strip().endswith(">"):
            text = text[:text.rfind(">")]
        
        self.buffer += text
        if '\n' in text or len(self.buffer) > 80:
            self.text_updated.emit(self.buffer)
            self.buffer = ""

    def flush(self):
        if self.buffer:
            self.text_updated.emit(self.buffer)
            self.buffer = ""

class StudioLoggerUI(QMainWindow):
    """MC Studio日志控制台UI"""

    def __init__(self, host='0.0.0.0', port=8000):
        super().__init__()

        # 应用设置
        self.settings = QSettings("MCPyWrap", "StudioLogger")

        # 窗口基本设置
        self.setWindowTitle("MC Studio 日志控制台")
        self.resize(300, 80)  # 默认展示一个小窗口
        self.setMinimumWidth(200)
        self.setMinimumHeight(80)

        # 日志区域默认隐藏状态
        self.log_expanded = False
        
        # 客户端连接状态
        self.client_connected = False

        # 创建UI组件
        self.setup_ui()

        # 应用暗黑模式
        self.apply_dark_theme()

        # 创建并启动日志服务器
        self.start_log_server(host, port)
        
        # 初始化按钮状态
        self.update_connection_status(False)
        
        # 默认设置窗口置顶
        self.set_always_on_top(True)
        self.stay_on_top_check.setChecked(True)
        
        # 设置窗口位置到屏幕左下角
        self.position_window_bottom_left()

    def setup_ui(self):
        """设置UI组件"""
        # 主窗口布局
        central_widget = QWidget()
        self.main_layout = QVBoxLayout(central_widget)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(8)

        # 创建上部操作区域
        control_frame = QFrame()
        control_layout = QHBoxLayout(control_frame)
        control_layout.setContentsMargins(0, 0, 0, 0)

        # 添加控制按钮
        self.reload_btn = QPushButton("热更行为包")
        self.reload_btn.clicked.connect(lambda: self.send_command("reload_pack"))
        self.reload_btn.setToolTip("执行热更新，重新加载行为包（资源包不支持热更）")

        self.restart_btn = QPushButton("重载存档")
        self.restart_btn.clicked.connect(lambda: self.send_command("restart_local_game"))
        self.restart_btn.setToolTip("重新进入世界")

        # 添加展开/收起按钮
        self.toggle_btn = QPushButton("展开日志")
        self.toggle_btn.clicked.connect(self.toggle_log_view)
        
        # 添加置顶勾选框
        self.stay_on_top_check = QCheckBox("置顶")
        self.stay_on_top_check.setToolTip("保持窗口在最上层")
        self.stay_on_top_check.stateChanged.connect(self.toggle_always_on_top)
        
        # 添加按钮和控件到控制布局
        control_layout.addWidget(self.reload_btn)
        control_layout.addWidget(self.restart_btn)
        control_layout.addWidget(self.toggle_btn)
        control_layout.addStretch(1)
        control_layout.addWidget(self.stay_on_top_check)

        # 创建日志区域容器
        self.log_container = QWidget()
        log_container_layout = QVBoxLayout(self.log_container)
        log_container_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建日志显示区域
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        font = QFont("Microsoft YaHei", 9)
        self.log_text.setFont(font)
        
        # 添加命令输入区域
        input_layout = QHBoxLayout()
        self.cmd_input = QComboBox()
        self.cmd_input.setEditable(True)
        self.cmd_input.setFont(font)
        self.cmd_input.setMinimumWidth(200)

        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self.send_input_command)

        input_layout.addWidget(QLabel("命令:"))
        input_layout.addWidget(self.cmd_input, 1)
        input_layout.addWidget(self.send_btn)

        # 将日志相关控件添加到日志容器
        log_container_layout.addWidget(self.log_text, 1)
        log_container_layout.addLayout(input_layout)
        
        # 状态显示栏
        self.status_label = QLabel("未连接客户端")

        # 将所有元素添加到主布局
        self.main_layout.addWidget(control_frame)
        self.main_layout.addWidget(self.log_container)
        self.main_layout.addWidget(self.status_label)

        # 默认隐藏日志区域
        self.log_container.setVisible(False)

        # 设置中心控件
        self.setCentralWidget(central_widget)

    def toggle_log_view(self):
        """切换日志区域的显示状态"""
        self.log_expanded = not self.log_expanded
        self.log_container.setVisible(self.log_expanded)

        # 调整窗口大小
        if self.log_expanded:
            self.toggle_btn.setText("收起日志")
            # 保存当前大小，以便展开前的窗口大小被记住
            if not hasattr(self, 'collapsed_size'):
                self.collapsed_size = self.size()

            def set_size():
                self.resize(800, 600)

            # 使用 QTimer 替代 timer.set_timer
            QTimer.singleShot(100, set_size)
        else:
            self.toggle_btn.setText("展开日志")

            # 使用 QTimer 替代 timer.set_timer
            def set_size():
                if hasattr(self, 'collapsed_size'):
                    self.resize(self.collapsed_size)
                else:
                    self.resize(500, 400)

            QTimer.singleShot(100, set_size)

    def update_connection_status(self, connected):
        """更新连接状态和UI按钮"""
        self.client_connected = connected
        
        # 更新状态文本
        if connected:
            self.status_label.setText("已连接客户端")
        else:
            self.status_label.setText("未连接客户端")
        
        # 更新按钮状态
        self.reload_btn.setEnabled(connected)
        self.restart_btn.setEnabled(connected)
        self.send_btn.setEnabled(connected)

    def start_log_server(self, host='0.0.0.0', port=8000):
        """启动日志服务器，并将输出重定向到UI"""
        self.redirector = TextRedirector()
        self.redirector.text_updated.connect(self.update_log)

        # 保存原始的stdout
        self.original_stdout = sys.stdout

        # 重定向标准输出到UI
        sys.stdout = self.redirector

        # 创建并启动服务器
        self.log_server = StudioLogServer(host, port)
        
        # 连接客户端连接/断开信号
        self.log_server.client_connected_signal.connect(self.on_client_connected)
        self.log_server.client_disconnected_signal.connect(self.on_client_disconnected)
        
        self.server_thread = threading.Thread(target=self.log_server.start)
        self.server_thread.daemon = True
        self.server_thread.start()

        self.status_label.setText("服务器运行中 - 未连接客户端")

    @pyqtSlot()
    def on_client_connected(self):
        """当客户端连接时调用"""
        self.update_connection_status(True)
    
    @pyqtSlot()
    def on_client_disconnected(self):
        """当客户端断开连接时调用"""
        self.update_connection_status(False)

    @pyqtSlot(str)
    def update_log(self, text):
        """更新日志文本显示"""
        self.log_text.moveCursor(self.log_text.textCursor().End)
        self.log_text.insertPlainText(text)
        self.log_text.ensureCursorVisible()

    def send_command(self, cmd, *args):
        """发送命令到所有客户端"""
        if hasattr(self, 'log_server'):
            self.log_server.broadcast_command(cmd, *args)

    def send_input_command(self):
        """发送用户输入的命令"""
        cmd_text = self.cmd_input.currentText().strip()
        if cmd_text:
            parts = cmd_text.split()
            cmd, args = parts[0], parts[1:] if len(parts) > 1 else []
            self.send_command(cmd, *args)

            # 添加到历史记录
            if self.cmd_input.findText(cmd_text) == -1:
                self.cmd_input.addItem(cmd_text)

            # 清空输入框
            self.cmd_input.setCurrentText("")

    def apply_dark_theme(self):
        """应用暗黑主题"""
        # 设置暗色主题
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Base, QColor(35, 35, 35))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.ToolTipBase, QColor(25, 25, 25))
        palette.setColor(QPalette.ToolTipText, Qt.white)
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        # 设置禁用状态颜色
        palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(127, 127, 127))
        palette.setColor(QPalette.Disabled, QPalette.Text, QColor(127, 127, 127))
        palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(127, 127, 127))
        palette.setColor(QPalette.Disabled, QPalette.Button, QColor(45, 45, 45))
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        QApplication.setPalette(palette)

        # 设置日志区域样式
        self.log_text.setStyleSheet("background-color: #232323; color: #E0E0E0;")

        # 设置按钮样式表
        button_style = """
        QPushButton {
            background-color: #444444;
            color: #FFFFFF;
            border: 1px solid #555555;
            padding: 5px;
            border-radius: 3px;
        }
        QPushButton:hover {
            background-color: #555555;
        }
        QPushButton:pressed {
            background-color: #333333;
        }
        QPushButton:disabled {
            background-color: #333333;
            color: #666666;
            border: 1px solid #444444;
        }
        """

        # 应用按钮样式
        self.reload_btn.setStyleSheet(button_style)
        self.restart_btn.setStyleSheet(button_style)
        self.toggle_btn.setStyleSheet(button_style)
        self.send_btn.setStyleSheet(button_style)

        # 设置输入框样式
        input_style = """
        QComboBox {
            background-color: #333333;
            color: #FFFFFF;
            border: 1px solid #555555;
            padding: 3px;
            border-radius: 3px;
        }
        QComboBox:disabled {
            background-color: #2A2A2A;
            color: #666666;
            border: 1px solid #444444;
        }
        QComboBox QAbstractItemView {
            background-color: #333333;
            color: #FFFFFF;
            selection-background-color: #444444;
        }
        """
        self.cmd_input.setStyleSheet(input_style)

        # 设置 Windows 暗色标题栏
        if sys.platform == "win32":
            set_windows_dark_titlebar(int(self.winId()))

    def toggle_always_on_top(self, state):
        """切换窗口置顶状态"""
        is_on_top = state == Qt.Checked
        self.set_always_on_top(is_on_top)
        # 保存用户偏好
        self.settings.setValue("always_on_top", is_on_top)
        
    def set_always_on_top(self, on_top):
        """设置窗口是否置顶"""
        if on_top:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
        self.show()  # 重新显示窗口以应用更改

    def closeEvent(self, event):
        """窗口关闭时的处理"""
        # 恢复标准输出
        sys.stdout = self.original_stdout

        # 关闭服务器
        if hasattr(self, 'log_server'):
            self.log_server.running = False
            self.log_server.shutdown()

        # 保存置顶设置和窗口位置
        self.settings.setValue("always_on_top", self.stay_on_top_check.isChecked())
        self.settings.setValue("window_position_x", self.x())
        self.settings.setValue("window_position_y", self.y())
        
        # 保存设置
        self.settings.sync()

        super().closeEvent(event)
        
    def showEvent(self, event):
        """窗口显示事件"""
        super().showEvent(event)
        
        # 从设置中加载置顶状态
        always_on_top = self.settings.value("always_on_top", True, type=bool)
        if self.stay_on_top_check.isChecked() != always_on_top:
            self.stay_on_top_check.setChecked(always_on_top)
        
        # 如果是第一次显示，初始化置顶状态和位置
        if not hasattr(self, '_shown'):
            self.set_always_on_top(always_on_top)
            
            # 加载保存的位置或使用默认的左下角位置
            saved_x = self.settings.value("window_position_x", None)
            saved_y = self.settings.value("window_position_y", None)
            
            # 如果有保存的位置则使用，否则使用左下角位置
            if saved_x is not None and saved_y is not None:
                self.move(int(saved_x), int(saved_y))
            else:
                self.position_window_bottom_left()
                
            self._shown = True

    def position_window_bottom_left(self):
        """将窗口定位到屏幕左下角，保留边距"""
        # 获取可用屏幕几何信息
        desktop = QDesktopWidget().availableGeometry()
        
        # 设置边距（像素）
        margin = 20
        
        # 计算左下角位置
        x = desktop.left() + margin
        y = desktop.bottom() - self.height() - margin
        
        # 移动窗口
        self.move(x, y)
        
        # 保存初始位置信息
        self.settings.setValue("window_position_x", x)
        self.settings.setValue("window_position_y", y)

def run_studio_server_ui(host='0.0.0.0', port=8000):
    """主函数"""
    # 设置高DPI缩放
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))  # 使用Fusion风格，更现代一致

    window = StudioLoggerUI(host=host, port=port)
    window.show()

    # 窗口显示后再次设置暗色标题栏，确保生效
    if sys.platform == "win32":
        set_windows_dark_titlebar(int(window.winId()))

    # 处理Ctrl+C信号
    def signal_handler(sig, frame):
        print("捕获Ctrl+C，正在安全退出...")
        window.close()  # 触发窗口的closeEvent以确保资源被正确清理
        app.quit()      # 退出应用程序

    # 在主线程中注册信号处理程序
    signal.signal(signal.SIGINT, signal_handler)

    # 使用timer允许Python解释器处理信号
    timer = app.startTimer(500)

    # 正确定义timerEvent处理函数，接收event参数
    def process_signals(event):
        pass

    app.timerEvent = process_signals

    sys.exit(app.exec_())

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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Minecraft Studio 调试日志服务器')
    parser.add_argument('-p', '--port', type=int, default=8000,
                        help='服务器监听端口 (默认: 8000)')
    parser.add_argument('-a', '--address', default='0.0.0.0',
                        help='服务器监听地址 (默认: 0.0.0.0)')

    args = parser.parse_args()
    run_studio_server_ui(args.address, args.port)


# -*- coding: utf-8 -*-

"""
游戏实例管理图形界面
"""

import os
import sys
import time
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QTableWidget, QTableWidgetItem, QPushButton, QLabel, QHeaderView, 
    QMessageBox, QSplitter, QTextEdit, QProgressBar, QFrame,
    QStyleFactory, QStatusBar, QCheckBox, QFileDialog, QGroupBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QIcon, QFont, QTextCursor, QColor, QPalette

# 导入项目模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from mcpywrap.commands.run_cmd import (
    _get_all_instances, _get_latest_instance, _match_instance_by_prefix,
    _generate_new_instance_config, _setup_dependencies, _run_game_with_instance,
    _delete_instance, _clean_all_instances, get_project_name, config_exists,
    Console, base_dir as default_base_dir
)


class GameInstanceManager(QMainWindow):
    """游戏实例管理器主窗口"""
    
    def __init__(self, base_dir):
        super().__init__()
        self.base_dir = base_dir
        self.current_project = get_project_name() if config_exists() else "未初始化项目"
        self.instances = []
        self.all_packs = None
        self.setup_ui()
        self.init_data()

    def setup_global_font(self):
        """设置全局字体为现代化中文字体"""
        # 设置优先使用的字体：微软雅黑、苹方、思源黑体等现代中文字体
        font = QFont("Microsoft YaHei, PingFang SC, Hiragino Sans GB, Source Han Sans CN, WenQuanYi Micro Hei, SimHei, sans-serif", 9)
        QApplication.setFont(font)
        
    def setup_ui(self):
        """设置UI界面"""
        self.setWindowTitle(f"Minecraft游戏实例管理器 - {self.current_project}")
        self.setMinimumSize(800, 600)
        self.resize(1000, 700)
        self.setWindowIcon(QIcon())

        self.setup_global_font()
        
        # 主布局
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        self.setCentralWidget(main_widget)
        
        # 项目信息区域
        info_frame = QFrame()
        info_frame.setFrameShape(QFrame.StyledPanel)
        info_layout = QHBoxLayout(info_frame)
        
        # 项目名称和路径
        project_info = QLabel(f"<b>项目:</b> {self.current_project} | <b>路径:</b> {self.base_dir}")
        info_layout.addWidget(project_info)
        
        # 快速操作按钮
        refresh_btn = QPushButton("刷新")
        refresh_btn.setToolTip("刷新实例列表")
        refresh_btn.clicked.connect(self.refresh_instances)
        info_layout.addWidget(refresh_btn)
        
        main_layout.addWidget(info_frame)
        
        # 创建分割器
        splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(splitter)
        
        # 实例列表区域
        instance_widget = QWidget()
        instance_layout = QVBoxLayout(instance_widget)
        instance_layout.setContentsMargins(0, 0, 0, 0)
        
        # 实例列表标题
        instance_title = QLabel("<h3>游戏实例列表</h3>")
        instance_layout.addWidget(instance_title)
        
        # 实例列表表格
        self.instance_table = QTableWidget(0, 4)
        self.instance_table.setHorizontalHeaderLabels(["状态", "实例ID", "创建时间", "世界名称"])
        self.instance_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.instance_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.instance_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.instance_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.instance_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.instance_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.instance_table.setAlternatingRowColors(True)
        self.instance_table.itemDoubleClicked.connect(self.on_instance_double_clicked)
        self.instance_table.setStyleSheet("QTableView::item:selected { background-color: #e0f0ff; color: black; }")
        instance_layout.addWidget(self.instance_table)
        
        # 实例操作按钮
        btn_layout = QHBoxLayout()
        
        self.new_btn = QPushButton("新建实例")
        self.new_btn.clicked.connect(self.create_new_instance)
        btn_layout.addWidget(self.new_btn)
        
        self.run_btn = QPushButton("启动选中实例")
        self.run_btn.clicked.connect(self.run_selected_instance)
        self.run_btn.setEnabled(False)
        btn_layout.addWidget(self.run_btn)
        
        self.delete_btn = QPushButton("删除选中实例")
        self.delete_btn.clicked.connect(self.delete_selected_instance)
        self.delete_btn.setEnabled(False)
        btn_layout.addWidget(self.delete_btn)
        
        self.clean_btn = QPushButton("清空所有实例")
        self.clean_btn.clicked.connect(self.clean_all_instances)
        btn_layout.addWidget(self.clean_btn)
        
        instance_layout.addLayout(btn_layout)
        
        # 添加实例部分到分割器
        splitter.addWidget(instance_widget)
        
        # 日志输出区域
        log_frame = QFrame()
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(0, 0, 0, 0)
        
        log_title = QLabel("<h3>操作日志</h3>")
        log_layout.addWidget(log_title)
        
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        log_layout.addWidget(self.log_output)
        
        # 添加日志部分到分割器
        splitter.addWidget(log_frame)
        
        # 设置分割器初始大小
        splitter.setSizes([400, 200])
        
        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")
        
        # 连接选择变更信号
        self.instance_table.itemSelectionChanged.connect(self.on_selection_changed)
    
    def init_data(self):
        """初始化数据"""
        if not config_exists():
            self.log("❌ 项目尚未初始化，请先运行 mcpy init", "error")
            self.new_btn.setEnabled(False)
            self.clean_btn.setEnabled(False)
            return
        
        # 设置项目依赖
        self.log("📦 正在加载项目依赖...")
        self.all_packs = _setup_dependencies(self.current_project, self.base_dir)
        
        # 加载实例列表
        self.refresh_instances()
    
    def refresh_instances(self):
        """刷新实例列表"""
        self.instances = _get_all_instances()
        self.instance_table.setRowCount(0)
        
        if not self.instances:
            self.log("📭 没有找到任何游戏实例", "info")
            self.run_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            return
        
        self.instance_table.setRowCount(len(self.instances))
        for row, instance in enumerate(self.instances):
            # 状态图标
            status_item = QTableWidgetItem("📌" if row == 0 else "")
            status_item.setTextAlignment(Qt.AlignCenter)
            
            # 实例ID(显示前8位)
            id_item = QTableWidgetItem(instance['level_id'][:8])
            
            # 创建时间
            creation_time = datetime.fromtimestamp(instance['creation_time'])
            time_str = creation_time.strftime('%Y-%m-%d %H:%M:%S')
            time_item = QTableWidgetItem(time_str)
            
            # 世界名称
            name_item = QTableWidgetItem(instance['name'])
            
            # 设置表格内容
            self.instance_table.setItem(row, 0, status_item)
            self.instance_table.setItem(row, 1, id_item)
            self.instance_table.setItem(row, 2, time_item)
            self.instance_table.setItem(row, 3, name_item)
            
            # 设置行背景色
            if row == 0:  # 最新实例
                for col in range(4):
                    self.instance_table.item(row, col).setBackground(QColor("#e0ffe0"))
        
        self.instance_table.selectRow(0)  # 默认选择第一行
        self.log(f"✅ 已加载 {len(self.instances)} 个游戏实例", "success")
    
    def on_selection_changed(self):
        """选择变更事件处理"""
        selected_rows = self.instance_table.selectionModel().selectedRows()
        has_selection = len(selected_rows) > 0
        self.run_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)
    
    def on_instance_double_clicked(self, item):
        """双击实例表格项事件处理"""
        self.run_selected_instance()
    
    def create_new_instance(self):
        """创建新的游戏实例"""
        if not self.all_packs:
            self.log("❌ 无法创建实例，项目依赖加载失败", "error")
            return
        
        self.log("🆕 正在创建新的游戏实例...")
        
        # 生成新的实例配置
        level_id, config_path = _generate_new_instance_config(self.base_dir, self.current_project)
        
        # 运行游戏实例
        self.log(f"📝 配置文件已生成: {os.path.basename(config_path)}")
        self.log(f"🚀 正在启动游戏实例: {level_id[:8]}...")
        
        # 使用QThread启动游戏，避免UI卡死
        self.game_thread = GameRunThread(config_path, level_id, self.all_packs)
        self.game_thread.log_message.connect(self.log)
        self.game_thread.finished.connect(self.on_game_finished)
        self.game_thread.start()
        
        self.disable_ui_during_game()
    
    def run_selected_instance(self):
        """运行选中的游戏实例"""
        if not self.all_packs:
            self.log("❌ 无法运行实例，项目依赖加载失败", "error")
            return
            
        selected_rows = self.instance_table.selectionModel().selectedRows()
        if not selected_rows:
            return
            
        # 获取选中的行
        row = selected_rows[0].row()
        level_id = self.instances[row]['level_id']
        config_path = self.instances[row]['config_path']
        
        self.log(f"🚀 正在启动游戏实例: {level_id[:8]}...")
        
        # 使用QThread启动游戏，避免UI卡死
        self.game_thread = GameRunThread(config_path, level_id, self.all_packs)
        self.game_thread.log_message.connect(self.log)
        self.game_thread.start()
    
    def delete_selected_instance(self):
        """删除选中的游戏实例"""
        selected_rows = self.instance_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        
        # 获取选中的行
        row = selected_rows[0].row()
        instance = self.instances[row]
        level_id = instance['level_id']
        
        # 确认删除
        reply = QMessageBox.question(
            self, 
            "确认删除", 
            f"确定要删除实例 {level_id[:8]} ({instance['name']}) 吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.log(f"🗑️ 正在删除实例: {level_id[:8]}...")
            force = True  # 使用强制模式避免在函数内部显示确认对话框
            _delete_instance(level_id[:8], force)
            self.log(f"✅ 成功删除实例: {level_id[:8]}", "success")
            self.refresh_instances()
    
    def clean_all_instances(self):
        """清空所有游戏实例"""
        if not self.instances:
            self.log("📭 没有找到任何游戏实例", "info")
            return
        
        # 二次确认
        reply = QMessageBox.warning(
            self,
            "警告",
            f"确定要删除所有 {len(self.instances)} 个游戏实例吗？\n此操作将删除所有实例配置及对应的游戏存档，且不可恢复!",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 最终确认
            reply = QMessageBox.critical(
                self,
                "最终确认",
                "⚠️ 最后确认: 真的要删除所有实例吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.log("🗑️ 正在清空所有游戏实例...")
                _clean_all_instances(True)  # 使用强制模式
                self.log("✅ 已成功清空所有游戏实例", "success")
                self.refresh_instances()
    
    def log(self, message, level="normal"):
        """添加日志消息"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # 根据日志级别设置颜色
        if level == "error":
            color = "#FF5555"
        elif level == "success":
            color = "#55AA55"
        elif level == "info":
            color = "#5555FF"
        elif level == "warning":
            color = "#FFAA00"
        else:
            color = "#000000"
        
        formatted_message = f'<span style="color:#888888">[{timestamp}]</span> <span style="color:{color}">{message}</span>'
        self.log_output.append(formatted_message)
        
        # 滚动到底部
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_output.setTextCursor(cursor)


class GameRunThread(QThread):
    """游戏运行线程"""
    log_message = pyqtSignal(str, str)
    game_started = pyqtSignal()  # 游戏成功启动信号
    
    def __init__(self, config_path, level_id, all_packs):
        super().__init__()
        self.config_path = config_path
        self.level_id = level_id
        self.all_packs = all_packs
        self.game_process = None
        
    def run(self):
        """线程执行函数"""
        try:
            self.log_message.emit(f"🚀 正在启动游戏实例: {self.level_id[:8]}...", "info")
            
            # 使用run_cmd.py中的函数启动游戏，传递日志回调函数
            success, self.game_process = _run_game_with_instance(
                self.config_path, 
                self.level_id, 
                self.all_packs,
                wait=False,  # 不阻塞等待
                log_callback=lambda msg, level: self.log_message.emit(msg, level)
            )
            
            if success and self.game_process:
                self.game_started.emit()  # 发送游戏已启动信号
            
        except Exception as e:
            self.log_message.emit(f"❌ 运行游戏时出错: {str(e)}", "error")
            import traceback
            error_details = traceback.format_exc()
            self.log_message.emit(f"错误详情:\n{error_details}", "error")


def show_run_ui(base_dir=default_base_dir):
    """显示游戏实例管理UI"""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))
    
    # 设置应用主题
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(240, 240, 240))
    palette.setColor(QPalette.WindowText, QColor(0, 0, 0))
    palette.setColor(QPalette.Base, QColor(255, 255, 255))
    palette.setColor(QPalette.AlternateBase, QColor(245, 245, 245))
    palette.setColor(QPalette.Text, QColor(0, 0, 0))
    palette.setColor(QPalette.Button, QColor(240, 240, 240))
    palette.setColor(QPalette.ButtonText, QColor(0, 0, 0))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218, 70))
    palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
    app.setPalette(palette)
    
    window = GameInstanceManager(base_dir)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    show_run_ui()

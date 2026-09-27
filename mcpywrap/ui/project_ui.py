# -*- coding: utf-8 -*-

"""
游戏实例管理图形界面
"""

import os
import sys
import time
import html
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QTableWidget, QTableWidgetItem, QPushButton, QLabel, QHeaderView, 
    QMessageBox, QSplitter, QTextEdit, QPlainTextEdit, QProgressBar, QFrame,
    QStyleFactory, QStatusBar, QCheckBox, QFileDialog, QGroupBox,
    QLineEdit, QListWidget, QListWidgetItem, QComboBox, QCompleter
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QStringListModel
from PyQt5.QtGui import QIcon, QFont, QTextCursor, QColor, QPalette

# 导入项目模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from mcpywrap.commands.run_cmd import (
    _get_all_instances, _generate_new_instance_config, _setup_dependencies, _run_game_with_instance,
    _delete_instance, _clean_all_instances, get_project_name, config_exists
)
from ..commands.edit_cmd import open_edit
from ..config import get_project_dependencies
from ..dependencies import (DependencyService, DependencyDeclaration, DependencyError,
                            read_project, resolve_path, path_for_storage, addon_directories)
from ..builders.dependency_manager import find_all_mcpywrap_packages


class GameInstanceManager(QMainWindow):
    """游戏实例管理器主窗口"""
    
    def __init__(self, base_dir, mcs_auth=False):
        super().__init__()
        self.base_dir = os.path.abspath(base_dir)
        self.mcs_auth = mcs_auth
        self.dependency_service = DependencyService(self.base_dir)
        self.current_project = read_project(self.base_dir).get('project', {}).get('name', '未初始化项目')
        self.dependency_busy = False
        self.instances = []
        self.all_packs = None
        self.dependencies = []
        self.setup_ui()
        self.init_data()

    def closeEvent(self, event):
        if any(getattr(self, name, None) and getattr(self, name).isRunning()
               for name in ('install_thread', 'game_thread')):
            self.log('请等待当前安装或启动操作完成后关闭窗口。', 'warning')
            event.ignore()
            return
        super().closeEvent(event)

    def setup_global_font(self):
        """设置全局字体为现代化中文字体"""
        # 设置优先使用的字体：微软雅黑、苹方、思源黑体等现代中文字体
        font = QFont("Microsoft YaHei, PingFang SC, Hiragino Sans GB, Source Han Sans CN, WenQuanYi Micro Hei, SimHei, sans-serif", 9)
        QApplication.setFont(font)
        
    def setup_ui(self):
        """设置UI界面"""
        self.setWindowTitle(f"Minecraft游戏实例管理器 - {self.current_project}")
        self.setMinimumSize(800, 600)
        self.resize(1200, 800)
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
        
        # 设置固定高度策略
        size_policy = info_frame.sizePolicy()
        size_policy.setVerticalPolicy(size_policy.Fixed)
        info_frame.setSizePolicy(size_policy)
        
        # 项目名称和路径
        project_info = QLabel(f"<b>项目:</b> {self.current_project} | <b>路径:</b> {self.base_dir}")
        info_layout.addWidget(project_info)
        
        # 快速操作按钮
        refresh_btn = QPushButton("刷新")
        refresh_btn.setToolTip("刷新实例列表")
        refresh_btn.clicked.connect(self.refresh_instances)
        info_layout.addWidget(refresh_btn)
        
        # 添加编辑器按钮
        edit_btn = QPushButton("使用MCEditor编辑")
        edit_btn.setToolTip("使用MC Studio Editor编辑项目")
        edit_btn.clicked.connect(self.open_mc_editor)
        info_layout.addWidget(edit_btn)
        self.edit_btn = edit_btn  # 保存引用以便稍后启用/禁用
        
        main_layout.addWidget(info_frame)
        
        # 创建水平分割器用于左侧依赖管理和右侧实例管理
        h_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(h_splitter)
        
        # 左侧依赖管理区域
        dependency_widget = QWidget()
        dependency_layout = QVBoxLayout(dependency_widget)
        
        # 依赖管理标题
        dependency_title = QLabel("<h3>依赖管理</h3>")
        dependency_layout.addWidget(dependency_title)
        
        # 依赖列表
        self.dependency_list = QListWidget()
        self.dependency_list.setAlternatingRowColors(True)
        self.dependency_list.itemClicked.connect(self.on_dependency_selected)
        dependency_layout.addWidget(self.dependency_list)
        
        # 依赖操作按钮
        self.remove_dep_btn = QPushButton("移除选中依赖")
        self.remove_dep_btn.setEnabled(False)
        self.remove_dep_btn.clicked.connect(self.remove_selected_dependency)
        dependency_layout.addWidget(self.remove_dep_btn)
        
        # 添加依赖区域
        add_dep_group = QGroupBox("添加新依赖")
        add_dep_layout = QVBoxLayout(add_dep_group)
        
        self.dependency_kind = QComboBox()
        self.dependency_kind.addItem("Python 包（工具环境）", "package")
        self.dependency_kind.addItem("本地 Addon 目录", "local")
        add_dep_layout.addWidget(self.dependency_kind)
        dependency_note = QLabel('包安装于 mcpy 工具环境；仅识别出的 Addon 参与组装，游戏不会读取 Python 依赖表。')
        dependency_note.setWordWrap(True)
        add_dep_layout.addWidget(dependency_note)
        self.new_dep_input = QComboBox()
        self.new_dep_input.setEditable(True)
        self.new_dep_input.setInsertPolicy(QComboBox.NoInsert)
        self.new_dep_input.lineEdit().setPlaceholderText("包名或版本约束")
        self.new_dep_input.lineEdit().returnPressed.connect(self.add_dependency)
        add_dep_layout.addWidget(self.new_dep_input)
        self.local_path_input = QLineEdit()
        self.local_path_input.setPlaceholderText("相对或绝对 Addon 根目录")
        self.local_path_input.returnPressed.connect(self.add_dependency)
        self.browse_dependency_btn = QPushButton("浏览目录")
        self.browse_dependency_btn.clicked.connect(self.browse_dependency)
        self.absolute_path_check = QCheckBox("保存为绝对路径")
        self.path_preview = QPlainTextEdit()
        self.path_preview.setReadOnly(True)
        self.path_preview.setMinimumHeight(105)
        self.path_preview.setMaximumHeight(150)
        for widget in (self.local_path_input, self.browse_dependency_btn, self.absolute_path_check, self.path_preview):
            add_dep_layout.addWidget(widget)
        self.local_path_input.textChanged.connect(self.update_path_preview)
        self.absolute_path_check.toggled.connect(self.update_path_preview)
        self.dependency_kind.currentIndexChanged.connect(self.on_dependency_kind_changed)
        self.add_dep_btn = QPushButton("添加依赖")
        self.add_dep_btn.clicked.connect(self.add_dependency)
        add_dep_layout.addWidget(self.add_dep_btn)
        self.on_dependency_kind_changed()

        dependency_layout.addWidget(add_dep_group)
        
        # 将依赖管理界面添加到分割器
        h_splitter.addWidget(dependency_widget)
        
        # 右侧实例管理区域
        instance_widget = QWidget()
        instance_layout = QVBoxLayout(instance_widget)
        
        # 创建垂直分割器用于实例列表和日志区域
        v_splitter = QSplitter(Qt.Vertical)
        instance_layout.addWidget(v_splitter)
        
        # 实例列表区域
        instance_list_widget = QWidget()
        instance_list_layout = QVBoxLayout(instance_list_widget)
        instance_list_layout.setContentsMargins(0, 0, 0, 0)
        
        # 实例列表标题
        instance_title = QLabel("<h3>游戏实例列表</h3>")
        instance_list_layout.addWidget(instance_title)
        
        # 实例列表表格
        self.instance_table = QTableWidget(0, 4)
        self.instance_table.setHorizontalHeaderLabels(["默认", "实例ID", "创建时间", "世界名称"])
        self.instance_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.instance_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.instance_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.instance_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.instance_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.instance_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.instance_table.setAlternatingRowColors(True)
        self.instance_table.itemDoubleClicked.connect(self.on_instance_double_clicked)
        self.instance_table.setStyleSheet("QTableView::item:selected { background-color: #e0f0ff; color: black; }")
        instance_list_layout.addWidget(self.instance_table)
        
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
        
        instance_list_layout.addLayout(btn_layout)
        
        # 添加实例管理区域到垂直分割器
        v_splitter.addWidget(instance_list_widget)
        
        # 日志输出区域
        log_frame = QFrame()
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(0, 0, 0, 0)
        
        log_title = QLabel("<h3>操作日志</h3>")
        log_layout.addWidget(log_title)
        
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        log_layout.addWidget(self.log_output)
        
        # 添加日志区域到垂直分割器
        v_splitter.addWidget(log_frame)
        
        # 设置垂直分割器比例
        v_splitter.setSizes([400, 200])
        
        # 将实例管理区域添加到水平分割器
        h_splitter.addWidget(instance_widget)
        
        # 设置水平分割器比例
        h_splitter.setSizes([300, 700])
        
        # 连接选择变更信号
        self.instance_table.itemSelectionChanged.connect(self.on_selection_changed)
    
    def init_data(self):
        """初始化数据"""
        if not os.path.isfile(os.path.join(self.base_dir, 'pyproject.toml')):
            self.log("❌ 项目尚未初始化，请先运行 mcpy init", "error")
            self.new_btn.setEnabled(False)
            self.clean_btn.setEnabled(False)
            self.edit_btn.setEnabled(False)  # 禁用编辑按钮
            return
        
        # 设置项目依赖
        self.log("📦 正在加载项目依赖...")
        self.reload_runtime_dependencies()
        
        # 加载实例列表
        self.refresh_instances()
        
        # 加载依赖列表
        self.refresh_dependencies()
        
        # 加载可用mcpywrap包
        self.load_available_packages()
    
    def load_available_packages(self):
        """加载系统中可用的mcpywrap包"""
        self.log("🔍 正在搜索系统中可用的mcpywrap包...", "info")
        try:
            available_packages = find_all_mcpywrap_packages()
            if available_packages:
                self.new_dep_input.clear()
                for package in available_packages:
                    if package != self.current_project:  # 排除当前项目
                        self.new_dep_input.addItem(package)
                
                # 添加自动补全功能
                completer = QCompleter(available_packages)
                completer.setCaseSensitivity(Qt.CaseInsensitive)
                self.new_dep_input.setCompleter(completer)
                
                # 设置当前索引为-1，表示不选择任何项
                self.new_dep_input.setCurrentIndex(-1)
                
                self.log(f"✅ 找到 {len(available_packages)} 个可用的mcpywrap包", "success")
            else:
                self.log("📦 没有找到可用的mcpywrap包", "info")
        except Exception as e:
            self.log(f"❌ 搜索可用包时出错: {str(e)}", "error")
    
    def on_dependency_selected_from_dropdown(self, index):
        """从下拉列表选择依赖时触发"""
        if index >= 0:
            # 可以在这里添加额外的处理逻辑
            pass
    
    def refresh_instances(self):
        """刷新实例列表"""
        self.instances = _get_all_instances(self.base_dir)
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
    
    def refresh_dependencies(self):
        self.dependency_list.clear()
        try:
            self.dependencies = self.dependency_service.list()
            for dependency in self.dependencies:
                status = self.dependency_service.inspect(dependency)
                label = "本地目录" if dependency.kind == "local" else "Python 包"
                text = f"[{label}] {dependency.value}"
                labels = {'addon': 'Addon', 'development_only': '仅开发环境',
                          'inactive': '环境标记未启用', 'unavailable': '缺失／无效'}
                text += ' — ' + labels[status.state]
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, dependency)
                tooltip = status.message or '可参与 Addon 组装；游戏兼容性需实际测试'
                if dependency.kind == 'local':
                    tooltip = str(resolve_path(self.base_dir, dependency.value)) + "\n" + tooltip
                item.setToolTip(tooltip)
                self.dependency_list.addItem(item)
        except (DependencyError, OSError) as exc:
            self.log(str(exc), 'error')
        self.remove_dep_btn.setEnabled(False)

    def reload_runtime_dependencies(self):
        try:
            self.all_packs = _setup_dependencies(self.current_project, self.base_dir, raise_errors=True,
                                                report=lambda message: self.log(message, 'warning'))
        except (DependencyError, OSError) as exc:
            self.all_packs = None
            self.log(str(exc), 'error')
        ready = self.all_packs is not None and not self.dependency_busy
        self.new_btn.setEnabled(ready)
        self.edit_btn.setEnabled(ready)
        self.run_btn.setEnabled(ready and bool(self.instance_table.selectedItems()))
        return self.all_packs is not None

    def on_dependency_kind_changed(self, *args):
        local = self.dependency_kind.currentData() == 'local'
        self.new_dep_input.setVisible(not local)
        for widget in (self.local_path_input, self.browse_dependency_btn, self.absolute_path_check, self.path_preview):
            widget.setVisible(local)
        if local:
            self.update_path_preview()

    def browse_dependency(self):
        selected = QFileDialog.getExistingDirectory(self, '选择 Addon 根目录', self.base_dir)
        if selected:
            self.local_path_input.setText(selected)

    def update_path_preview(self, *args):
        value = self.local_path_input.text().strip()
        if not value:
            self.path_preview.setPlainText('请选择包含行为包或资源包的项目目录')
            return
        try:
            resolved = resolve_path(self.base_dir, value)
            folders = addon_directories(resolved)
            saved = path_for_storage(self.base_dir, value, self.absolute_path_check.isChecked())
            self.path_preview.setPlainText(f"目录：{resolved}\n保存为：{saved}\n有效包：{', '.join(folders)}")
        except (DependencyError, OSError, ValueError) as exc:
            self.path_preview.setPlainText(str(exc))

    def set_dependency_busy(self, busy):
        self.dependency_busy = busy
        for widget in (self.dependency_kind, self.new_dep_input, self.local_path_input,
                       self.browse_dependency_btn, self.absolute_path_check, self.add_dep_btn):
            widget.setEnabled(not busy)
        self.remove_dep_btn.setEnabled(not busy and bool(self.dependency_list.selectedItems()))
        self.new_btn.setEnabled(not busy and self.all_packs is not None)
        self.edit_btn.setEnabled(not busy and self.all_packs is not None)
        self.run_btn.setEnabled(not busy and self.all_packs is not None and bool(self.instance_table.selectedItems()))

    def on_selection_changed(self):
        """选择变更事件处理"""
        selected_rows = self.instance_table.selectionModel().selectedRows()
        has_selection = len(selected_rows) > 0
        self.run_btn.setEnabled(has_selection and self.all_packs is not None and not self.dependency_busy)
        self.delete_btn.setEnabled(has_selection)
    
    def on_instance_double_clicked(self, item):
        """双击实例表格项事件处理"""
        self.run_selected_instance()
    
    def on_dependency_selected(self, item):
        """依赖项目被选中"""
        self.remove_dep_btn.setEnabled(not self.dependency_busy)
    
    def create_new_instance(self):
        """创建新的游戏实例"""
        if self.dependency_busy or not self.reload_runtime_dependencies():
            self.log("❌ 无法创建实例，项目依赖加载失败", "error")
            return
        
        self.log("🆕 正在创建新的游戏实例...")
        
        # 生成新的实例配置
        level_id, config_path = _generate_new_instance_config(self.base_dir, self.current_project)
        
        # 运行游戏实例
        self.log(f"📝 配置文件已生成: {os.path.basename(config_path)}")
        self.log(f"🚀 正在启动游戏实例: {level_id[:8]}...")
        
        # 使用QThread启动游戏，避免UI卡死
        self.start_game_thread(config_path, level_id)
    
    def run_selected_instance(self):
        """运行选中的游戏实例"""
        if self.dependency_busy or not self.reload_runtime_dependencies():
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
        self.start_game_thread(config_path, level_id)

    def start_game_thread(self, config_path, level_id):
        identity = None
        if self.mcs_auth:
            from ..mcstudio.mcs_auth import acquire_identity, AuthError
            try:
                identity = acquire_identity(interactive=True)
            except AuthError as exc:
                self.log(str(exc), 'error')
                return
        self.game_thread = GameRunThread(config_path, level_id, self.all_packs, identity)
        self.game_thread.log_message.connect(self.log)
        self.game_thread.finished.connect(self.refresh_instances)
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
            _delete_instance(level_id[:8], force, self.base_dir)
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
                _clean_all_instances(True, self.base_dir)  # 使用强制模式
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
        
        formatted_message = f'<span style="color:#888888">[{timestamp}]</span> <span style="color:{color}">{html.escape(str(message))}</span>'
        self.log_output.append(formatted_message)
        
        # 滚动到底部
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_output.setTextCursor(cursor)
    
    def open_mc_editor(self):
        """打开MC Studio Editor编辑器"""
        if not os.path.isfile(os.path.join(self.base_dir, 'pyproject.toml')):
            self.log("❌ 项目尚未初始化，无法打开编辑器", "error")
            return
            
        if self.reload_runtime_dependencies():
            open_edit(self.base_dir)
    
    def remove_selected_dependency(self):
        if self.dependency_busy:
            return
        selected = self.dependency_list.selectedItems()
        if not selected:
            return
        entry = selected[0].data(Qt.UserRole)
        note = '仅移除引用，源目录保留。' if entry.kind == 'local' else '仅移除配置，不卸载 Python 包。'
        if QMessageBox.question(self, '确认移除依赖', f'{entry.value}\n{note}',
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.dependency_service.remove(entry)
            self.log(f'已移除依赖: {entry.value}', 'success')
            self.refresh_dependencies()
            self.reload_runtime_dependencies()
        except (DependencyError, OSError) as exc:
            self.log(str(exc), 'error')

    def add_dependency(self):
        if self.dependency_busy:
            return
        if self.dependency_kind.currentData() == 'local':
            value = self.local_path_input.text().strip()
            try:
                if not value:
                    raise DependencyError('请输入或选择本地 Addon 目录')
                saved = path_for_storage(self.base_dir, value, self.absolute_path_check.isChecked())
                changed, warnings = self.dependency_service.add_local(saved)
                self.log('依赖已添加' if changed else '依赖已存在', 'success')
                for warning in warnings:
                    self.log(warning, 'warning')
                self.local_path_input.clear()
                self.refresh_dependencies()
                self.reload_runtime_dependencies()
            except (DependencyError, OSError) as exc:
                self.path_preview.setPlainText(str(exc))
                self.log(str(exc), 'error')
            return
        package = self.new_dep_input.currentText().strip()
        if not package:
            QMessageBox.warning(self, '输入错误', '请输入或选择 Python 包声明')
            return
        self.set_dependency_busy(True)
        self.install_thread = DependencyInstallThread(package, self.base_dir)
        self.install_thread.log_message.connect(self.log)
        self.install_thread.result.connect(self.on_dependency_installed)
        self.install_thread.finished.connect(lambda: self.set_dependency_busy(False))
        self.install_thread.start()

    def on_dependency_installed(self, success, message):
        self.log(message, 'success' if success else 'error')
        if success:
            self.load_available_packages()
            self.new_dep_input.setCurrentText('')
        self.refresh_dependencies()
        self.reload_runtime_dependencies()


class GameRunThread(QThread):
    """游戏运行线程"""
    log_message = pyqtSignal(str, str)
    game_started = pyqtSignal()  # 游戏成功启动信号
    
    def __init__(self, config_path, level_id, all_packs, auth_context=None):
        super().__init__()
        self.config_path = config_path
        self.level_id = level_id
        self.all_packs = all_packs
        self.game_process = None
        self.auth_context = auth_context
        
    def run(self):
        """线程执行函数"""
        try:
            self.log_message.emit(f"🚀 正在启动游戏实例: {self.level_id[:8]}...", "info")
            if self.auth_context is not None:
                from pathlib import Path
                from ..mcstudio import sessions
                from ..mcstudio.processes import checked_process
                data = sessions.start(str(Path(self.config_path).resolve().parent.parent),
                                      self.config_path, self.level_id, auth_context=self.auth_context)
                self.game_process = checked_process(data['game'])
                self.log_message.emit('游戏已启动；日志保存在 '+data['log_path'], 'success')
                self.game_started.emit()
                return
            
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
        finally:
            self.auth_context = None


class DependencyInstallThread(QThread):
    """后台安装成功后才保存声明，并显式报告结果。"""
    log_message = pyqtSignal(str, str)
    result = pyqtSignal(bool, str)

    def __init__(self, package, project_dir):
        super().__init__()
        self.package, self.project_dir = package, project_dir

    def run(self):
        try:
            self.log_message.emit(f'正在向 mcpy 工具环境安装 {self.package}（非游戏环境）...', 'info')
            service = DependencyService(self.project_dir)
            changed = service.add_package(self.package)
            for message in service.last_resolution.warnings:
                self.log_message.emit(message, 'warning')
            self.result.emit(True, '工具环境安装完成，声明已保存' if changed else '工具环境安装完成，声明已存在')
        except Exception as exc:
            self.result.emit(False, f'依赖安装失败: {exc}')


def show_run_ui(base_dir=None, mcs_auth=False):
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
    
    window = GameInstanceManager(base_dir or os.getcwd(), mcs_auth=mcs_auth)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    show_run_ui()

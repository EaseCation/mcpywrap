# -*- coding: utf-8 -*-

"""
游戏实例管理图形界面
"""

import os
import sys
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QTableWidget, QTableWidgetItem, QPushButton, QLabel, QHeaderView, 
    QMessageBox, QSplitter, QTextEdit, QPlainTextEdit, QFrame,
    QCheckBox, QFileDialog, QGroupBox, QScrollArea,
    QTabWidget, QLineEdit, QListWidget, QListWidgetItem, QComboBox, QCompleter, QToolButton, QMenu, QInputDialog, QSizePolicy, QFormLayout
)
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer, QStringListModel
from PySide6.QtGui import QFont, QColor

from ..runtime.preparation import resolve_packs
from ..commands.edit_cmd import open_edit
from ..engines.backend import get_backend
from .session_controller import SessionController
from .session_views import SessionControls, PythonConsole
from .log_view import LogView
from .log_window import SessionLogWindow
from .application import create_application, application_icon
from ..dependencies import (DependencyService, DependencyError,
                            read_project, resolve_path, path_for_storage, addon_directories)
from ..builders.dependency_manager import find_all_mcpywrap_packages


class GameInstanceManager(QMainWindow):
    """游戏实例管理器主窗口"""
    
    def __init__(self, base_dir, mcs_auth=False, engine_overrides=None):
        super().__init__()
        self.base_dir = os.path.abspath(base_dir)
        self.mcs_auth = mcs_auth
        self.backend = get_backend()
        self.controller = SessionController(self.base_dir, self.backend, self, engine_overrides)
        self.closing = False
        self.log_window = None
        self.dependency_service = DependencyService(self.base_dir)
        self.current_project = read_project(self.base_dir).get('project', {}).get('name', '未初始化项目')
        self.dependency_busy = False
        self.instances = []
        self.all_packs = None
        self.dependencies = []
        self.setup_ui()
        self.controller.started.connect(self.on_game_started)
        self.controller.changed.connect(self.update_session_state)
        self.controller.stopped.connect(self.on_game_stopped)
        self.controller.failed.connect(self.task_failed)
        self.init_data()
        self.update_session_state()

    def closeEvent(self, event):
        if self.is_busy():
            self.log('请等待当前操作完成后关闭窗口。', 'warning')
            event.ignore(); return
        if self.controller.watcher:
            self.closing = True
            self.controller.set_watching(False)
            event.ignore(); return
        if self.log_window: self.log_window.close()
        self.controller.dispose()
        super().closeEvent(event)

    def is_busy(self):
        return self.controller.busy or bool(getattr(self, 'install_thread', None) and self.install_thread.isRunning())

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
        self.setWindowIcon(application_icon())

        self.setup_global_font()
        
        # 主布局
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        self.setCentralWidget(main_widget)
        
        # 项目信息区域
        info_frame = QFrame()
        info_frame.setFrameShape(QFrame.Shape.StyledPanel)
        info_layout = QHBoxLayout(info_frame)
        
        # 设置固定高度策略
        size_policy = info_frame.sizePolicy()
        size_policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)
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
        edit_btn = QPushButton("使用 MCEditor 编辑" if "editor" in self.backend.capabilities else "MCEditor（不支持）")
        edit_btn.setToolTip("使用MC Studio Editor编辑项目")
        edit_btn.clicked.connect(self.open_mc_editor)
        info_layout.addWidget(edit_btn)
        edit_btn.setToolTip('需要 Windows MC Studio Editor' if 'editor' not in self.backend.capabilities else '使用 MC Studio Editor 编辑项目')
        self.edit_btn = edit_btn  # 保存引用以便稍后启用/禁用
        
        self.mod_btn = QPushButton('新建 Mod')
        self.mod_btn.clicked.connect(self.create_mod)
        info_layout.addWidget(self.mod_btn)
        self.engine_btn = QPushButton('运行环境')
        self.engine_btn.clicked.connect(self.prepare_engine)
        info_layout.addWidget(self.engine_btn)
        self.session_label = QLabel(self.backend.label)
        main_layout.addWidget(self.session_label)
        main_layout.addWidget(info_frame)
        
        # 创建水平分割器用于左侧依赖管理和右侧实例管理
        h_splitter = QSplitter(Qt.Orientation.Horizontal)
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
        self.change_packaging_btn = QPushButton('更改打包设置…')
        self.change_packaging_btn.setEnabled(False)
        self.change_packaging_btn.clicked.connect(self.change_dependency_packaging)
        dependency_layout.addWidget(self.change_packaging_btn)
        packaging_note = QLabel('依赖默认随构建打包；勾选“不随构建打包”后，仅在 dev/run 中加载。修改后请重启游戏会话。')
        packaging_note.setWordWrap(True)
        dependency_layout.addWidget(packaging_note)
        
        # 添加依赖区域
        add_dep_group = QGroupBox("添加新依赖")
        add_dep_layout = QVBoxLayout(add_dep_group)
        
        self.dependency_kind = QComboBox()
        self.dependency_kind.addItem("Python 包（工具环境）", "package")
        self.dependency_kind.addItem("本地 Addon 目录", "local")
        self.dependency_kind.addItem("Git 依赖（项目与代码库）", "git")
        add_dep_layout.addWidget(self.dependency_kind)
        self.dependency_note = QLabel()
        self.dependency_note.setWordWrap(True)
        add_dep_layout.addWidget(self.dependency_note)
        self.dependency_unbundled = QCheckBox('不随构建打包（unbundled）')
        self.dependency_unbundled.setChecked(False)
        self.dependency_unbundled.setToolTip('默认不勾选。勾选后 dev/run 照常加载，build/package 排除；Python 工具包不使用此设置。')
        add_dep_layout.addWidget(self.dependency_unbundled)
        self.new_dep_input = QComboBox()
        self.new_dep_input.setEditable(True)
        self.new_dep_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
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
        from ..framework_presets import FRAMEWORK_PRESETS
        self.git_shortcuts = {}
        for name, preset in FRAMEWORK_PRESETS.items():
            button = QToolButton()
            button.setText('一键添加 ' + preset['title'])
            button.setToolTip(preset['title'] + ' ' + preset['version'] + '：使用已验证的固定提交；新目录生成入口，已有代码不改写。')
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda checked=False, name=name: self.add_preset_dependency(name))
            menu = QMenu(button)
            for source in preset['sources']:
                action = menu.addAction('使用 ' + source + ' 来源')
                action.triggered.connect(lambda checked=False, name=name, source=source: self.add_preset_dependency(name, source=source))
            action = menu.addAction('指定 Mod 脚本目录…')
            action.triggered.connect(lambda checked=False, name=name: self.add_preset_dependency(name, choose_script=True))
            button.setMenu(menu)
            self.git_shortcuts[name] = button
            add_dep_layout.addWidget(button)
        self.git_fields = {}
        self.git_panel = QWidget()
        git_form = QFormLayout(self.git_panel)
        git_form.setContentsMargins(0, 0, 0, 0)
        labels = {'git': '仓库', 'name': '名称', 'ref': '版本引用', 'subdir': '子目录', 'target': '安装位置'}
        for key, placeholder in [('git', 'Git URL（HTTPS或file://）'), ('name', '依赖名称（可选，默认仓库名）'),
                                 ('ref', '提交／标签／分支（默认HEAD，添加后锁SHA）'),
                                 ('subdir', '项目／源码子目录（默认 .）'), ('target', '代码安装位置（Addon无需填写）')]:
            field = QLineEdit()
            field.setPlaceholderText(placeholder)
            field.setToolTip(placeholder)
            self.git_fields[key] = field
            git_form.addRow(labels[key], field)
        self.git_kind = QComboBox()
        for name, value in [('自动识别导出描述或Addon', 'auto'), ('Addon', 'addon'), ('Python代码目录', 'code')]:
            self.git_kind.addItem(name, value)
        git_form.addRow('导出类型', self.git_kind)
        add_dep_layout.addWidget(self.git_panel)
        self.add_dep_btn = QPushButton("添加依赖")
        self.add_dep_btn.clicked.connect(self.add_dependency)
        add_dep_layout.addWidget(self.add_dep_btn)
        self.dependency_unbundled.toggled.connect(self.update_packaging_controls)
        self.on_dependency_kind_changed()

        dependency_layout.addWidget(add_dep_group)
        self.sync_dependencies_btn = QPushButton('同步项目依赖')
        self.sync_dependencies_btn.clicked.connect(self.sync_dependencies)
        dependency_layout.addWidget(self.sync_dependencies_btn)
        self.preview_release_btn = QPushButton('查看发布依赖…')
        self.preview_release_btn.clicked.connect(self.preview_release_dependencies)
        dependency_layout.addWidget(self.preview_release_btn)
        
        # 将依赖管理界面添加到分割器
        dependency_scroll = QScrollArea()
        dependency_scroll.setWidgetResizable(True)
        dependency_scroll.setWidget(dependency_widget)
        dependency_scroll.setMinimumWidth(340)
        h_splitter.addWidget(dependency_scroll)
        
        # 右侧实例管理区域
        instance_widget = QWidget()
        instance_layout = QVBoxLayout(instance_widget)
        
        # 创建垂直分割器用于实例列表和日志区域
        v_splitter = QSplitter(Qt.Orientation.Vertical)
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
        self.instance_table.setHorizontalHeaderLabels(["状态", "实例ID", "创建时间", "世界名称"])
        self.instance_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.instance_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.instance_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.instance_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.instance_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.instance_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.instance_table.setAlternatingRowColors(True)
        self.instance_table.itemDoubleClicked.connect(self.on_instance_double_clicked)
        self.instance_table.setStyleSheet("QTableView::item:selected { background-color: #e0f0ff; color: black; }")
        instance_list_layout.addWidget(self.instance_table)
        
        # 实例操作按钮
        btn_layout = QHBoxLayout()
        
        self.new_btn = QToolButton()
        self.new_btn.setText('新建实例')
        self.new_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        menu = QMenu(self.new_btn)
        menu.addAction('从 cppconfig 新建…', self.create_from_cppconfig)
        menu.addAction('按选中实例配置新建', self.create_from_selected)
        self.new_btn.setMenu(menu)
        self.new_btn.clicked.connect(self.create_new_instance)
        btn_layout.addWidget(self.new_btn)
        
        self.run_btn = QPushButton("启动选中实例")
        self.run_btn.clicked.connect(self.run_selected_instance)
        self.run_btn.setEnabled(False)
        btn_layout.addWidget(self.run_btn)
        self.dual_btn = QPushButton('双客户端联调')
        self.dual_btn.clicked.connect(self.run_dual_clients)
        btn_layout.addWidget(self.dual_btn)
        self.connect_btn = QPushButton('连接服务器…')
        self.connect_btn.clicked.connect(self.connect_server)
        btn_layout.addWidget(self.connect_btn)
        
        self.delete_btn = QPushButton("删除选中实例")
        self.delete_btn.clicked.connect(self.delete_selected_instance)
        self.delete_btn.setEnabled(False)
        btn_layout.addWidget(self.delete_btn)
        
        self.clean_btn = QPushButton("清空所有实例")
        self.clean_btn.clicked.connect(self.clean_all_instances)
        btn_layout.addWidget(self.clean_btn)
        
        instance_list_layout.addLayout(btn_layout)
        self.watch_on_start = QCheckBox('运行并监控 Python（客户端；可在下方调整端侧）')
        instance_list_layout.addWidget(self.watch_on_start)
        self.attach_btn = QPushButton('接管已有会话…')
        self.attach_btn.clicked.connect(self.attach_existing)
        instance_list_layout.addWidget(self.attach_btn)
        self.session_controls = SessionControls(self.controller)
        instance_list_layout.addWidget(self.session_controls)
        self.float_log_btn = QPushButton('打开日志小窗')
        self.float_log_btn.clicked.connect(self.show_log_window)
        instance_list_layout.addWidget(self.float_log_btn)

        # 添加实例管理区域到垂直分割器
        v_splitter.addWidget(instance_list_widget)
        
        # 日志输出区域
        log_frame = QFrame()
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(0, 0, 0, 0)
        
        log_title = QLabel("<h3>操作日志</h3>")
        log_layout.addWidget(log_title)
        
        self.operation_view = LogView(self.controller.logs, source='operations', toolbar=False)
        self.log_output = self.operation_view.editor
        self.log_tabs = QTabWidget()
        self.log_tabs.addTab(self.operation_view, '操作')
        self.debug_view = LogView(self.controller.logs)
        self.log_tabs.addTab(self.debug_view, 'Debug 日志')
        self.python_console = PythonConsole(self.controller)
        self.log_tabs.addTab(self.python_console, 'Python / 热更')
        log_layout.addWidget(self.log_tabs)
        
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
                completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
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
    
    @Slot()
    def refresh_instances(self):
        """刷新实例列表"""
        self.instances = self.backend.instances(self.base_dir)
        self.instance_table.setRowCount(0)
        
        if not self.instances:
            self.log("📭 没有找到任何游戏实例", "info")
            self.run_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            return
        
        self.instance_table.setRowCount(len(self.instances))
        default = next((i['level_id'] for i in self.instances if i.get('state', 'ready') in ('ready', 'legacy_existing')), None)
        for row, instance in enumerate(self.instances):
            # 状态图标
            state = instance.get('state', 'ready')
            labels = {'pending': '待启动', 'failed': '启动失败', 'unverified': '尚未确认', 'legacy_existing': '已有存档', 'ready': '可用'}
            status_item = QTableWidgetItem(('📌 ' if instance['level_id'] == default else '') + labels.get(state, state))
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            
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
        self.controller.restore_startup_problem(self.instances)
    
    def refresh_dependencies(self):
        self.dependency_list.clear()
        try:
            self.dependencies = self.dependency_service.list()
            for dependency in self.dependencies:
                status = self.dependency_service.inspect(dependency)
                label = {'local': '本地目录', 'package': 'Python 包', 'code': 'Git依赖', 'git': 'Git依赖'}[dependency.kind]
                usage = ('不随构建打包' if dependency.unbundled else '随构建打包') if dependency.kind in ('local', 'git', 'code') else '工具 Python'
                text = f"[{label} / {usage}] {dependency.value}"
                labels = {'addon': 'Addon', 'development_only': '仅开发环境',
                          'inactive': '环境标记未启用', 'unavailable': '缺失／无效', 'code_library': '已同步', 'git_project': '已同步'}
                text += ' — ' + labels[status.state]
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, dependency)
                tooltip = status.message or '可参与 Addon 组装；游戏兼容性需实际测试'
                if dependency.kind in ('local', 'git', 'code'):
                    tooltip += '\n' + ('仅 dev/run 加载；build/package 排除。' if dependency.unbundled else 'dev/run 加载，并进入 build/package。')
                if dependency.kind == 'local':
                    tooltip = str(resolve_path(self.base_dir, dependency.value)) + "\n" + tooltip
                item.setToolTip(tooltip)
                self.dependency_list.addItem(item)
        except (DependencyError, OSError) as exc:
            self.log(str(exc), 'error')
        self.remove_dep_btn.setEnabled(False)
        self.change_packaging_btn.setEnabled(False)

    def reload_runtime_dependencies(self):
        try:
            self.all_packs = resolve_packs(self.base_dir, report=lambda message: self.log(message, 'warning'))
        except (DependencyError, OSError) as exc:
            self.all_packs = None
            self.log(str(exc), 'error')
        ready = self.all_packs is not None and not self.dependency_busy
        self.new_btn.setEnabled(ready)
        self.edit_btn.setEnabled(ready and 'editor' in self.backend.capabilities)
        self.run_btn.setEnabled(ready and bool(self.instance_table.selectedItems()))
        return self.all_packs is not None

    def on_dependency_kind_changed(self, *args):
        kind = self.dependency_kind.currentData()
        self.dependency_note.setText({
            'package': 'Python 包安装到工具环境；只有识别出的 Addon 内容会参与游戏组装。',
            'local': '引用完整的本地 Addon；保留源目录，并解析其声明的子依赖。',
            'git': '从仓库读取项目描述和子依赖。也可使用快捷按钮添加常用 Git 依赖。',
        }[kind])
        self.dependency_unbundled.setVisible(kind != 'package')
        self.new_dep_input.setVisible(kind == 'package')
        for widget in (self.git_panel, *self.git_shortcuts.values()):
            widget.setVisible(kind == 'git')
        for widget in (self.local_path_input, self.browse_dependency_btn, self.absolute_path_check, self.path_preview):
            widget.setVisible(kind == 'local')
        if kind == 'local':
            self.update_path_preview()
        self.add_dep_btn.setText('添加 Git 依赖' if kind == 'git' else '添加依赖')
        self.update_packaging_controls()

    def update_packaging_controls(self, *args):
        for button in self.git_shortcuts.values():
            button.setEnabled(not self.dependency_busy and not self.dependency_unbundled.isChecked())
        self.dependency_unbundled.setToolTip('默认随构建打包。勾选后 dev/run 照常加载，build/package 排除；框架快捷入口需要随业务代码发布，勾选时不可使用。')

    def add_preset_dependency(self, preset, source=None, script_dir=None, choose_script=False):
        if self.dependency_busy:
            return
        from ..frameworks import framework_preview, script_directories
        try:
            candidates = script_directories(self.base_dir)
            if choose_script or (script_dir is None and len(candidates) > 1):
                script_dir, accepted = QInputDialog.getItem(
                    self, '选择所属 Mod', '脚本目录（新目录将生成入口，已有代码不改写）',
                    candidates or ['MyScript'], 0, True)
                if not accepted:
                    return
            if self.dependency_unbundled.isChecked():
                raise DependencyError('框架快捷入口会生成需要该依赖的业务入口，请取消“不随构建打包”；辅助代码可在 Git 表单中添加。')
            preview = framework_preview(self.base_dir, preset, script_dir, source)
            self.dependency_kind.setCurrentIndex(self.dependency_kind.findData('git'))
            from ..framework_presets import FRAMEWORK_PRESETS
            descriptor = FRAMEWORK_PRESETS[preset]
            values = {'git': preview['source'], 'name': preview['dependency'], 'ref': preview['rev'],
                      'subdir': descriptor['subdir'], 'target': preview['target']}
            for key, value in values.items():
                self.git_fields[key].setText(value)
                self.git_fields[key].setCursorPosition(0)
            self.git_kind.setCurrentIndex(self.git_kind.findData(descriptor['kind']))
            self.log(f"准备 Git 依赖 {preview['title']} → {preview['target']}；已有业务代码保留", 'info')
            self._start_dependency_operation('preset', preset=preset, script_dir=preview['script_dir'], source=source)
        except (DependencyError, OSError, ValueError) as exc:
            self.log(str(exc), 'error')

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
        self.controller.set_workspace_busy(busy)
        for widget in (self.dependency_kind, self.dependency_unbundled, self.new_dep_input, self.local_path_input,
                       self.browse_dependency_btn, self.absolute_path_check, self.add_dep_btn,
                       self.sync_dependencies_btn, self.preview_release_btn, *self.git_shortcuts.values(),
                       self.git_kind, *self.git_fields.values()):
            widget.setEnabled(not busy)
        self.remove_dep_btn.setEnabled(not busy and bool(self.dependency_list.selectedItems()))
        self.update_packaging_controls()
        selected = self.dependency_list.currentItem()
        self.change_packaging_btn.setEnabled(not busy and selected is not None and selected.data(Qt.ItemDataRole.UserRole).kind in ("local", "git"))
        self.new_btn.setEnabled(not busy and self.all_packs is not None)
        self.edit_btn.setEnabled(not busy and self.all_packs is not None and 'editor' in self.backend.capabilities)
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
        entry = item.data(Qt.ItemDataRole.UserRole)
        self.change_packaging_btn.setEnabled(not self.dependency_busy and entry.kind in ('local', 'git'))

    def change_dependency_packaging(self):
        item = self.dependency_list.currentItem()
        if self.dependency_busy or item is None:
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        if entry.kind not in ('local', 'git'):
            return
        labels = ['随构建打包（默认，unbundled=false）', '不随构建打包（unbundled=true）']
        selected, accepted = QInputDialog.getItem(self, '更改打包设置', entry.value + '\ndev/run 均加载；修改后需重启会话。', labels, 1 if entry.unbundled else 0, False)
        if not accepted:
            return
        unbundled = selected == labels[1]
        try:
            self.dependency_service.set_unbundled(entry, unbundled)
            self.log('打包设置已更新：' + selected + '；重启会话后应用。', 'success')
            self.refresh_dependencies()
            self.reload_runtime_dependencies()
        except (DependencyError, OSError, ValueError) as exc:
            self.log(str(exc), 'error')

    def create_new_instance(self):
        self.confirm_new_instance()

    def confirm_new_instance(self, config=None):
        if self.is_busy() or self.controller.session:
            self.log('请先保存退出当前游戏，再创建实例。', 'warning'); return
        from .world_config import WorldConfigDialog
        restrictions = self.backend.world_option_restrictions()
        dialog = WorldConfigDialog(self.current_project, self, config=config, restrictions=restrictions)
        if dialog.exec() == WorldConfigDialog.DialogCode.Accepted:
            self.start_game_thread(world_config=dialog.cppconfig())

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
        
        self.log(f"🚀 正在启动游戏实例: {level_id[:8]}...")
        
        # 使用QThread启动游戏，避免UI卡死
        self.start_game_thread(level_id)

    def run_dual_clients(self):
        if self.is_busy(): return
        if 'local-dual-client-manual' not in self.backend.capabilities:
            self.log('当前平台运行包尚不支持从游戏卡片加入本地主机。', 'warning'); return
        if self.mcs_auth:
            self.log('双客户端联调使用无认证开发身份，请关闭 MCS 身份模式后启动。', 'warning'); return
        rows = self.instance_table.selectionModel().selectedRows()
        identity = self.instances[rows[0].row()]['level_id'] if rows else None
        self.controller.start(identity, clients=2)

    def connect_server(self):
        if self.is_busy(): return
        host, accepted = QInputDialog.getText(self, '连接服务器', '服务器 IP 或域名（无认证开发服务器）')
        if not accepted or not host.strip(): return
        port, accepted = QInputDialog.getInt(self, '服务器端口', '端口', 19132, 1, 65535)
        if not accepted: return
        clients, accepted = QInputDialog.getItem(self, '玩家数量', '本机客户端', ['2', '1'], 0, False)
        if accepted: self.controller.connect_server(host.strip(), port, int(clients))

    def attach_existing(self):
        if self.is_busy(): return
        from ..runtime import groups, occupancy
        from ..mcstudio import sessions
        choices = []
        grouped = set()
        for value in groups.list_groups(self.base_dir):
            if value['state'] in ('ready', 'running', 'waiting_for_join', 'joining', 'partial', 'starting'):
                choices.append(('联调组 ' + value['group'][:8] + ' · ' + value['state'], value))
                grouped.update(m.get('session') for m in value['members'])
        for data in occupancy.active(self.base_dir):
            if data['session'] not in grouped and data.get('game'):
                choices.append(('会话 ' + data['session'][:8], dict(sessions.handoff(data), already_running=True)))
        if not choices:
            self.log('没有运行中的会话。', 'info'); return
        label, accepted = QInputDialog.getItem(self, '接管已有会话', '选择目标', [x[0] for x in choices], 0, False)
        if accepted:
            result = next(value for name, value in choices if name == label)
            self.controller.attach(dict(result, already_running=True))

    def create_from_cppconfig(self):
        path, _ = QFileDialog.getOpenFileName(self, '从 cppconfig 新建', self.base_dir,
                                             'cppconfig (*.cppconfig);;JSON (*.json)')
        if path:
            self.start_from_config(path)

    def create_from_selected(self):
        rows = self.instance_table.selectionModel().selectedRows()
        if not rows:
            self.log('请先选择实例。', 'warning'); return
        self.start_from_config(self.instances[rows[0].row()]['config_path'])

    def start_from_config(self, path):
        from ..mcstudio.runtime_cppconfig import creation_settings
        try:
            config = {'world_info': creation_settings(path)}
        except (OSError, ValueError) as error:
            self.log(str(error), 'error'); return
        self.confirm_new_instance(config)

    def start_game_thread(self, level_id=None, world_config=None):
        if self.is_busy() or self.controller.session:
            self.log('请先保存退出当前游戏，再启动其他实例。', 'warning'); return
        if level_id is None and self.backend.managed_install and not self.backend.diagnose(self.base_dir).get('ok'):
            self.prepare_engine(auto_install=True)
            if not self.backend.diagnose(self.base_dir).get('ok'):
                self.log('运行资源尚未准备完成，可通过“运行环境”继续安装。', 'warning'); return
        identity = None
        if self.mcs_auth:
            from ..mcstudio.mcs_auth import acquire_identity, AuthError
            try:
                identity = acquire_identity(interactive=True)
            except AuthError as exc:
                self.log(str(exc), 'error'); return
        self.controller.start(level_id, identity, **({'world_config': world_config} if world_config is not None else {}))

    @Slot(object)
    def on_game_started(self, result):
        self.refresh_instances()
        self.log_tabs.setCurrentIndex(1)
        self.show_log_window()
        if self.watch_on_start.isChecked() and result.get('ok', True):
            self.controller.set_watching(True)

    @Slot()
    def show_log_window(self):
        if self.log_window is None:
            self.log_window = SessionLogWindow(self.controller, self)
        self.log_window.show()

    @Slot()
    def update_session_state(self):
        self.session_label.setText(self.controller.status)
        self.float_log_btn.setEnabled(bool(self.controller.session))
        if not self.controller.session and self.log_window: self.log_window.close()
        if self.closing and not self.is_busy() and not self.controller.watcher:
            QTimer.singleShot(0, self.close)

    @Slot(object)
    def on_game_stopped(self, result):
        if self.closing: QTimer.singleShot(0, self.close)

    @Slot(str)
    def task_failed(self, message):
        self.closing = False

    def create_mod(self):
        from ..utils.project_setup import find_behavior_pack_dir
        from ..minecraft.template.mod_template import open_ui_crate_mod
        behavior = find_behavior_pack_dir(self.base_dir)
        if not behavior:
            self.log('未找到行为包，请先初始化 Addon。', 'error'); return
        self.mod_window = open_ui_crate_mod(behavior, run_event_loop=False)
        self.mod_window.setParent(self, Qt.WindowType.Window)
        self.mod_window.show()

    def prepare_engine(self, auto_install=False):
        if self.is_busy(): return
        if self.backend.managed_install:
            from .engine_setup import EngineSetupDialog
            EngineSetupDialog(self.backend, self, auto_install=auto_install).exec()
        else:
            self.controller.run_task(lambda: self.backend.diagnose(self.base_dir, self.controller.engine_overrides))

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
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.log(f"🗑️ 正在删除实例: {level_id[:8]}...")
            force = True  # 使用强制模式避免在函数内部显示确认对话框
            try: self.backend.delete_instances(self.base_dir, level_id)
            except Exception as error:
                self.log(str(error), 'error'); return
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
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # 最终确认
            reply = QMessageBox.critical(
                self,
                "最终确认",
                "⚠️ 最后确认: 真的要删除所有实例吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.log("🗑️ 正在清空所有游戏实例...")
                try: self.backend.delete_instances(self.base_dir)
                except Exception as error:
                    self.log(str(error), 'error'); return
                self.log("✅ 已成功清空所有游戏实例", "success")
                self.refresh_instances()
    
    def log(self, message, level='info'):
        self.controller.log(message, level)

    def open_mc_editor(self):
        """打开MC Studio Editor编辑器"""
        if not os.path.isfile(os.path.join(self.base_dir, 'pyproject.toml')):
            self.log("❌ 项目尚未初始化，无法打开编辑器", "error")
            return
            
        if self.reload_runtime_dependencies():
            open_edit(self.base_dir, engine_overrides=self.controller.engine_overrides)
    
    def remove_selected_dependency(self):
        if self.dependency_busy:
            return
        selected = self.dependency_list.selectedItems()
        if not selected:
            return
        entry = selected[0].data(Qt.ItemDataRole.UserRole)
        note = {'local': '仅移除引用，源目录保留。', 'package': '仅移除配置，不卸载 Python 包。',
                'code': '仅移除代码库声明，缓存与入口保留。请检查业务代码中的框架导入。',
                'git': '仅移除Git依赖声明，缓存与入口保留。请检查业务代码中的依赖导入。'}[entry.kind]
        if QMessageBox.question(self, '确认移除依赖', f'{entry.value}\n{note}',
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
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
        if self.dependency_kind.currentData() == 'git':
            self._start_dependency_operation('git')
            return
        if self.dependency_kind.currentData() == 'local':
            value = self.local_path_input.text().strip()
            try:
                if not value:
                    raise DependencyError('请输入或选择本地 Addon 目录')
                saved = path_for_storage(self.base_dir, value, self.absolute_path_check.isChecked())
                changed, warnings = self.dependency_service.add_local(saved, unbundled=self.dependency_unbundled.isChecked())
                self.log('依赖已添加' if changed else '依赖已存在', 'success')
                for warning in warnings:
                    self.log(warning, 'warning')
                self.log("打包设置：" + ("不随构建打包（unbundled=true）" if self.dependency_unbundled.isChecked() else "随构建打包（unbundled=false）") + "；运行中的会话需重启。", "info")
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
        self.install_thread.finished.connect(self.on_dependency_finished)
        self.install_thread.start()

    def preview_release_dependencies(self):
        try:
            selection = self.dependency_service.resolve(purpose='release').selection()
            lines = []
            for item in selection['dependencies']:
                lines.append(item['name'] + ' · 随 build/package 发布')
                lines.extend('  ' + ' → '.join(chain) for chain in item['via'])
            lines.extend(item['dependency'] + ' · 已排除（unbundled=true）' for item in selection['excluded'])
            dialog = QMessageBox(self)
            dialog.setWindowTitle('发布依赖')
            dialog.setText('build/package 仅包含随发布的依赖，共 %d 个依赖节点。' % len(selection['dependencies']))
            dialog.setInformativeText('unbundled 节点若同时被普通打包依赖引用，仍会随发布；展开详情查看引用链。')
            dialog.setDetailedText('\n'.join(lines) or '没有外部发布依赖。')
            dialog.exec()
        except (DependencyError, OSError, ValueError) as exc:
            self.log(str(exc), 'error')

    def sync_dependencies(self):
        if not self.dependency_busy:
            self._start_dependency_operation('sync')

    def _start_dependency_operation(self, operation, preset=None, script_dir=None, source=None):
        self.set_dependency_busy(True)
        self.install_thread = DependencyTaskThread(
            self.base_dir, operation, script_dir, source, preset=preset,
            git_options={**{key: field.text().strip() or None for key, field in self.git_fields.items()}, 'kind': self.git_kind.currentData(), 'unbundled': self.dependency_unbundled.isChecked()})
        self.install_thread.log_message.connect(self.log)
        self.install_thread.result.connect(self.on_dependency_installed)
        self.install_thread.finished.connect(self.on_dependency_finished)
        self.install_thread.start()

    @Slot()
    def on_dependency_finished(self):
        self.set_dependency_busy(False)

    @Slot(bool, str)
    def on_dependency_installed(self, success, message):
        self.log(message, 'success' if success else 'error')
        if success:
            self.load_available_packages()
            self.new_dep_input.setCurrentText('')
        self.refresh_dependencies()
        self.reload_runtime_dependencies()


class DependencyTaskThread(QThread):
    """网络同步在后台；与CLI共用同一个框架/依赖服务。"""
    log_message = Signal(str, str)
    result = Signal(bool, str)

    def __init__(self, project_dir, operation='framework', script_dir=None, source=None, preset=None, git_options=None):
        super().__init__()
        self.project_dir, self.operation = project_dir, operation
        self.script_dir, self.source = script_dir, source
        self.preset, self.git_options = preset, git_options or {}

    def run(self):
        try:
            if self.operation == 'sync':
                from ..commands.sync_cmd import sync_project
                self.log_message.emit('正在恢复项目声明的固定版本代码库...', 'info')
                result = sync_project(self.project_dir)
                message = f"同步完成：{result['git_projects']} 个Git项目、{result['code_libraries']} 个兼容代码库"
            elif self.operation == 'git':
                options = dict(self.git_options)
                url = options.pop('git', None)
                if not url:
                    raise DependencyError('请输入Git URL')
                if options.get('kind') == 'auto':
                    options['kind'] = None
                result = DependencyService(self.project_dir).add_git(url, **options)
                from ..dependency_feedback import packaging_summary
                message = f"Git项目已注册：{result['dependency']}，提交 {result['rev'][:12]}；" + packaging_summary(result)
            else:
                self.log_message.emit('正在准备框架外部依赖...', 'info')
                result = DependencyService(self.project_dir).add_framework(self.preset, self.script_dir, self.source)
                for warning in result['warnings']:
                    self.log_message.emit(warning, 'warning')
                message = f"框架已准备：{result['target']}；其他开发者执行 mcpy sync 即可恢复"
            self.result.emit(True, message)
        except Exception as exc:
            self.result.emit(False, f'框架准备失败: {exc}')


class DependencyInstallThread(QThread):
    """后台安装成功后才保存声明，并显式报告结果。"""
    log_message = Signal(str, str)
    result = Signal(bool, str)

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


def show_run_ui(base_dir=None, mcs_auth=False, autorun=False, new=False, instance=None, engine_overrides=None, world_config=None):
    """显示游戏实例管理UI"""
    app = create_application(sys.argv)
    # Keep Qt's platform style and system palette for the project and floating controls.
    
    window = GameInstanceManager(base_dir or os.getcwd(), mcs_auth=mcs_auth, engine_overrides=engine_overrides)
    window.show()
    if autorun:
        identity = instance or (window.instances[0]['level_id'] if window.instances and not new else None)
        QTimer.singleShot(0, lambda: window.start_game_thread(identity) if identity else window.confirm_new_instance(world_config))
    import signal
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        for sig in previous: signal.signal(sig, lambda *_: window.close())
        return app.exec()
    finally:
        for sig, handler in previous.items(): signal.signal(sig, handler)


if __name__ == "__main__":
    show_run_ui()

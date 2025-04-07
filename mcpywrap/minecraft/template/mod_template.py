# -*- coding: utf-8 -*-

import os
import sys
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                            QLabel, QLineEdit, QPushButton, QFormLayout, 
                            QGroupBox, QMessageBox, QTreeWidget, QTreeWidgetItem,
                            QSplitter, QFrame)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QIcon, QPalette, QColor, QFontDatabase
from .generate_mod_files import generate_mod_framework

class FileStructurePreview(QFrame):
    """文件结构预览组件"""
    
    def __init__(self, parent=None, is_dark_mode=False):
        super(FileStructurePreview, self).__init__(parent)
        self.setObjectName("treeFrame")
        
        # 设置颜色
        self.is_dark_mode = is_dark_mode
        self.folder_color = "#6bbbff" if is_dark_mode else "#4a86cf"
        self.file_color = "#e1e1e1" if is_dark_mode else "#888888"
        self.path_color = "#aaaaaa" if is_dark_mode else "#999999"
        
        # 创建布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # 创建树形视图
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.setIndentation(20)
        self.tree_widget.setSelectionMode(QTreeWidget.NoSelection)  # 禁用选择
        self.tree_widget.setFocusPolicy(Qt.NoFocus)  # 防止获得焦点
        
        layout.addWidget(self.tree_widget)
    
    def update_preview(self, behavior_pack_path, mod_name, root_dir_name="myScript", server_system_name=None, client_system_name=None):
        """更新文件结构预览
        
        Args:
            behavior_pack_path: 行为包路径
            mod_name: 模组名称
            root_dir_name: 顶级目录名称
            server_system_name: 服务端系统名称
            client_system_name: 客户端系统名称
        """
        self.tree_widget.clear()
        
        # 如果模组名为空，使用默认名
        if not mod_name:
            mod_name = "MyMod"
            
        if not server_system_name:
            server_system_name = f"{mod_name}ServerSystem"
            
        if not client_system_name:
            client_system_name = f"{mod_name}ClientSystem"
        
        # 创建根目录项 (行为包路径)
        root_path = os.path.basename(behavior_pack_path)
        root_item = QTreeWidgetItem(self.tree_widget, [root_path])
        root_item.setForeground(0, QColor(self.folder_color))
        root_item.setExpanded(True)
        
        # 创建顶级目录 (使用用户指定的目录名)
        script_item = QTreeWidgetItem(root_item, [root_dir_name])
        script_item.setForeground(0, QColor(self.folder_color))
        script_item.setExpanded(True)
        
        # 创建配置文件和主文件
        config_item = QTreeWidgetItem(script_item, ["config.py"])
        config_item.setForeground(0, QColor(self.file_color))
        
        modmain_item = QTreeWidgetItem(script_item, ["modMain.py"])
        modmain_item.setForeground(0, QColor(self.file_color))
        
        init_item = QTreeWidgetItem(script_item, ["__init__.py"])
        init_item.setForeground(0, QColor(self.file_color))
        
        # 创建服务端目录
        server_dir = QTreeWidgetItem(script_item, ["server"])
        server_dir.setForeground(0, QColor(self.folder_color))
        server_dir.setExpanded(True)
        
        server_system_file = QTreeWidgetItem(server_dir, [f"{server_system_name}.py"])
        server_system_file.setForeground(0, QColor(self.file_color))
        
        server_init = QTreeWidgetItem(server_dir, ["__init__.py"])
        server_init.setForeground(0, QColor(self.file_color))
        
        # 创建客户端目录
        client_dir = QTreeWidgetItem(script_item, ["client"])
        client_dir.setForeground(0, QColor(self.folder_color))
        client_dir.setExpanded(True)
        
        client_system_file = QTreeWidgetItem(client_dir, [f"{client_system_name}.py"])
        client_system_file.setForeground(0, QColor(self.file_color))
        
        client_init = QTreeWidgetItem(client_dir, ["__init__.py"])
        client_init.setForeground(0, QColor(self.file_color))

def open_ui_crate_mod(behavior_pack_path):
    """创建一个交互式UI，用于生成Minecraft Mod基础框架
    
    Args:
        behavior_pack_path: 行为包目录的路径
    """
    # 在创建 QApplication 之前启用高 DPI 缩放
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    app = QApplication(sys.argv) if not QApplication.instance() else QApplication.instance()
    
    # 为已存在的应用程序实例启用自动缩放
    if QApplication.instance():
        if hasattr(Qt, 'AA_EnableHighDpiScaling'):
            QApplication.instance().setAttribute(Qt.AA_EnableHighDpiScaling, True)
        if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
            QApplication.instance().setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    # 设置优先使用的中文字体列表
    preferred_fonts = [
        "Microsoft YaHei UI", "微软雅黑",  # 微软雅黑UI/微软雅黑
        "Source Han Sans CN", "思源黑体",  # 思源黑体
        "Noto Sans CJK SC",               # Noto Sans中文字体
        "PingFang SC", "苹方-简",          # 苹方字体(macOS)
        "Hiragino Sans GB", "冬青黑体",     # 冬青黑体
        "Microsoft JhengHei", "微軟正黑體", # 微软正黑
        "SimHei", "黑体"                   # 最后回退到黑体
    ]
    
    # 获取系统中可用的字体
    font_db = QFontDatabase()
    available_fonts = font_db.families()
    
    # 查找第一个可用的首选字体
    selected_font = None
    for font_name in preferred_fonts:
        for available_font in available_fonts:
            if font_name.lower() in available_font.lower():
                selected_font = available_font
                break
        if selected_font:
            break
    
    # 设置全局字体
    if selected_font:
        font = QFont(selected_font, 9)  # 9号字体大小比较合适
    else:
        font = QFont()  # 使用系统默认字体
        
    app.setFont(font)
    
    # 主窗口
    window = QWidget()
    window.setWindowTitle("Minecraft Mod 创建工具")
    window.setMinimumWidth(900)  # 增加窗口宽度以适应目录树
    window.setMinimumHeight(600)  # 设置窗口最小高度
    
    # 检测是否为深色模式
    palette = app.palette()
    is_dark_mode = palette.color(QPalette.Window).lightness() < 128
    
    # 根据深色/浅色模式设置样式
    if is_dark_mode:
        window.setStyleSheet("""
            QWidget {
                background-color: #292929;
                color: #ffffff;
                font-size: 13px;
            }
            QPushButton {
                background-color: #0a84ff;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #006cd9;
            }
            QPushButton:pressed {
                background-color: #0054a8;
            }
            QLineEdit {
                padding: 8px;
                background-color: #3c3c3c;
                color: #ffffff;
                border: 1px solid #555555;
                border-radius: 6px;
                selection-background-color: #0a84ff;
            }
            QLineEdit:focus {
                border: 1px solid #0a84ff;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #555555;
                border-radius: 8px;
                margin-top: 0px;
                padding-top: 15px;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
            }
            QTreeWidget {
                background-color: #333333;
                border-radius: 6px;
                outline: none;
            }
            QTreeWidget::item {
                padding: 4px;
                border-radius: 4px;
            }
            QTreeWidget::item:selected {
                background-color: rgba(10, 132, 255, 0.3);
            }
            QTreeWidget::item:hover {
                background-color: rgba(255, 255, 255, 0.05);
            }
            QSplitter::handle {
                background-color: #444444;
                width: 6px;
            }
            QHeaderView::section {
                background-color: #333333;
                color: #ffffff;
                padding: 6px;
                border: none;
                border-right: 1px solid #555555;
                border-bottom: 1px solid #555555;
            }
            QFrame#treeFrame {
                background-color: #333333;
                border-radius: 8px;
                border: 1px solid #555555;
                padding: 5px;
            }
        """)
    else:
        window.setStyleSheet("""
            QWidget {
                background-color: #f5f5f5;
                color: #333333;
                font-size: 13px;
            }
            QPushButton {
                background-color: #0a84ff;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #006cd9;
            }
            QPushButton:pressed {
                background-color: #0054a8;
            }
            QLineEdit {
                padding: 8px;
                border: 1px solid #ddd;
                border-radius: 6px;
                background-color: #ffffff;
                selection-background-color: #0a84ff;
            }
            QLineEdit:focus {
                border: 1px solid #0a84ff;
            }
            QGroupBox {
                font-weight: bold;
                border: 1px solid #ddd;
                border-radius: 8px;
                margin-top: 0px;
                padding-top: 15px;
                color: #333333;
            }
            QTreeWidget {
                background-color: #ffffff;
                border-radius: 6px;
                outline: none;
            }
            QTreeWidget::item {
                padding: 4px;
                border-radius: 4px;
            }
            QTreeWidget::item:selected {
                background-color: rgba(10, 132, 255, 0.1);
                color: #333333;
            }
            QTreeWidget::item:hover {
                background-color: rgba(0, 0, 0, 0.03);
            }
            QSplitter::handle {
                background-color: #dddddd;
                width: 6px;
            }
            QHeaderView::section {
                background-color: #f5f5f5;
                padding: 6px;
                border: none;
                border-right: 1px solid #ddd;
                border-bottom: 1px solid #ddd;
            }
            QFrame#treeFrame {
                background-color: white;
                border-radius: 8px;
                border: 1px solid #ddd;
                padding: 5px;
            }
        """)
    
    # 创建分割器以放置左右两侧内容
    splitter = QSplitter(Qt.Horizontal)
    
    # 左侧表单部分
    left_widget = QWidget()
    main_layout = QVBoxLayout(left_widget)
    
    # 创建一个组框来包含所有输入字段
    group_box = QGroupBox()
    group_layout = QFormLayout()
    group_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)  # 允许字段扩展
    group_layout.setLabelAlignment(Qt.AlignLeft)  # 标签左对齐
    group_layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)  # 表单左上对齐
    group_layout.setSpacing(10)  # 增加表单项间距

    # 添加顶级目录名称输入框
    root_dir_input = QLineEdit()
    root_dir_input.setPlaceholderText("脚本目录名")
    root_dir_input.setText("MyScript")  # 默认值
    root_dir_input.setMinimumWidth(300)
    
    # 创建输入字段
    mod_name_input = QLineEdit()
    mod_name_input.setPlaceholderText("必填: 例如 MyFirstMod")
    mod_name_input.setMinimumWidth(300)  # 设置输入框最小宽度
    
    mod_version_input = QLineEdit()
    mod_version_input.setPlaceholderText("例如: 1.0")
    mod_version_input.setText("1.0")  # 默认版本
    mod_version_input.setMinimumWidth(300)  # 设置输入框最小宽度
    
    server_system_name_input = QLineEdit()
    server_system_name_input.setPlaceholderText("例如: MyServerSystem")
    server_system_name_input.setMinimumWidth(300)  # 设置输入框最小宽度
    
    # 类路径输入框设为只读
    server_system_cls_input = QLineEdit()
    server_system_cls_input.setPlaceholderText("自动生成")
    server_system_cls_input.setMinimumWidth(300)
    server_system_cls_input.setReadOnly(True)  # 设置为只读
    if is_dark_mode:
        server_system_cls_input.setStyleSheet("background-color: #2a2a2a; color: #aaaaaa;")
    else:
        server_system_cls_input.setStyleSheet("background-color: #f0f0f0; color: #888888;")
    
    client_system_name_input = QLineEdit()
    client_system_name_input.setPlaceholderText("例如: MyClientSystem")
    client_system_name_input.setMinimumWidth(300)  # 设置输入框最小宽度
    
    # 类路径输入框设为只读
    client_system_cls_input = QLineEdit()
    client_system_cls_input.setPlaceholderText("自动生成")
    client_system_cls_input.setMinimumWidth(300)
    client_system_cls_input.setReadOnly(True)  # 设置为只读
    if is_dark_mode:
        client_system_cls_input.setStyleSheet("background-color: #2a2a2a; color: #aaaaaa;")
    else:
        client_system_cls_input.setStyleSheet("background-color: #f0f0f0; color: #888888;")
    
    # 添加到布局
    group_layout.addRow(QLabel("<b>脚本目录名 *:</b>"), root_dir_input)  # 新增顶级目录名称字段
    group_layout.addRow(QLabel("<b>Mod 名称 *:</b>"), mod_name_input)
    group_layout.addRow(QLabel("<b>Mod 版本:</b>"), mod_version_input)
    group_layout.addRow(QLabel("<b>服务端系统名:</b>"), server_system_name_input)
    group_layout.addRow(QLabel("<b>服务端系统类路径:</b>"), server_system_cls_input)
    group_layout.addRow(QLabel("<b>客户端系统名:</b>"), client_system_name_input)
    group_layout.addRow(QLabel("<b>客户端系统类路径:</b>"), client_system_cls_input)
    
    group_box.setLayout(group_layout)
    main_layout.addWidget(QLabel("<b>Mod 配置</b>"))
    main_layout.addWidget(group_box)
    
    # 创建按钮
    btn_layout = QHBoxLayout()
    create_button = QPushButton("创建 Mod 框架")
    btn_layout.addStretch()
    btn_layout.addWidget(create_button)
    
    main_layout.addLayout(btn_layout)
    main_layout.addStretch()
    
    # 右侧目录结构预览部分
    right_widget = QWidget()
    right_layout = QVBoxLayout(right_widget)
    
    # 目录结构标题
    right_layout.addWidget(QLabel("<b>预计创建的文件结构:</b>"))
    
    # 创建文件结构预览组件
    file_preview = FileStructurePreview(is_dark_mode=is_dark_mode)
    right_layout.addWidget(file_preview)
    
    # 添加左右部分到分割器
    splitter.addWidget(left_widget)
    splitter.addWidget(right_widget)
    splitter.setSizes([450, 450])  # 设置初始宽度比例
    
    # 主布局
    window_layout = QVBoxLayout(window)
    window_layout.addWidget(splitter)
    
    # 自动填充功能
    def update_dependent_fields():
        mod_name = mod_name_input.text()
        root_dir_name = root_dir_input.text() or "myScript"
        
        if (mod_name):
            # 如果用户没有手动修改过，则自动更新
            if not server_system_name_input.isModified():
                server_system_name_input.setText(f"{mod_name}ServerSystem")
            
            if not client_system_name_input.isModified():
                client_system_name_input.setText(f"{mod_name}ClientSystem")
            
            # 总是更新类路径，因为它们不可手动编辑
            server_name = server_system_name_input.text() or f"{mod_name}ServerSystem"
            client_name = client_system_name_input.text() or f"{mod_name}ClientSystem"
            server_system_cls = f"{root_dir_name}.server.{server_name}.{server_name}"
            client_system_cls = f"{root_dir_name}.client.{client_name}.{client_name}"
            
            server_system_cls_input.setText(server_system_cls)
            client_system_cls_input.setText(client_system_cls)
        
        # 更新树视图
        file_preview.update_preview(
            behavior_pack_path, 
            mod_name_input.text(),
            root_dir_name,
            server_system_name_input.text(),
            client_system_name_input.text()
        )
    
    # 连接信号和槽
    mod_name_input.textChanged.connect(update_dependent_fields)
    root_dir_input.textChanged.connect(update_dependent_fields)  # 连接顶级目录名称输入框
    server_system_name_input.textChanged.connect(update_dependent_fields)
    client_system_name_input.textChanged.connect(update_dependent_fields)
    
    # 初始化树视图
    update_dependent_fields()
    
    # 创建Mod框架
    def create_mod_framework():
        root_dir_name = root_dir_input.text()
        if not root_dir_name:
            QMessageBox.warning(window, "错误", "脚本目录名称不能为空!")
            return

        mod_name = mod_name_input.text()
        if not mod_name:
            QMessageBox.warning(window, "错误", "Mod名称不能为空!")
            return
        
        mod_version = mod_version_input.text()
        server_system_name = server_system_name_input.text()
        server_system_cls = server_system_cls_input.text()
        client_system_name = client_system_name_input.text()
        client_system_cls = client_system_cls_input.text()
        
        # 调用生成函数
        success, message = generate_mod_framework(
            behavior_pack_path,
            mod_name,
            mod_version,
            server_system_name,
            server_system_cls,
            client_system_name,
            client_system_cls,
            root_dir_name  # 传递顶级目录名称
        )
        
        if success:
            QMessageBox.information(window, "成功", message)
            window.close()
        else:
            QMessageBox.critical(window, "错误", message)
    
    create_button.clicked.connect(create_mod_framework)
    
    # 显示窗口
    window.show()
    
    if not QApplication.instance():
        sys.exit(app.exec_())
    else:
        app.exec_()

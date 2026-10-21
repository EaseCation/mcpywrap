"""Compact instance confirmation backed by the existing cppconfig field model."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QComboBox, QLineEdit,
    QCheckBox, QGroupBox, QDialogButtonBox, QLabel, QScrollArea, QWidget, QSpinBox, QToolButton)
from ..mcstudio.runtime_cppconfig import gen_runtime_config, creation_settings, RULE_LABELS





class WorldConfigDialog(QDialog):
    def __init__(self, name, parent=None, config=None, restrictions=None):
        super().__init__(parent)
        self.setWindowTitle('新建测试实例')
        self.setMinimumWidth(380)
        defaults = gen_runtime_config('', name, 'preview', '', '', [], [])['world_info']
        if config is not None:
            supplied = creation_settings(config)
            defaults['cheat_info'].update(supplied.pop('cheat_info', {}))
            defaults.update(supplied)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary)
        self.more = QToolButton()
        self.more.setText('世界设置')
        self.more.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.more.setArrowType(Qt.ArrowType.RightArrow)
        self.more.setCheckable(True)
        layout.addWidget(self.more)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMaximumHeight(420)
        self.details = QWidget()
        body = QVBoxLayout(self.details)
        form = QFormLayout()
        body.addLayout(form)
        self.fields = {}
        for key, label in [('name', '世界名称'), ('seed', '种子')]:
            widget = QLineEdit(defaults[key])
            if key == 'seed': widget.setPlaceholderText('留空由游戏生成')
            widget.textChanged.connect(self.update_summary)
            form.addRow(label, widget); self.fields[key] = widget
        for key, label, items in (
            ('world_type', '地形', [('无限', 1), ('平坦', 2)]),
            ('game_type', '模式', [('生存', 0), ('创造', 1), ('冒险', 2)]),
            ('difficulty', '难度', [('和平', 0), ('简单', 1), ('普通', 2), ('困难', 3)]),
            ('permission_level', '玩家权限', [('访客', 0), ('成员', 1), ('管理员', 2)])):
            widget = QComboBox()
            for title, value in items: widget.addItem(title, value)
            widget.setCurrentIndex(widget.findData(defaults[key]))
            widget.currentIndexChanged.connect(self.update_summary)
            form.addRow(label, widget); self.fields[key] = widget
        for key, label in [('cheat', '开启作弊'), ('start_with_map', '初始地图'), ('bonus_items', '奖励箱')]:
            widget = QCheckBox(label); widget.setChecked(defaults[key])
            widget.toggled.connect(self.update_summary)
            form.addRow(widget); self.fields[key] = widget
        rules = QGroupBox('游戏规则')
        rules_form = QFormLayout(rules)
        self.rules = {}
        for key, label in RULE_LABELS.items():
            if key == 'random_tick_speed':
                widget = QSpinBox(); widget.setRange(0, 2147483647)
                widget.setValue(defaults['cheat_info'][key])
                rules_form.addRow(label, widget)
            else:
                widget = QCheckBox(label); widget.setChecked(defaults['cheat_info'][key])
                rules_form.addRow(widget)
            reason = (restrictions or {}).get('cheat_info.' + key)
            if reason:
                widget.setEnabled(False)
                widget.setToolTip(reason)
                note = QLabel(reason); note.setWordWrap(True)
                rules_form.addRow(note)
            self.rules[key] = widget
        body.addWidget(rules)
        note = QLabel('设置仅属于本实例。创建后，已有世界的实际设置由存档保存。')
        note.setWordWrap(True);body.addWidget(note)
        self.scroll.setWidget(self.details)
        layout.addWidget(self.scroll)
        self.more.toggled.connect(self.expand_settings)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        confirm = buttons.button(QDialogButtonBox.StandardButton.Ok)
        confirm.setText('创建并运行'); confirm.setDefault(True)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.more.setChecked(False); self.scroll.hide()
        self.update_summary()
        confirm.setFocus()

    def expand_settings(self, expanded):
        self.scroll.setVisible(expanded)
        self.more.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.adjustSize()

    def update_summary(self):
        if not all(key in self.fields for key in ('name', 'world_type', 'game_type', 'difficulty', 'cheat')):
            return
        description = ' · '.join(self.fields[key].currentText() for key in ('world_type', 'game_type', 'difficulty'))
        description += ' · ' + ('开启作弊' if self.fields['cheat'].isChecked() else '关闭作弊')
        self.summary.setText('创建并运行「%s」\n%s' % (self.fields['name'].text(), description))

    def cppconfig(self):
        info = {}
        for key, widget in self.fields.items():
            info[key] = widget.text() if isinstance(widget, QLineEdit) else (
                widget.currentData() if isinstance(widget, QComboBox) else widget.isChecked())
        info['cheat_info'] = {key: widget.value() if isinstance(widget, QSpinBox) else widget.isChecked()
                              for key, widget in self.rules.items()}
        return {'world_info': info}

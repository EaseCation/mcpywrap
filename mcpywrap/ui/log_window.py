"""共用的紧凑悬浮窗；默认只呈现一行状态，日志与操作按需展开。"""
from PySide6.QtCore import Qt, QSettings, Slot, QSize, QEvent
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPixmap, QPen, QPalette
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                              QLabel, QTabWidget, QMenu, QWidgetAction, QSizePolicy, QToolButton)
from .log_view import LogView
from .session_views import SessionControls, PythonConsole


class ElidedStatus(QLabel):
    """长状态不撑宽小窗，完整内容留在悬停提示中。"""
    def __init__(self):
        super().__init__()
        self.full_text = ''
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)

    def setText(self, text):
        self.full_text = text
        self.setToolTip(text)
        self._update_text()

    def _update_text(self):
        super().setText(self.fontMetrics().elidedText(self.full_text, Qt.TextElideMode.ElideRight, self.width()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_text()


class LogWindow(QMainWindow):
    def __init__(self, model, controls, parent=None, title='mcpy 调试'):
        super().__init__(parent, Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.settings = QSettings('MCPyWrap', 'StudioLogger')
        self.log_expanded = False
        self.expanded_size = QSize(540, 340)
        self.setWindowTitle(title)
        central = QWidget(); layout = QVBoxLayout(central); self.setCentralWidget(central)
        layout.setContentsMargins(6, 4, 6, 4); layout.setSpacing(4)
        row = QHBoxLayout(); row.setSpacing(4)
        self.status_label = ElidedStatus(); self.status_label.setText('未启动')
        row.addWidget(self.status_label, 1)
        self.toggle_btn = QPushButton('日志'); self.toggle_btn.setCheckable(True)
        self.toggle_btn.setToolTip('展开日志与 Python 控制台')
        self.toggle_btn.clicked.connect(self.toggle_log_view)
        self.actions_btn = QPushButton('操作')
        self.actions_menu = QMenu(self.actions_btn)
        action = QWidgetAction(self.actions_menu); action.setDefaultWidget(controls)
        self.actions_menu.addAction(action)
        self.actions_btn.setMenu(self.actions_menu)
        self.top = QToolButton(); self.top.setCheckable(True)
        self.top.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.top.setAccessibleName('置顶')
        self.top.setIconSize(QSize(16, 16))
        self.top.setIcon(self.pin_icon())
        self.top.setToolTip('取消置顶' if self.top.isChecked() else '保持小窗在游戏上方')
        self.top.toggled.connect(self.set_always_on_top)
        for button in (self.toggle_btn, self.actions_btn, self.top):
            button.setAttribute(Qt.WidgetAttribute.WA_MacSmallSize)
            row.addWidget(button)
        layout.addLayout(row)
        self.tabs = QTabWidget(); self.log_view = LogView(model, compact=True)
        self.tabs.addTab(self.log_view, '日志'); layout.addWidget(self.tabs)
        self.tabs.hide()
        self.resize(320, self.sizeHint().height())
        self.top.setChecked(self.settings.value('always_on_top', True, type=bool))
        position = self.settings.value('window_position')
        if position is not None and any(screen.availableGeometry().contains(position) for screen in self.screen().virtualSiblings()):
            self.move(position)
        else:
            screen = self.screen().availableGeometry(); self.move(screen.left()+20, screen.bottom()-self.height()-40)

    def fit_on_screen(self):
        area = self.screen().availableGeometry()
        frame = self.frameGeometry()
        self.move(max(area.left(), min(frame.left(), area.right()-frame.width()+1)),
                  max(area.top(), min(frame.top(), area.bottom()-frame.height()+1)))

    def pin_icon(self):
        """DPI-aware pin glyph; the native Qt tool button draws every control state."""
        icon = QIcon()
        for size in (16, 32):
            pixmap = QPixmap(size, size); pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.scale(size/20, size/20)
            color = self.top.palette().color(QPalette.ColorRole.ButtonText)
            painter.setPen(QPen(color, 1.5))
            painter.setBrush(color)
            path = QPainterPath(); path.moveTo(6, 3)
            for x, y in ((14, 3), (14, 5), (12, 5), (12, 10), (15, 13),
                         (5, 13), (8, 10), (8, 5), (6, 5)):
                path.lineTo(x, y)
            path.closeSubpath(); painter.drawPath(path)
            painter.drawLine(10, 13, 10, 18); painter.end()
            icon.addPixmap(pixmap)
        return icon

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_on_screen()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange) and hasattr(self, 'top'):
            self.top.setIcon(self.pin_icon())

    @Slot()
    def toggle_log_view(self):
        if self.log_expanded:
            self.expanded_size = self.size()
        self.log_expanded = not self.log_expanded
        self.tabs.setVisible(self.log_expanded)
        self.toggle_btn.setChecked(self.log_expanded)
        self.toggle_btn.setToolTip('收起日志' if self.log_expanded else '展开日志与 Python 控制台')
        self.centralWidget().layout().activate()
        self.layout().activate()
        if self.log_expanded:
            self.resize(self.expanded_size)
        else:
            self.resize(320, self.minimumSizeHint().height())
        self.fit_on_screen()

    @Slot(bool)
    def set_always_on_top(self, enabled):
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.top.setToolTip('取消置顶' if enabled else '保持小窗在游戏上方')
        self.settings.setValue('always_on_top', enabled)
        if visible: self.show()

    def closeEvent(self, event):
        # 关闭视图不会结束游戏，也不新建日志服务。
        self.settings.setValue('window_position', self.pos()); self.settings.sync()
        super().closeEvent(event)


class SessionLogWindow(LogWindow):
    def __init__(self, controller, parent=None):
        self.controller = controller
        controls = SessionControls(controller, compact=True)
        super().__init__(controller.logs, controls, parent)
        self.controls = controls
        self.console = PythonConsole(controller, compact=True)
        self.tabs.addTab(self.console, 'Python')
        controller.changed.connect(self.refresh); self.refresh()
        # 弹出菜单中的操作仍调用同一个控制器，点击后立即让出游戏画面。
        for button in (controls.reload_btn, controls.restart_btn, controls.stop_btn):
            button.clicked.connect(self.actions_menu.close)

    @Slot()
    def refresh(self):
        status = self.controller.status.removeprefix(self.controller.backend.label + ' · ')
        if self.controller.busy: status = '处理中…'
        elif self.controller.watcher: status += ' · 自动热更'
        self.status_label.setText(status)
        self.status_label.setToolTip(self.controller.status)

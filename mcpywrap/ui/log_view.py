"""One log model and rich-text renderer for embedded, floating and legacy views."""
from collections import deque
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QColor, QTextCursor, QTextCharFormat
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QCheckBox, QLineEdit, QPushButton, QLabel, QTextEdit
from ..mcstudio.log_colorizer import LogColorizer
from ..mcstudio import sessions
from .session_tools import LogTail, DebugLogFilter


class LogBuffer(QObject):
    appended = Signal(str, str, str)
    reset = Signal()
    sources = ('game', 'engine', 'worker', 'operations')
    limit = 1024 * 1024

    def __init__(self, parent=None):
        super().__init__(parent)
        self.chunks = {}
        self.sizes = {}

    def clear(self, sources=None):
        for key in list(self.chunks):
            if sources is None or key[0] in sources:
                self.chunks.pop(key); self.sizes.pop(key)
        self.reset.emit()

    def append(self, source, raw, filtered=None):
        filtered = raw if filtered is None else filtered
        for detail, text in ((True, raw), (False, filtered)):
            key = (source, detail)
            chunk = text[-self.limit:]
            queue = self.chunks.setdefault(key, deque())
            queue.append(chunk); self.sizes[key] = self.sizes.get(key, 0) + len(chunk)
            while self.sizes[key] > self.limit and len(queue) > 1:
                self.sizes[key] -= len(queue.popleft())
        self.appended.emit(source, raw, filtered)

    def snapshot(self, source, raw=False):
        return ''.join(self.chunks.get((source, raw), ()))


class SessionLogs(LogBuffer):
    """Read each worker-owned file once; any number of views share this source."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.directory = None
        self.tails, self.filters = {}, {}

    def bind(self, project, session):
        self.directory = sessions.session_path(project, session)
        self.tails = {name: LogTail() for name in self.sources if name != 'operations'}
        self.filters = {name: DebugLogFilter() for name in self.tails}
        self.clear(self.tails)

    def poll(self):
        if self.directory is None: return
        for name, tail in self.tails.items():
            text = tail.read(self.directory/(name + '.log'))
            if text: self.append(name, text, self.filters[name].apply(text))

    def finish(self):
        # Drain the remaining bounded view history; complete logs stay on disk.
        for _ in range(16):
            before = sum(tail.offset for tail in self.tails.values())
            self.poll()
            if before == sum(tail.offset for tail in self.tails.values()): break
        for name, tail in self.tails.items():
            if tail.pending:
                self.append(name, tail.pending, self.filters[name].apply(tail.pending))
                tail.pending = ''
        self.directory = None


class LogView(QWidget):
    """The original logger's colors/search, usable without owning a socket or game."""
    def __init__(self, model, source='game', toolbar=True, parent=None, compact=False):
        super().__init__(parent)
        self.model = model
        self.colorizer = LogColorizer(use_qt_colors=True)
        self.matches, self.current_match, self._term = [], -1, ''
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.tools = QWidget(); row = QHBoxLayout(self.tools); row.setContentsMargins(0, 0, 0, 0)
        self.source = QComboBox(); self.source.addItems(model.sources); self.source.setCurrentText(source)
        self.raw = QCheckBox('详情' if compact else '协议详情')
        self.raw.setToolTip('显示原始协议日志')
        self.search = QLineEdit(); self.search.setPlaceholderText('搜索日志…')
        self.previous = QPushButton('上条' if compact else '上一个')
        self.next = QPushButton('下条' if compact else '下一个')
        self.clear_button = QPushButton('清除')
        for button, label in ((self.previous, '上一个搜索结果'), (self.next, '下一个搜索结果'),
                              (self.clear_button, '清除搜索')):
            button.setToolTip(label); button.setAccessibleName(label)
        self.search.setClearButtonEnabled(compact)
        if compact:
            row.setSpacing(4)
            self.source.setMaximumWidth(90)
            self.search.setMinimumWidth(60)
        self.match_label = QLabel('0/0')
        for widget in (self.source, self.raw, self.search, self.previous, self.next, self.clear_button, self.match_label): row.addWidget(widget)
        self.clear_button.setVisible(not compact)
        self.tools.setVisible(toolbar); layout.addWidget(self.tools)
        self.editor = QTextEdit(); self.editor.setReadOnly(True); self.editor.setAcceptRichText(False)
        self.editor.document().setMaximumBlockCount(5000)
        self.editor.setStyleSheet('QTextEdit { background: #232323; color: #e0e0e0; }')
        layout.addWidget(self.editor)
        self.source.currentTextChanged.connect(self.replay); self.raw.toggled.connect(self.replay)
        self.search.returnPressed.connect(self.search_text); self.search.textChanged.connect(self.search_text)
        self.previous.clicked.connect(self.find_previous); self.next.clicked.connect(self.find_next)
        self.clear_button.clicked.connect(self.search.clear)
        model.appended.connect(self.receive); model.reset.connect(self.replay)
        self.replay()
        self.search_text(navigate=False)

    @Slot()
    def replay(self, *_):
        self.editor.clear()
        self.append_text(self.model.snapshot(self.source.currentText(), self.raw.isChecked()))

    @Slot(str, str, str)
    def receive(self, source, raw, filtered):
        if source != self.source.currentText(): return
        text = raw if self.raw.isChecked() else filtered
        if self.editor.document().characterCount() + len(text) > self.model.limit + 1:
            self.replay()
        else:
            self.append_text(text)

    def append_text(self, text):
        if not text: return
        bar = self.editor.verticalScrollBar()
        follow = bar.value() >= bar.maximum() - 2 and not self.editor.textCursor().hasSelection()
        position = bar.value()
        cursor = QTextCursor(self.editor.document()); cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.beginEditBlock()
        for line in text.splitlines(keepends=True):
            for segment, color in self.colorizer.analyze_text(line):
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(self.colorizer.COLORS.get(color) or '#e0e0e0'))
                cursor.insertText(segment, fmt)
        cursor.endEditBlock()
        self.search_text(navigate=False)
        bar.setValue(bar.maximum() if follow else position)

    def search_text(self, *_, navigate=True):
        term = self.search.text()
        if not term and self._term:
            cursor = self.editor.textCursor(); cursor.clearSelection(); self.editor.setTextCursor(cursor)
        self._term = term
        self.matches = []
        cursor = QTextCursor(self.editor.document())
        if term:
            while True:
                cursor = self.editor.document().find(term, cursor)
                if cursor.isNull(): break
                self.matches.append(QTextCursor(cursor))
        self.current_match = min(max(0, self.current_match), len(self.matches) - 1)
        selections = []
        for index, match in enumerate(self.matches):
            selection = QTextEdit.ExtraSelection(); selection.cursor = match
            selection.format.setBackground(QColor('#d08000' if index == self.current_match else '#705000'))
            selections.append(selection)
        self.editor.setExtraSelections(selections)
        self.previous.setEnabled(bool(self.matches)); self.next.setEnabled(bool(self.matches))
        self.clear_button.setEnabled(bool(term))
        self.match_label.setText('%d/%d' % (self.current_match + 1, len(self.matches)))
        if navigate and self.matches: self.move_to_match(self.current_match)

    def move_to_match(self, index):
        if not self.matches: return
        self.current_match = index % len(self.matches)
        self.editor.setTextCursor(self.matches[self.current_match]); self.editor.ensureCursorVisible()
        self.search_text(navigate=False)

    def find_next(self): self.move_to_match(self.current_match + 1)
    def find_previous(self): self.move_to_match(self.current_match - 1)

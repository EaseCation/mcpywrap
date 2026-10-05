"""Shared log rendering and one session owner across embedded/floating views."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication
from mcpywrap.mcstudio import sessions
from mcpywrap.mcstudio.log_colorizer import LogColorizer
from mcpywrap.ui.log_view import LogBuffer, LogView
from mcpywrap.ui.log_window import SessionLogWindow
from mcpywrap.ui.session_controller import SessionController
from mcpywrap.ui.session_views import SessionControls


class SharedLogsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve()
        self.backend = Mock(label='Fixture', capabilities=('watch',))
        self.controller = SessionController(self.project, self.backend)
        self.controller.timer.stop()
        self.addCleanup(self.cleanup)
        self.read = patch.object(sessions, 'read', side_effect=lambda root, sid: {
            'state': 'running', 'mode': 'local', 'level_id': 'world', 'session': sid})
        self.read.start(); self.addCleanup(self.read.stop)
        self.windows = []

    def cleanup(self):
        if self.controller.task:
            self.controller.task.wait(3000); self.app.processEvents()
        for window in self.windows: window.close()
        self.controller.session = None; self.controller.watcher = None
        self.controller.dispose(); self.app.processEvents()

    def log_file(self, sid, content):
        directory = sessions.session_path(self.project, sid); directory.mkdir(parents=True, exist_ok=True)
        path = directory/'game.log'; path.write_text(content, encoding='utf-8'); return path

    def wait(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(.005)
        self.app.processEvents(); self.assertTrue(predicate())

    def color_at(self, view, needle):
        cursor = view.editor.document().find(needle)
        self.assertFalse(cursor.isNull())
        return cursor.charFormat().foreground().color().name()

    def test_terminal_and_gui_share_lossless_color_classification(self):
        import re
        formatter = LogColorizer()
        text = '[2026-10-05 12:00:00,001] [ERROR][Engine] 错误\n[Probe] ready\nplain <xml>'
        formatter.ansi_colors = {key: '\x1b[31m' for key in formatter.COLORS}
        formatter.ansi_colors['reset'] = '\x1b[0m'
        rendered = formatter.colorize_terminal(text)
        self.assertEqual(re.sub(r'\x1b\[[0-9;]*m', '', rendered), text)
        self.assertEqual(''.join(segment for line in text.splitlines(keepends=True)
                                 for segment, _ in formatter.analyze_text(line)), text)

    def test_one_reader_fans_out_colored_logs_and_search_preserves_colors(self):
        sid = 'a'*32
        path = self.log_file(sid, '[2026-10-05 12:00:00,001] [ERROR][Engine] 故障一\n')
        self.controller.attach({'session': sid})
        embedded = LogView(self.controller.logs)
        floating = SessionLogWindow(self.controller); self.windows += [embedded, floating]
        with path.open('a', encoding='utf-8') as stream:
            stream.write('[2026-10-05 12:00:00,002] [WARN][Engine] 故障二\n')
        with patch.object(self.controller.logs.tails['game'], 'read', wraps=self.controller.logs.tails['game'].read) as read:
            self.controller.poll()
            self.assertEqual(read.call_count, 1)
            floating.log_view.raw.setChecked(True)
            self.assertEqual(read.call_count, 1)  # View changes replay memory, not the file.
        for view in (embedded, floating.log_view):
            self.assertEqual(view.editor.toPlainText(), path.read_text())
            self.assertEqual(self.color_at(view, '[ERROR]'), LogColorizer.COLORS['bright_red'].lower())
            self.assertEqual(self.color_at(view, '[WARN]'), LogColorizer.COLORS['bright_yellow'].lower())
            view.search.setText('故障'); self.assertEqual(len(view.matches), 2)
            view.find_next(); self.assertEqual(view.current_match, 1)
            view.find_previous(); self.assertEqual(view.current_match, 0)
            view.search.clear()
            self.assertFalse(view.editor.textCursor().hasSelection())
            self.assertEqual(self.color_at(view, '[ERROR]'), '#ff0000')

    def test_floating_window_collapses_and_closes_without_touching_game_or_stdout(self):
        self.log_file('a'*32, 'before\n'); self.controller.attach({'session': 'a'*32})
        original = sys.stdout
        with patch('socket.socket', side_effect=AssertionError('GUI must not open a log socket')):
            window = SessionLogWindow(self.controller); self.windows.append(window); window.show()
            self.assertFalse(window.log_expanded)
            window.toggle_log_view(); self.assertTrue(window.log_expanded)
            window.toggle_log_view(); self.assertFalse(window.log_expanded)
            with patch.object(sessions, 'stop') as stop: window.close(); stop.assert_not_called()
        self.assertIs(sys.stdout, original)
        self.assertEqual(self.controller.session, 'a'*32)
        self.controller.logs.append('game', 'after\n'); window.show()
        self.assertIn('after', window.log_view.editor.toPlainText())

    def test_watch_buttons_share_one_monitor_and_command_side(self):
        self.log_file('a'*32, ''); self.controller.attach({'session': 'a'*32})
        embedded = SessionControls(self.controller); self.windows.append(embedded)
        floating = SessionLogWindow(self.controller); self.windows.append(floating)
        with patch('mcpywrap.mcstudio.hot_reload.SessionWatcher') as watcher:
            floating.controls.side.setCurrentText('server')
            self.assertEqual(embedded.side.currentText(), 'server')
            floating.controls.watch.setChecked(True)
            self.wait(lambda: not self.controller.busy)
            self.assertTrue(embedded.watch.isChecked())
            watcher.assert_called_once()
            self.assertEqual(watcher.call_args.kwargs['sides'], ('server',))
            watcher.return_value.start.assert_called_once()
            embedded.watch.setChecked(False)
            self.wait(lambda: not self.controller.busy)
            watcher.return_value.stop.assert_called_once()
            self.assertFalse(floating.controls.watch.isChecked())

    def test_restart_rebinds_both_views_and_stop_is_serialized(self):
        self.log_file('a'*32, 'old-session\n'); self.log_file('b'*32, 'new-session\n')
        self.controller.attach({'session': 'a'*32})
        embedded = LogView(self.controller.logs); floating = SessionLogWindow(self.controller)
        self.windows += [embedded, floating]
        self.backend.start_session.return_value = {'session': 'b'*32}
        with patch.object(sessions, 'stop', return_value={'state': 'exited'}) as stop:
            floating.controls.restart_btn.click()
            embedded_before = self.controller.session
            floating.controls.stop_btn.click()  # Disabled while the same controller is busy.
            self.wait(lambda: not self.controller.busy)
        self.assertEqual(embedded_before, 'a'*32)
        stop.assert_called_once_with(str(self.project), 'a'*32)
        self.backend.start_session.assert_called_once_with(str(self.project), 'world')
        for view in (embedded, floating.log_view): self.assertEqual(view.editor.toPlainText(), 'new-session\n')

    def test_failed_stop_preserves_session_for_retry(self):
        self.log_file('a'*32, ''); self.controller.attach({'session': 'a'*32})
        with patch.object(sessions, 'stop', side_effect=ValueError('save still pending')):
            self.controller.stop(); self.wait(lambda: not self.controller.busy)
        self.assertEqual(self.controller.session, 'a'*32)
        self.assertTrue(self.controller.owns_session)
        self.assertIn('save still pending', self.controller.logs.snapshot('operations'))

    def test_buffer_history_is_bounded_and_filter_views_are_independent(self):
        model = LogBuffer(); model.limit = 64
        raw, filtered = LogView(model), LogView(model)
        self.windows += [raw, filtered]; raw.raw.setChecked(True)
        model.append('game', 'RN Call: transport\nreal output\n', 'real output\n')
        self.assertIn('transport', raw.editor.toPlainText())
        self.assertNotIn('transport', filtered.editor.toPlainText())
        for _ in range(20): model.append('game', '0123456789\n')
        self.assertLessEqual(len(model.snapshot('game')), 64)
        self.assertLessEqual(len(model.snapshot('game', True)), 64)
        self.assertLessEqual(raw.editor.document().characterCount(), 65)
        self.assertLessEqual(filtered.editor.document().characterCount(), 65)


if __name__ == '__main__': unittest.main()

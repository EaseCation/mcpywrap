"""Real Qt6 widgets using the same backend/session contract on either platform."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer, QThread, Qt
from mcpywrap.ui.project_ui import GameInstanceManager
from mcpywrap.ui.engine_setup import EngineSetupDialog
from mcpywrap.ui.session_tools import LogTail
from mcpywrap.engines.backend import GameBackend


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root/'pyproject.toml').write_text('[project]\nname="qt-test"\nversion="0.0.0"\n')
        self.backend = Mock(spec=GameBackend)
        self.backend.capabilities = ('project-ui', 'watch')
        self.backend.label = 'Fixture backend'
        self.backend.instances.return_value = []
        self.backend.start_session.return_value = {'session': 'a'*32}
        with patch('mcpywrap.ui.project_ui.get_backend', return_value=self.backend), \
                patch('mcpywrap.ui.project_ui._setup_dependencies', return_value=[]), \
                patch('mcpywrap.ui.project_ui.find_all_mcpywrap_packages', return_value=[]):
            self.window = GameInstanceManager(str(self.root))
        self.window.controller.timer.stop()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        task = self.window.controller.task
        if task: task.wait(2000); self.app.processEvents()
        self.window.controller.session=None; self.window.controller.owns_session=False
        self.window.close();self.app.processEvents()

    def wait(self, condition):
        end=time.monotonic()+3
        while not condition() and time.monotonic()<end:
            self.app.processEvents();time.sleep(.005)
        self.app.processEvents()
        self.assertTrue(condition())

    def test_new_instance_confirms_with_settings_collapsed_and_can_cancel(self):
        from mcpywrap.ui.world_config import WorldConfigDialog
        from mcpywrap.mcstudio.runtime_cppconfig import gen_runtime_config, WORLD_FIELDS
        dialog = WorldConfigDialog('test')
        self.addCleanup(dialog.close)
        dialog.show(); self.app.processEvents()
        self.assertFalse(dialog.scroll.isVisible())
        initial = dialog.cppconfig()['world_info']
        expected = gen_runtime_config('', 'test', 'preview', '', '', [], [])['world_info']
        self.assertEqual(initial, {key:expected[key] for key in WORLD_FIELDS})
        dialog.more.setChecked(True); self.app.processEvents()
        self.assertTrue(dialog.scroll.isVisible())
        dialog.fields['difficulty'].setCurrentIndex(3)
        dialog.rules['keep_inventory'].setChecked(False)
        dialog.more.setChecked(False)
        self.assertEqual(dialog.cppconfig()['world_info']['difficulty'],3)
        self.assertFalse(dialog.cppconfig()['world_info']['cheat_info']['keep_inventory'])
        self.backend.world_option_restrictions.return_value = {}
        QTimer.singleShot(0, lambda: QApplication.activeModalWidget().reject())
        self.window.create_new_instance()
        self.backend.start_session.assert_not_called()

    def test_new_confirmation_passes_cppconfig_to_shared_controller(self):
        from mcpywrap.ui.world_config import WorldConfigDialog
        self.backend.world_option_restrictions.return_value = {}
        # Patching methods on a QObject class crashes PySide 6.10/Python 3.9
        # during signal introspection. Exercise the real modal dialog instead.
        def accept():
            dialog = QApplication.activeModalWidget()
            dialog.fields['difficulty'].setCurrentIndex(3)
            dialog.accept()
        QTimer.singleShot(0, accept)
        with patch.object(self.window, 'start_game_thread') as start:
            self.window.create_new_instance()
        start.assert_called_once()
        self.assertEqual(start.call_args.kwargs['world_config']['world_info']['difficulty'], 3)

    def test_start_and_stop_use_managed_session_without_platform_branch(self):
        self.window.start_game_thread('world')
        self.wait(lambda:self.window.controller.session=='a'*32 and not self.window.is_busy())
        self.backend.start_session.assert_called_once_with(str(self.root),'world',None)
        self.assertFalse(self.window.edit_btn.isEnabled())
        with patch('mcpywrap.mcstudio.sessions.stop', return_value={'state':'exited'}) as stop:
            self.window.controller.stop()
            self.wait(lambda:self.window.controller.session is None and not self.window.is_busy())
        stop.assert_called_once_with(str(self.root),'a'*32)

    def test_first_start_uses_graphical_resource_setup(self):
        self.backend.managed_install = True
        self.backend.diagnose.side_effect = [{'ok': False}, {'ok': True}]
        with patch.object(self.window, 'prepare_engine') as setup:
            self.window.start_game_thread()
            self.wait(lambda: self.window.controller.session is not None and not self.window.is_busy())
        setup.assert_called_once_with(auto_install=True)

    def test_explicit_engine_is_kept_when_starting_and_reloading_world(self):
        overrides = {'engine_version': '3.9.0.401155'}
        self.window.controller.engine_overrides = overrides
        self.window.start_game_thread('world')
        self.wait(lambda: self.window.controller.session and not self.window.is_busy())
        self.backend.start_session.assert_called_once_with(str(self.root), 'world', None, overrides=overrides)
        self.backend.start_session.reset_mock()
        with patch('mcpywrap.mcstudio.sessions.read', return_value={'state': 'running', 'level_id': 'world'}), \
                patch('mcpywrap.mcstudio.sessions.stop', return_value={'state': 'exited'}):
            self.window.controller.restart()
            self.wait(lambda: not self.window.is_busy())
        self.backend.start_session.assert_called_once_with(str(self.root), 'world', overrides=overrides)

    def test_reloading_attached_session_preserves_its_engine_selection(self):
        overrides = {'engine_version': '3.9.0.401155'}
        self.window.controller.session = 'a'*32
        with patch('mcpywrap.mcstudio.sessions.read', return_value={
                'state': 'running', 'level_id': 'world', 'engine_overrides': overrides}), \
                patch('mcpywrap.mcstudio.sessions.stop', return_value={'state': 'exited'}):
            self.window.controller.restart()
            self.wait(lambda: not self.window.is_busy())
        self.backend.start_session.assert_called_once_with(str(self.root), 'world', overrides=overrides)

    def test_background_result_updates_widgets_on_application_thread(self):
        workers, updates = [], []
        self.window.log_output.textChanged.connect(
            lambda: updates.append(QThread.currentThread()), Qt.ConnectionType.DirectConnection)
        def work():
            workers.append(QThread.currentThread())
            return {'state': 'completed', 'value': 'worker-result'}
        self.window.controller.run_task(work)
        self.wait(lambda: 'worker-result' in self.window.log_output.toPlainText() and not self.window.is_busy())
        self.assertNotEqual(workers[0], self.app.thread())
        self.assertTrue(updates)
        self.assertTrue(all(thread == self.app.thread() for thread in updates))

    def test_startup_failure_keeps_interface_usable(self):
        self.backend.start_session.side_effect=ValueError('fixture failed')
        self.window.start_game_thread()
        self.wait(lambda:not self.window.is_busy())
        self.assertIn('fixture failed', self.window.log_output.toPlainText())
        self.assertIsNone(self.window.controller.session)

    def test_window_close_stops_only_its_owned_game(self):
        self.window.controller.session='a'*32;self.window.controller.owns_session=True
        self.window.show()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes), \
                patch('mcpywrap.mcstudio.sessions.stop',return_value={'state':'exited'}) as stop:
            self.window.close()
            self.wait(lambda: not self.window.isVisible() and not self.window.is_busy())
        stop.assert_called_once()
        self.window.controller.session='b'*32;self.window.controller.owns_session=False;self.window.show()
        with patch('mcpywrap.mcstudio.sessions.stop') as stop:
            self.window.close(); self.app.processEvents()
        stop.assert_not_called()

    def test_close_attached_view_stops_monitor_but_keeps_external_game(self):
        self.window.controller.attach({'session': 'b'*32, 'already_running': True})
        watcher = Mock(); self.window.controller.watcher = watcher
        self.window.show()
        with patch('mcpywrap.mcstudio.sessions.stop') as stop:
            self.window.close()
            self.wait(lambda: not self.window.isVisible() and not self.window.is_busy())
        watcher.stop.assert_called_once()
        stop.assert_not_called()
        self.assertFalse(self.window.log_window.isVisible())

    def test_debug_log_displays_regular_output_and_filters_protocol(self):
        from mcpywrap.mcstudio import sessions
        self.window.controller.session='a'*32
        directory=sessions.session_path(self.root,self.window.controller.session);directory.mkdir(parents=True)
        (directory/'game.log').write_text('真实 Mod 输出\n[INFO] RN Call: transport\nerror: fixture\n')
        self.window.controller.logs.bind(self.root,self.window.controller.session)
        with patch.object(sessions,'read',return_value={'state':'running','world_ready':True}):self.window.controller.poll()
        text=self.window.debug_view.editor.toPlainText()
        self.assertIn('真实 Mod 输出',text);self.assertIn('error: fixture',text);self.assertNotIn('transport',text)

    def test_large_install_progress_and_close_guard(self):
        backend=Mock(spec=GameBackend,setup_description='fixture')
        def install(catalog,apk,progress):
            progress(3_883_509_388,3_883_509_388)
            return {'ok':True}
        backend.install.side_effect=install
        dialog=EngineSetupDialog(backend)
        dialog.catalog.setText('/catalog.json');dialog.install()
        self.wait(lambda: not dialog.task.isRunning())
        self.assertEqual(dialog.progress.value(),100)
        self.assertIn('资源已就绪',dialog.status.text())
        dialog.close()

    def test_run_view_close_keeps_game_and_exit_disposes_controller(self):
        from mcpywrap.ui.run_session import RunSessionView
        state = {'session': 'b'*32, 'state': 'running', 'game': None}
        with patch('mcpywrap.ui.session_controller.sessions.read', return_value=state), \
                patch.object(self.app, 'quit') as quit_app:
            view = RunSessionView(self.app, str(self.root), self.backend, {'session': 'b'*32})
            self.assertTrue(view.window.isVisible())
            self.assertIs(view.window.controls.controller, view.controller)
            self.assertIs(view.window.log_view.model, view.controller.logs)
            view.window.close()
            view.update()
            self.assertEqual(view.controller.session, 'b'*32)
            quit_app.assert_not_called()
            state['state'] = 'exited'
            view.controller.poll()
            quit_app.assert_called()
            view.dispose()

    def test_run_view_terminal_interrupt_uses_existing_stop_action(self):
        from mcpywrap.ui.run_session import RunSessionView
        state = {'session': 'b'*32, 'state': 'running', 'game': None}
        with patch('mcpywrap.ui.session_controller.sessions.read', return_value=state), \
                patch('mcpywrap.ui.session_controller.sessions.stop', return_value={'state': 'exited'}) as stop, \
                patch.object(self.app, 'quit'):
            view = RunSessionView(self.app, str(self.root), self.backend, {'session': 'b'*32})
            view.request_stop()
            view.update()
            self.wait(lambda: not view.controller.busy)
            stop.assert_called_once_with(str(self.root), 'b'*32)
            view.dispose()

    def test_ui_setup_defaults_are_hidden_and_auto_setup_continues(self):
        backend = Mock(spec=GameBackend, setup_description='fixture')
        backend.install.return_value = {'ok': True}
        dialog = EngineSetupDialog(backend, auto_install=True)
        dialog.show()
        self.assertFalse(dialog.advanced.isVisible())
        self.wait(lambda: dialog.ready and not dialog.isVisible())
        self.assertEqual(backend.install.call_args.args[:2], (None, None))
        dialog.close()

    def test_protocol_filter_spans_chunks_and_keeps_mod_output(self):
        from mcpywrap.ui.session_tools import DebugLogFilter
        filtered=DebugLogFilter()
        self.assertEqual(filtered.apply('[Server][Run] script begin\nechoed code'), '')
        self.assertEqual(filtered.apply('more code\n[Server][Run] script end\nMod output'), 'Mod output')

    def test_mod_template_can_embed_without_nested_application_loop(self):
        from mcpywrap.minecraft.template.mod_template import open_ui_crate_mod
        window = open_ui_crate_mod(str(self.root), run_event_loop=False)
        self.assertTrue(window.isVisible())
        window.close()

    def test_log_tail_preserves_utf8_and_partial_lines(self):
        path=self.root/'game.log';tail=LogTail()
        encoded='中文\n'.encode();path.write_bytes(encoded[:2])
        self.assertEqual(tail.read(path),'')
        with path.open('ab') as f:f.write(encoded[2:])
        self.assertEqual(tail.read(path),'中文\n')
        self.assertEqual(tail.read(path),'')


if __name__=='__main__':unittest.main()

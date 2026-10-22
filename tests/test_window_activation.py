"""Activation guard handoff and cleanup, without installing a real hook in CI."""
import ctypes as C
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from mcpywrap_core.mcstudio.window_activation import ActivationGuard
from mcpywrap_core.engines.host import EngineError


class ActivationGuardTests(unittest.TestCase):
    def test_missing_or_tampered_asset_never_loads_a_dll(self):
        with tempfile.TemporaryDirectory() as temp, \
                patch('mcpywrap_core.host_assets.asset_directory', return_value=Path(temp)), \
                patch.object(C, 'WinDLL', create=True) as load:
            with self.assertRaises(EngineError) as error:
                ActivationGuard()
            self.assertEqual(error.exception.code, 'background_window_unavailable')
            load.assert_not_called()

    def test_gui_queue_retry_uses_the_same_owned_initial_thread(self):
        guard = ActivationGuard.__new__(ActivationGuard)
        guard.library, guard.hook = Mock(), None
        process = Mock(pid=123, poll=Mock(return_value=None))
        events = []
        def install(pid, pointer):
            self.assertEqual(pid, 123)
            events.append(('install', pointer._obj.value))
            pointer._obj.value = 456
            return None if len(events) == 1 else 789
        def resume(pid, thread):
            events.append(('resume', pid, thread.value))
            return True
        guard.library.McpyGuardInstall.side_effect = install
        guard.library.McpyGuardResume.side_effect = resume
        with patch.object(C, 'get_last_error', return_value=87, create=True):
            guard.start(process)
        self.assertEqual(events, [('install', 0), ('resume', 123, 456), ('install', 456)])
        guard.close()
        guard.close()
        guard.library.McpyGuardClose.assert_called_once_with(789)

    @unittest.skipUnless(os.name == 'nt', 'Win32 process handoff')
    def test_guard_failure_terminates_only_its_new_process(self):
        from types import SimpleNamespace
        from mcpywrap_core.mcstudio import game
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp)/'Minecraft.Windows.exe'
            executable.touch()
            engine = SimpleNamespace(executable=str(executable), engine_dir=temp, version='3.10', source='test')
            with patch.object(game, '_launch_message'), patch.object(game.subprocess, 'Popen') as spawn, \
                    patch('mcpywrap_core.mcstudio.window_activation.ActivationGuard') as factory:
                factory.return_value.start.side_effect = OSError('hook refused')
                self.assertFalse(game.open_game(None, engine=engine, background=True))
                spawn.return_value.kill.assert_called_once_with()
                spawn.return_value.wait.assert_called_once_with(timeout=10)
                factory.return_value.close.assert_called_once_with()

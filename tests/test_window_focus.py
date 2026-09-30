"""Foreground fallback retains exact target checks and always detaches queues."""
import unittest
from unittest.mock import Mock, patch
from mcpywrap.mcstudio.window import GameWindow


class FocusTests(unittest.TestCase):
    def target(self):
        window=GameWindow.__new__(GameWindow)
        window.hwnd=123;window.game={'pid':456};window.cancel=None
        window.validate_process=Mock();window.owner=Mock(return_value=456)
        window.user=Mock();window.kernel=Mock()
        window.user.IsIconic.return_value=False
        window.kernel.GetCurrentThreadId.return_value=7
        window.user.GetWindowThreadProcessId.return_value=8
        return window

    def test_attach_fallback_detaches_and_verifies_target(self):
        window=self.target();foreground=[999];attached=[False]
        window.user.GetForegroundWindow.side_effect=lambda:foreground[0]
        def attach(a,b,enabled):attached[0]=enabled;return True
        def focus(hwnd):
            if attached[0]:foreground[0]=hwnd
            return attached[0]
        window.user.AttachThreadInput.side_effect=attach
        window.user.SetForegroundWindow.side_effect=focus
        with patch('mcpywrap.mcstudio.window.time.sleep'):
            window.foreground()
        self.assertEqual(foreground[0],123)
        self.assertFalse(attached[0])
        window.user.AttachThreadInput.assert_any_call(7,8,False)
        window.check_foreground()

    def test_focus_exception_still_detaches(self):
        window=self.target();window.user.GetForegroundWindow.return_value=999
        window.user.AttachThreadInput.return_value=True
        window.user.SetForegroundWindow.side_effect=[False,OSError('focus failed')]
        with self.assertRaises(OSError):window.foreground()
        window.user.AttachThreadInput.assert_any_call(7,8,False)

    def test_existing_foreground_does_not_attach(self):
        window=self.target();window.user.GetForegroundWindow.return_value=123
        with patch('mcpywrap.mcstudio.window.time.sleep'):window.foreground()
        window.user.AttachThreadInput.assert_not_called()

    def test_unconfirmed_target_still_rejected(self):
        window=self.target();window.user.GetForegroundWindow.return_value=999
        with self.assertRaisesRegex(ValueError,'前台窗口'):window.check_foreground()

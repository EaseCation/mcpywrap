"""Skill 的窗口工具：解析、PNG 像素、进程身份及按键释放保护。"""
import contextlib
import ctypes
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch
import zlib

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/mcpywrap/scripts/game_window.py'
spec = importlib.util.spec_from_file_location('game_window_skill', SCRIPT)
window = importlib.util.module_from_spec(spec)
spec.loader.exec_module(window)


class SkillWindowTests(unittest.TestCase):
    def test_full_keyboard_named_keys_and_raw_codes(self):
        for name in ['F24', 'RSHIFT', 'RCTRL', 'RALT', 'NUMPAD9', 'NUMPAD_ENTER',
                     'OEM_102', 'BACKTICK', 'PAGEUP', 'CAPSLOCK', 'MEDIA_PLAY_PAUSE',
                     'LWIN', 'KANA', 'VK:0xAB', 'SC:0x11', 'E0:0x1D']:
            with self.subTest(name=name):
                self.assertEqual(len(window.parse_keys(name)), 1)
        self.assertEqual(window.parse_keys('NUMPAD_ENTER')[0].extended, True)
        self.assertEqual(window.parse_keys('ENTER')[0].extended, False)
        self.assertEqual(window.parse_keys('E0:0x1D')[0].scan, 0x1D)
        self.assertEqual(window.parse_keys('F24')[0].vk, 0x87)

    def test_chord_modifiers_first_and_validation(self):
        self.assertEqual([k.name for k in window.parse_keys(['W+A', 'SHIFT'])], ['LSHIFT', 'W', 'A'])
        for invalid in ['W+W', 'CTRL+LCTRL', 'W++A', 'not-a-key', 'VK:0', 'VK:0x100',
                        'VK:0xE7', 'SC:0', 'SC:0x80', 'E0:0xFFFF', 'VK:wrong']:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                window.parse_keys(invalid)

    def test_png_correct_color_orientation_and_crc(self):
        image = window.png_bytes(1, 2, bytes([0, 0, 255, 0, 255, 0, 0, 0]))
        self.assertEqual(image[:8], b'\x89PNG\r\n\x1a\n')
        position = 8
        chunks = {}
        while position < len(image):
            length = struct.unpack('>I', image[position:position + 4])[0]
            kind = image[position + 4:position + 8]
            data = image[position + 8:position + 8 + length]
            checksum = struct.unpack('>I', image[position + 8 + length:position + 12 + length])[0]
            self.assertEqual(checksum, zlib.crc32(kind + data))
            chunks[kind] = data
            position += length + 12
        self.assertEqual(zlib.decompress(chunks[b'IDAT']), b'\0\xff\0\0\0\0\0\xff')
        self.assertEqual(struct.unpack('>II', chunks[b'IHDR'][:8]), (1, 2))

    def test_wrong_dimensions_rejected(self):
        with self.assertRaises(ValueError):
            window.png_bytes(2, 2, b'wrong')

    def test_status_rejects_other_process_and_exited_session(self):
        with tempfile.TemporaryDirectory() as folder:
            data = {'ok': True, 'project': folder, 'state': 'running',
                    'game': {'executable': 'notepad.exe'}}
            result = Mock(returncode=0, stdout=json.dumps(data), stderr='')
            with patch.object(window.subprocess, 'run', return_value=result) as run:
                with self.assertRaisesRegex(ValueError, 'Minecraft'):
                    window.load_session('custom mcpy.exe', folder, 'id')
                self.assertEqual(run.call_args.args[0][0], 'custom mcpy.exe')
                self.assertFalse(run.call_args.kwargs.get('shell', False))
            data.update(state='exited')
            result.stdout = json.dumps(data)
            with patch.object(window.subprocess, 'run', return_value=result):
                with self.assertRaisesRegex(ValueError, '未运行'):
                    window.load_session('mcpy', folder, 'id')

    def test_project_mismatch_rejected(self):
        data = {'ok': True, 'project': '/somewhere/else', 'state': 'running',
                'game': {'executable': 'Minecraft.Windows.exe'}}
        with patch.object(window.subprocess, 'run', return_value=Mock(returncode=0, stdout=json.dumps(data))):
            with self.assertRaisesRegex(ValueError, '项目路径'):
                window.load_session('mcpy', '/my/project', 'id')

    def test_bad_cli_json_is_error(self):
        with patch.object(window.subprocess, 'run', return_value=Mock(stdout='unexpected')):
            with self.assertRaisesRegex(ValueError, 'JSON'):
                window.load_session('mcpy', '.', 'id')

    def fake_window(self):
        target = window.GameWindow.__new__(window.GameWindow)
        target.foreground = Mock()
        target.check_foreground = Mock()
        target.user = Mock()
        target.user.GetAsyncKeyState.return_value = 0
        target.user.SendInput.return_value = 1
        return target

    def test_release_attempted_when_interrupted(self):
        target = self.fake_window()
        flags = []
        target.user.SendInput.side_effect = lambda count, event, size: flags.append(event._obj.keyboard.flags) or 1
        with patch.object(window.time, 'sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                target.press('F11', 80)
        self.assertEqual(flags, [0, 2])

    def test_modifier_blocks_input(self):
        target = self.fake_window()
        target.user.GetAsyncKeyState.return_value = 0x8000
        with self.assertRaisesRegex(ValueError, '按住'):
            target.press('F3', 80)
        target.user.SendInput.assert_not_called()

    def test_focus_failure_sends_nothing(self):
        target = self.fake_window()
        target.check_foreground.side_effect = ValueError('not foreground')
        with self.assertRaises(ValueError):
            target.press('F3', 80)
        target.user.SendInput.assert_not_called()

    def test_focus_lost_after_press_is_error_after_release(self):
        target = self.fake_window()
        target.check_foreground.side_effect = [None, ValueError('lost focus')]
        flags = []
        target.user.SendInput.side_effect = lambda count, event, size: flags.append(event._obj.keyboard.flags) or 1
        with patch.object(window.time, 'sleep'):
            with self.assertRaisesRegex(ValueError, 'lost focus'):
                target.press('F3', 80)
        self.assertEqual(flags, [0, 2])

    def test_movement_chord_press_order_and_reverse_release(self):
        target = self.fake_window()
        events = []
        target.user.SendInput.side_effect = lambda count, event, size: events.append(
            (event._obj.keyboard.vk, event._obj.keyboard.scan, event._obj.keyboard.flags)) or 1
        with patch.object(window.time, 'monotonic', side_effect=[0, 2]):
            result = target.press(['W', 'A', 'SHIFT'], 1000)
        self.assertEqual(events, [(0xA0, 0, 0), (0x57, 0, 0), (0x41, 0, 0),
                                  (0x41, 0, 2), (0x57, 0, 2), (0xA0, 0, 2)])
        self.assertTrue(result['released'])

    def test_partial_send_releases_all_attempted_keys(self):
        target = self.fake_window()
        events = []

        def send(count, event, size):
            events.append((event._obj.keyboard.vk, event._obj.keyboard.flags))
            return 0 if len(events) == 2 else 1

        target.user.SendInput.side_effect = send
        with self.assertRaisesRegex(ValueError, '完整发送'):
            target.press('SHIFT+W', 1000)
        self.assertEqual(events, [(0xA0, 0), (0x57, 0), (0x57, 2), (0xA0, 2)])

    def test_scancode_and_extended_events(self):
        target = self.fake_window()
        target.user.MapVirtualKeyW.return_value = 0xA3
        events = []
        target.user.SendInput.side_effect = lambda count, event, size: events.append(
            (event._obj.keyboard.vk, event._obj.keyboard.scan, event._obj.keyboard.flags)) or 1
        with patch.object(window.time, 'monotonic', side_effect=[0, 2]):
            target.press('E0:0x1D', 1000)
        self.assertEqual(events, [(0, 0x1D, 9), (0, 0x1D, 11)])

    def test_focus_loss_during_movement_releases_chord(self):
        target = self.fake_window()
        target.check_foreground.side_effect = [None, None, ValueError('lost focus')]
        events = []
        target.user.SendInput.side_effect = lambda count, event, size: events.append(
            (event._obj.keyboard.vk, event._obj.keyboard.flags)) or 1
        with self.assertRaisesRegex(ValueError, 'lost focus'):
            target.press('W+A', 5000)
        self.assertEqual(events[-2:], [(0x41, 2), (0x57, 2)])

    def test_release_failure_still_releases_other_keys(self):
        target = self.fake_window()
        events = []

        def send(count, event, size):
            events.append((event._obj.keyboard.vk, event._obj.keyboard.flags))
            return 0 if len(events) == 3 else 1

        target.user.SendInput.side_effect = send
        with patch.object(window.time, 'monotonic', side_effect=[0, 2]):
            with self.assertRaisesRegex(ValueError, '释放'):
                target.press('W+A', 1000)
        self.assertEqual(events[-1], (0x57, 2))

    @unittest.skipUnless(os.name == 'nt', 'Windows')
    def test_screenshot_failure_leaves_no_output(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'blocked.png'
            fake = Mock()
            fake.screenshot.side_effect = ValueError('游戏客户区被其他窗口覆盖')
            with patch.object(window, 'load_session', return_value={}), patch.object(window, 'GameWindow', return_value=fake), contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = window.main(['--project', folder, '--session', 'id', 'screenshot', '--output', str(output)])
            self.assertEqual(code, 1)
            self.assertIn('覆盖', json.loads(stdout.getvalue())['error'])
            self.assertFalse(output.exists())
            fake.close.assert_called_once()

    @unittest.skipUnless(os.name == 'nt', 'Windows')
    def test_real_process_handle_rejects_wrong_creation_time(self):
        import sys
        target = {'pid': os.getpid(), 'created_at': 0, 'executable': sys.executable}
        with self.assertRaisesRegex(ValueError, '身份不匹配'):
            window.GameWindow(target)

    @unittest.skipUnless(os.name == 'nt', 'Windows ABI')
    def test_input_abi_size(self):
        self.assertEqual(ctypes.sizeof(window.Input), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    @unittest.skipUnless(os.name == 'nt', 'Windows')
    def test_existing_output_rejected_before_window_access(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'already.png'
            output.write_bytes(b'preserve')
            with patch.object(window, 'load_session') as lookup, contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = window.main(['--project', folder, '--session', 'id', 'screenshot', '--output', str(output)])
            self.assertEqual(code, 1)
            self.assertFalse(json.loads(stdout.getvalue())['ok'])
            lookup.assert_not_called()
            self.assertEqual(output.read_bytes(), b'preserve')


if __name__ == '__main__':
    unittest.main()

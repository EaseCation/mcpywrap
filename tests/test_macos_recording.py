"""macOS ScreenCaptureKit recording backend: helper verification, capability probe, PID target and worker flow."""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import uuid

from mcpywrap_core.mcstudio import recordings as jobs, recording_worker, sessions

MAC_GAME = {'pid': 4242, 'created_at': 1.0, 'executable': '/Apps/Minecraft China.app/Contents/MacOS/mcpelauncher-client'}


class FakeHelper:
    """A stand-in executable that answers --capabilities with a fixed JSON document."""

    def __init__(self, root, capabilities, protocol=1):
        self.folder = Path(tempfile.mkdtemp(dir=root)) / 'macos_capture'
        self.folder.mkdir()
        self.path = self.folder / jobs.MACOS_HELPER
        self.path.write_text('#!/bin/sh\necho \'' + json.dumps(capabilities) + '\'\n')
        self.path.chmod(self.path.stat().st_mode | stat.S_IXUSR)
        (self.folder / 'manifest.json').write_text(json.dumps({
            'executable_sha256': hashlib.sha256(self.path.read_bytes()).hexdigest(), 'media_protocol': protocol}))


@unittest.skipIf(os.name == 'nt', 'POSIX shell helper stand-in')
class MacCapabilities(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(jobs.sys, 'platform', 'darwin').start()
        patch('platform.machine', return_value='arm64').start()

    def inspect(self, capabilities, **kwargs):
        helper = FakeHelper(self.temp.name, capabilities, **kwargs)
        with patch('mcpywrap_core.host_assets.asset_directory', return_value=helper.folder):
            return jobs.inspect_media(), helper

    def test_ready_helper_enables_record_and_frames(self):
        media, _ = self.inspect({'protocol': 1, 'sck': True, 'h264_encoder': True, 'h264_decoder': True,
                                 'screen_capture_permission': True})
        self.assertTrue(media['component_available'] and media['record_available'] and media['frames_available'])
        self.assertFalse(media['wgc'])
        self.assertNotIn('reason', media)

    def test_missing_screen_recording_permission_disables_record_with_actionable_reason(self):
        media, _ = self.inspect({'protocol': 1, 'sck': True, 'h264_encoder': True, 'h264_decoder': True,
                                 'screen_capture_permission': False})
        self.assertFalse(media['record_available'])
        self.assertTrue(media['frames_available'])
        self.assertIn('Screen Recording', media['reason'])

    def test_tampered_helper_and_unknown_protocol_are_rejected(self):
        helper = FakeHelper(self.temp.name, {'protocol': 1, 'sck': True})
        helper.path.write_text(helper.path.read_text() + '# changed\n')
        with patch('mcpywrap_core.host_assets.asset_directory', return_value=helper.folder):
            media = jobs.inspect_media()
        self.assertFalse(media['component_available'])
        self.assertIn('integrity', media['reason'])
        media, _ = self.inspect({'protocol': 2}, protocol=2)
        self.assertFalse(media['record_available'])

    def test_intel_macs_are_reported_unsupported(self):
        with patch('platform.machine', return_value='x86_64'):
            media = jobs.inspect_media()
        self.assertFalse(media['record_available'])
        self.assertIn('Apple Silicon', media['reason'])


class MacTargets(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(patch.stopall)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'mac project'
        self.project.mkdir()
        self.sid = 'c' * 32
        patch.object(jobs.tempfile, 'gettempdir', return_value=str(self.root)).start()
        folder = sessions.session_path(self.project, self.sid)
        folder.mkdir(parents=True)
        self.session = {'session': self.sid, 'project': str(self.project), 'state': 'running',
                        'backend': 'macos-arm64', 'game': MAC_GAME, 'worker': None}
        sessions.save(folder / 'session.json', self.session)

    def test_recording_game_requires_the_live_launcher_process(self):
        patch.object(jobs.sessions, 'read', return_value=self.session).start()
        with patch.object(jobs, 'checked_process', return_value=Mock()):
            self.assertEqual(jobs.recording_game(self.project, self.sid), MAC_GAME)
        for checked in (None, ValueError('reused pid')):
            with self.subTest(checked=checked), patch.object(jobs, 'checked_process', side_effect=[checked] if
                                                             isinstance(checked, Exception) else None,
                                                             return_value=checked):
                with self.assertRaises(jobs.RecordingError) as caught:
                    jobs.recording_game(self.project, self.sid)
                self.assertEqual(caught.exception.code, 'session_unavailable')

    def test_windows_sessions_keep_the_window_target(self):
        self.session.update(backend='windows', game={'pid': 1, 'created_at': 1, 'executable': 'Minecraft.Windows.exe'})
        sessions.save(sessions.session_path(self.project, self.sid) / 'session.json', self.session)
        with patch('mcpywrap_core.mcstudio.window.session_game', return_value='windows-game') as selected:
            self.assertEqual(jobs.recording_game(self.project, self.sid), 'windows-game')
        selected.assert_called_once()

    def worker(self, events, alive=True):
        rid = uuid.uuid4().hex
        path = jobs.record_path(self.project, self.sid, rid)
        path.parent.mkdir(exist_ok=True)
        sessions.save(path, {'project': str(self.project), 'session': self.sid, 'recording': rid, 'state': 'starting',
                             'duration': 10, 'fps': 30, 'game': MAC_GAME, 'frames_written': 0})
        process = Mock()
        process.stdout = io.BytesIO(b''.join(json.dumps(e).encode() + b'\n' for e in events))
        process.poll.return_value = 0
        process.returncode = 0
        calls = []

        def spawn(command, **kwargs):
            calls.append(command)
            (jobs.payload(self.project, self.sid, rid) / 'video.partial.mp4').write_bytes(b'video')
            return process
        with patch.object(recording_worker, 'identity', return_value={'pid': 123}), \
             patch.object(recording_worker, 'checked_process', return_value=Mock() if alive else None), \
             patch.object(recording_worker, 'GameWindow', side_effect=AssertionError('no Windows window lookup')), \
             patch.object(jobs, 'helper', return_value=Path('mcpy-macos-capture')), \
             patch.object(recording_worker.subprocess, 'Popen', side_effect=spawn):
            recording_worker.run(self.project, self.sid, rid)
        return jobs.raw_record(self.project, self.sid, rid), calls, path

    def test_worker_passes_the_game_pid_and_publishes_the_video(self):
        data, calls, _ = self.worker([{'event': 'ready', 'width': 1440, 'height': 1024},
                                      {'event': 'progress', 'frames_written': 30}, {'event': 'finalizing'},
                                      {'event': 'completed', 'frames_written': 300, 'frames_captured': 280,
                                       'frames_repeated': 25, 'source_frames_skipped': 5, 'end_reason': 'duration'}])
        self.assertEqual(data['state'], 'completed')
        self.assertFalse(data['truncated'])
        command = calls[0]
        self.assertEqual(command[command.index('--pid') + 1], str(MAC_GAME['pid']))
        self.assertNotIn('--hwnd', command)

    def test_game_exit_stops_the_recording_as_window_unavailable(self):
        data, _, path = self.worker([{'event': 'ready', 'width': 2, 'height': 2},
                                     {'event': 'completed', 'frames_written': 3, 'frames_captured': 3,
                                      'frames_repeated': 0, 'source_frames_skipped': 0, 'end_reason': 'requested_stop'}],
                                    alive=False)
        self.assertTrue(path.with_suffix('.stop').exists())
        self.assertEqual(data['end_reason'], 'window_unavailable')


if __name__ == '__main__':
    unittest.main()

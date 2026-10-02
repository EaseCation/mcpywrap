"""Opt-in real WGC/MF integration, isolated from a user's game and skipped on headless CI."""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'mcpywrap/mcstudio/window_capture/mcpy-window-capture.exe'


@unittest.skipUnless(os.name == 'nt' and os.environ.get('MCPY_NATIVE_TESTS') == '1', 'opt-in interactive Windows desktop')
class NativeRecording(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = subprocess.Popen([sys.executable, str(ROOT / 'tests/manual_native_recording.py'),
            '--state', str(self.root / 'window.json')], creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(self.close_fixture)
        deadline = time.monotonic() + 5
        while not (self.root / 'window.json').exists():
            if self.fixture.poll() is not None or time.monotonic() > deadline:
                self.fail('Fixture window failed to start')
            time.sleep(.05)
        self.window = json.loads((self.root / 'window.json').read_text())
        self.user = C.WinDLL('user32')
        self.user.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        self.user.ShowWindow.argtypes = [W.HWND, C.c_int]

    def close_fixture(self):
        if self.fixture.poll() is None:
            self.fixture.terminate()
        self.fixture.wait(5)

    def record(self, duration=2, fps=12, ready=None):
        video = self.root / 'video.mp4'
        process = subprocess.Popen([str(HELPER), '--record', '--hwnd', str(self.window['hwnd']),
            '--duration', str(duration), '--fps', str(fps), '--output', str(video),
            '--mapping', str(self.root / 'mapping.jsonl'), '--stop-file', str(self.root / 'stop')],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        events = []
        while True:
            line = process.stdout.readline()
            if not line:
                break
            event = json.loads(line)
            events.append(event)
            if event['event'] == 'ready' and ready:
                ready()
        _, error = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, error.decode('utf-8', errors='replace'))
        return video, events

    def test_cfr_odd_dimensions_colors_orientation_and_exact_extraction(self):
        video, events = self.record(duration=3)
        complete = events[-1]
        self.assertEqual(complete['event'], 'completed')
        self.assertEqual(complete['frames_written'], 36)
        ready = events[0]
        self.assertEqual(ready['width'], (self.window['width'] + 1) & ~1)
        self.assertEqual(ready['height'], (self.window['height'] + 1) & ~1)
        mapping = [json.loads(line) for line in (self.root / 'mapping.jsonl').read_text().splitlines()]
        self.assertEqual([m['frame'] for m in mapping], list(range(36)))
        for index in (0, 18, 35):
            self.assertAlmostEqual(mapping[index]['time'], index / 12)
        extraction = subprocess.run([str(HELPER), '--extract', '--input', str(video), '--output', str(self.root),
            '--frames', '0,18,35'], capture_output=True, timeout=30)
        self.assertEqual(extraction.returncode, 0, extraction.stderr)
        for index in (0, 18, 35):
            self.assertTrue((self.root / ('frame-' + str(index) + '.png')).is_file())
        if shutil.which('ffprobe'):
            probe = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams', '-of', 'json', str(video)],
                                   capture_output=True, check=True)
            stream = json.loads(probe.stdout)['streams'][0]
            self.assertEqual(stream['codec_name'], 'h264')
            self.assertEqual(stream['nb_read_frames'], '36')
            self.assertEqual(stream['r_frame_rate'], '12/1')
        if shutil.which('ffmpeg'):
            frame = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(self.root / 'frame-0.png'),
                '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True).stdout
            width = ready['width']
            top = frame[(20 * width + 40) * 3:(20 * width + 40) * 3 + 3]
            bottom = frame[((self.window['height'] - 20) * width + 40) * 3:
                           ((self.window['height'] - 20) * width + 40) * 3 + 3]
            self.assertGreater(top[0], 200, top)
            self.assertLess(top[2], 40, top)
            self.assertGreater(bottom[2], 200, bottom)
            # Vertical markers expose decoder stride errors that flat horizontal bands hide.
            for row in (20, self.window['height'] - 20):
                marker = frame[(row * width + 8) * 3:(row * width + 8) * 3 + 3]
                self.assertGreater(marker[1], 180, marker)
                self.assertLess(marker[2], 60, marker)
        late = self.root / 'late'
        late.mkdir()
        result = subprocess.run([str(HELPER), '--extract', '--input', str(video), '--output', str(late),
                                 '--frames', '35'], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((late / 'frame-35.png').read_bytes(), (self.root / 'frame-35.png').read_bytes())
        result = subprocess.run([str(HELPER), '--extract', '--input', str(video), '--output', str(self.root),
                                 '--frames', '36'], capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)

    def test_black_frames_remain_valid(self):
        self.user.PostMessageW(self.window['hwnd'], 0x8001, 1, 0)
        time.sleep(.15)
        _, events = self.record(duration=1, fps=30)
        self.assertEqual(events[-1]['frames_written'], 30)

    def test_early_stop_and_minimize_finalize_short_clips(self):
        _, events = self.record(duration=10, ready=lambda: self.user.ShowWindow(self.window['hwnd'], 6))
        self.assertEqual(events[-1]['event'], 'completed')
        self.assertEqual(events[-1]['end_reason'], 'window_unavailable')
        self.assertLess(events[-1]['frames_written'], 120)

    def test_sixty_fps_and_explicit_stop(self):
        _, events = self.record(duration=1, fps=60)
        self.assertEqual(events[-1]['frames_written'], 60)

    def test_explicit_stop_finalizes(self):
        _, events = self.record(duration=10, ready=lambda: (self.root / 'stop').touch())
        self.assertEqual(events[-1]['event'], 'completed')
        self.assertEqual(events[-1]['end_reason'], 'requested_stop')
        self.assertLess(events[-1]['frames_written'], 120)


if __name__ == '__main__':
    unittest.main()

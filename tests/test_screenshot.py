import json
import os
from pathlib import Path
import socketserver
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib

from click.testing import CliRunner
from mcpywrap.cli import cli
from mcpywrap.engines.host import EngineError
from mcpywrap.mcstudio import screenshot
from mcpywrap.mcstudio.image import png_bytes


def png_rows(png):
    position, compressed = 8, bytearray()
    while position < len(png):
        length = struct.unpack('>I', png[position:position+4])[0]
        kind, body = png[position+4:position+8], png[position+8:position+8+length]
        if kind == b'IDAT': compressed.extend(body)
        position += 12 + length
    return zlib.decompress(compressed)


class ImageTests(unittest.TestCase):
    def test_windows_bgra_and_native_bottom_up_rgba_produce_same_colors(self):
        # Top row red/green, bottom row blue/white. Alpha is intentionally discarded.
        bgra = bytes([0,0,255,0, 0,255,0,0, 255,0,0,0, 255,255,255,0])
        rgba = bytes([0,0,255,255, 255,255,255,255, 255,0,0,255, 0,255,0,255])
        windows = png_bytes(2, 2, bgra)
        native = png_bytes(2, 2, rgba, rgba=True, bottom_up=True)
        self.assertEqual(windows, native)
        self.assertEqual(png_rows(native), b'\0\xff\0\0\0\xff\0\0\0\0\xff\xff\xff\xff')

    def test_windows_still_uses_the_existing_capture_path(self):
        with patch.object(screenshot.sessions, 'read', return_value={'backend': 'windows'}), \
             patch('mcpywrap.mcstudio.window.operate', return_value={'content': b'png'}) as operate:
            self.assertEqual(screenshot.capture('.', 'session', True), {'content': b'png'})
        operate.assert_called_once_with('.', 'session', 'screenshot', {'background_only': True})


@unittest.skipUnless(os.name == 'posix', 'Native launcher uses Unix sockets')
class NativeScreenshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='mcpy-shot-', dir='/tmp')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.metadata = self.root/'Contents/Resources/runtime.json'
        self.metadata.parent.mkdir(parents=True)
        self.metadata.write_text('{"screenshot_protocol":1}')
        self.game = {'pid': 123, 'executable': '/runtime/mcpelauncher-client'}
        self.session = {'backend': 'macos-arm64', 'state': 'running', 'game': self.game,
                        'project': str(self.root), 'launch': {'runtime': str(self.root), 'data': str(self.root)}}
        self.calls = []
        self.behavior = 'normal'
        self.pixels = bytes([0,0,255,255, 255,255,255,255, 255,0,0,255, 0,255,0,255])
        case = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                message = json.loads(self.rfile.readline())
                method, params = message['method'], message['params']
                case.calls.append((method, params))
                if method == 'status':
                    result = {} if case.behavior == 'old-process' else {'screenshot_protocol': 1}
                else:
                    identity, op = params['request_id'], params['op']
                    path = case.root/('screenshot-' + identity + '.rgba')
                    if op == 'release':
                        path.unlink(missing_ok=True)
                        result = {'state': 'released'}
                    elif case.behavior == 'busy':
                        result = {'state': 'failed', 'code': 'busy'}
                    elif case.behavior == 'timeout' or (case.behavior == 'queued' and op == 'capture'):
                        result = {'state': 'queued'}
                    else:
                        if case.behavior == 'symlink':
                            outside = case.root/'outside'; outside.write_bytes(case.pixels)
                            path.symlink_to(outside)
                        else:
                            path.write_bytes(case.pixels if case.behavior != 'short' else b'bad')
                            path.chmod(0o644 if case.behavior == 'public' else 0o600)
                        result = {'protocol': 1, 'request_id': identity, 'state': 'completed',
                                  'width': 2, 'height': 2, 'source_time_ns': 123456}
                        if case.behavior == 'wrong-id': result['request_id'] = 'b'*32
                        if case.behavior == 'oversized': result['width'] = screenshot.MAX_PIXELS
                self.wfile.write(json.dumps({'id': message['id'], 'result': result}).encode()+b'\n')

        self.server = socketserver.UnixStreamServer(str(self.root/'control.sock'), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        def close():
            self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.addCleanup(close)
        metadata = self.root/'python-control.json'
        metadata.write_text(json.dumps({'protocol': 1, 'pid': 123, 'socket': str(self.root/'control.sock')}))
        metadata.chmod(0o600)
        self.read = patch.object(screenshot.sessions, 'read', return_value=self.session).start()
        self.live = patch.object(screenshot, 'checked_process', return_value=True).start()
        self.addCleanup(patch.stopall)

    def capture(self):
        return screenshot.capture(self.root, 'a'*32, True)

    def test_public_cli_generates_png_and_releases_native_pixels(self):
        self.behavior = 'queued'
        output = self.root/'capture.png'
        args = ['--local', '--project', str(self.root), 'screenshot', '--session', 'a'*32,
                '--background-only', '--output', str(output), '--json']
        result = CliRunner().invoke(cli, args)
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.stdout)
        self.assertEqual(data['capture'], 'launcher-framebuffer')
        self.assertEqual(data['coordinate_space'], 'game-content')
        self.assertEqual((data['width'], data['height']), (2, 2))
        self.assertFalse(data['capture_fallback'])
        self.assertEqual(output.read_bytes(), png_bytes(2,2,self.pixels,rgba=True,bottom_up=True))
        self.assertFalse(list(self.root.glob('screenshot-*.rgba')))
        self.assertEqual([p['op'] for m,p in self.calls if m=='screenshot'], ['capture','poll','release'])
        calls = len(self.calls)
        self.assertNotEqual(CliRunner().invoke(cli,args).exit_code,0)
        self.assertEqual(len(self.calls),calls)  # Existing output is rejected before requesting a frame.

    def test_old_runtime_and_old_process_never_start_capture(self):
        self.metadata.write_text('{}')
        with self.assertRaises(EngineError) as caught: self.capture()
        self.assertEqual(caught.exception.code, 'capability_missing')
        self.assertEqual(self.calls, [])
        self.metadata.write_text('{"screenshot_protocol":1}')
        self.behavior = 'old-process'
        with self.assertRaises(EngineError) as caught: self.capture()
        self.assertEqual(caught.exception.code, 'capability_missing')
        self.assertEqual([m for m,p in self.calls], ['status'])

    def test_dead_or_foreign_session_is_rejected_before_rpc(self):
        for field, value in [('state','exited'), ('project',str(self.root/'other'))]:
            original = self.session[field]; self.session[field] = value
            with self.assertRaises(EngineError): self.capture()
            self.session[field] = original
        self.live.return_value = False
        with self.assertRaises(EngineError): self.capture()
        self.assertEqual(self.calls, [])

    def test_timeout_and_busy_release_only_the_current_request(self):
        for behavior, code in [('busy','busy'), ('timeout','capture_timeout')]:
            self.behavior = behavior
            with patch.object(screenshot.time, 'monotonic', side_effect=[0,7]), self.assertRaises(EngineError) as caught:
                self.capture()
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(self.calls[-1][1]['op'], 'release')

    def test_untrusted_artifacts_and_mismatched_responses_are_not_published(self):
        for behavior in ('short','public','symlink','wrong-id','oversized'):
            with self.subTest(behavior=behavior):
                self.behavior = behavior
                with self.assertRaises((EngineError,OSError)): self.capture()
                self.assertFalse(list(self.root.glob('screenshot-*.rgba')))
                self.assertEqual(self.calls[-1][1]['op'], 'release')

    def test_macos_recording_remains_explicitly_unsupported(self):
        from mcpywrap.mcstudio import recordings
        with patch.object(recordings, 'cleanup'), \
             patch('mcpywrap.mcstudio.window.session_game', side_effect=AssertionError('Windows target selection')):
            with self.assertRaises(recordings.RecordingError) as caught:
                recordings.start(self.root, 'a'*32)
        self.assertEqual(caught.exception.code, 'capability_missing')
        self.assertIn('Windows', str(caught.exception))

    def test_host_capabilities_follow_selected_runtime_without_enabling_video(self):
        from types import SimpleNamespace
        from mcpywrap.remote.service import capabilities
        backend = SimpleNamespace(id='macos-arm64', capabilities=(), managed_install=True,
                                  diagnose=lambda: {'ok': True, 'runtime': str(self.root)})
        with patch('mcpywrap.engines.backend.get_backend', return_value=backend):
            info = capabilities()
            self.assertIn('screenshot', info['capabilities'])
            self.assertNotIn('record', info['capabilities'])
            self.assertNotIn('record-frames', info['capabilities'])
            self.assertFalse(info['media']['record_available'])
            self.metadata.write_text('{}')
            self.assertNotIn('screenshot', capabilities()['capabilities'])


if __name__ == '__main__': unittest.main()

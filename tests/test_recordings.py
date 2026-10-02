"""Disk-backed recordings, task isolation, archive validation and real streaming HTTP."""
from contextlib import contextmanager
from email.message import Message
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import tracemalloc
import unittest
import uuid
from unittest.mock import Mock, patch
import zipfile

from click.testing import CliRunner
from mcpywrap.cli import cli
from mcpywrap.mcstudio import recordings as jobs, sessions, window
from mcpywrap.mcstudio import recording_worker
from mcpywrap.recording_io import transfer, unpack
from mcpywrap.remote import service as api
from mcpywrap.remote.client import Client
from mcpywrap.remote.http_server import GameHTTPServer


class RecordingFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'Windows 中文 project'
        self.project.mkdir()
        self.sid, self.rid = 'a' * 32, 'b' * 32
        self.addCleanup(patch.stopall)
        patch.object(jobs.tempfile, 'gettempdir', return_value=str(self.root)).start()
        session_dir = sessions.session_path(self.project, self.sid)
        session_dir.mkdir(parents=True)
        self.game = {'pid': 12, 'created_at': 1, 'executable': 'Minecraft.Windows.exe'}
        sessions.save(session_dir / 'session.json', {'session': self.sid, 'project': str(self.project),
            'origin': 'remote', 'state': 'exited', 'game': self.game, 'worker': None})

    def job(self, state='completed', size=64):
        path = jobs.record_path(self.project, self.sid, self.rid)
        path.parent.mkdir(exist_ok=True)
        data = {'project': str(self.project), 'session': self.sid, 'recording': self.rid,
                'request_id': self.rid, 'duration': 10, 'fps': 30, 'state': state,
                'created_at': time.time(), 'finished_at': time.time(), 'worker': None,
                'native': None, 'frames_written': 60, 'width': 2, 'height': 2, 'error': None}
        folder = jobs.payload(self.project, self.sid, self.rid)
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / 'video.mp4').open('wb') as stream:
            remaining = size
            while remaining:
                block = b'x' * min(remaining, jobs.CHUNK)
                stream.write(block)
                remaining -= len(block)
        data.update(size=size, sha256=jobs.digest(folder / 'video.mp4'))
        with (folder / 'mapping.jsonl').open('w', encoding='utf-8') as stream:
            for i in range(60):
                stream.write(json.dumps({'frame': i, 'time': i / 30, 'source_time_100ns': 100000 + i,
                                         'repeated': i > 0}) + '\n')
        sessions.save(path, data)
        return data

    def save(self, data):
        sessions.save(jobs.record_path(self.project, self.sid, self.rid), data)


class Jobs(RecordingFixture):
    def test_parameters_and_selector_contract(self):
        for duration, fps in ((0, 30), (301, 30), (10, 0), (10, 61), (True, 30), (10, 1.5)):
            with self.assertRaises(jobs.RecordingError):
                jobs.validate_parameters(duration, fps)
        data = self.job()
        self.assertEqual(jobs.frame_indices(data, [30, 0, 30]), [0, 30])
        self.assertEqual(jobs.frame_indices(data, times=[1, .05]), [1, 30])
        for frames, times in (([], []), ([0], [0]), ([60], []), ([-1], []), ([True], []),
                              ([], [float('nan')]), ([], [float('inf')]), ([0] * 101, [])):
            with self.assertRaises(jobs.RecordingError):
                jobs.frame_indices(data, frames, times)

    def test_idempotency_does_not_require_a_running_game(self):
        self.job()
        with patch.object(jobs, 'inspect_media') as media, patch.object(jobs.subprocess, 'Popen') as spawn:
            result = jobs.start(self.project, self.sid, 10, 30, self.rid)
        self.assertEqual(result['recording'], self.rid)
        spawn.assert_not_called()
        media.assert_not_called()
        with self.assertRaises(jobs.RecordingError) as error:
            jobs.start(self.project, self.sid, 11, 30, self.rid)
        self.assertEqual(error.exception.code, 'request_conflict')

    def test_start_ready_and_duplicate_session_reservation(self):
        def launched(*args, **kwargs):
            data = jobs.raw_record(self.project, self.sid, self.rid)
            data.update(state='recording', worker={'pid': 123})
            self.save(data)
            return Mock()
        with patch.object(window, 'session_game', return_value=self.game), \
             patch.object(jobs, 'inspect_media', return_value={'record_available': True}), \
             patch.object(jobs, 'checked_process', return_value=Mock()), \
             patch.object(jobs.subprocess, 'Popen', side_effect=launched) as spawn:
            self.assertEqual(jobs.start(self.project, self.sid, request_id=self.rid)['state'], 'recording')
            with self.assertRaises(jobs.RecordingError) as error:
                jobs.start(self.project, self.sid, request_id='c' * 32)
            self.assertEqual(error.exception.code, 'busy')
            self.assertEqual(spawn.call_count, 1)

    def test_start_timeout_preserves_id_for_recovery(self):
        with patch.object(window, 'session_game', return_value=self.game), \
             patch.object(jobs, 'inspect_media', return_value={'record_available': True}), \
             patch.object(jobs.subprocess, 'Popen'):
            with self.assertRaises(jobs.RecordingError) as error:
                jobs.start(self.project, self.sid, request_id=self.rid, timeout=0)
        self.assertEqual(error.exception.code, 'recording_timeout')
        self.assertIn(self.rid, error.exception.hint)
        self.assertEqual(jobs.read(self.project, self.sid, self.rid)['state'], 'starting')

    def test_stale_worker_marks_interrupted_and_refuses_reused_native_pid(self):
        data = self.job('recording')
        data.update(worker={'pid': 17}, native={'pid': 18})
        self.save(data)
        with patch.object(jobs, 'checked_process', side_effect=[None, ValueError('reused PID')]):
            result = jobs.read(self.project, self.sid, self.rid)
        self.assertEqual(result['state'], 'interrupted')
        with self.assertRaises(jobs.RecordingError):
            with jobs.artifact(self.project, self.sid, self.rid):
                self.fail('Incomplete video must not be downloadable')

    def test_expiry_and_manual_delete_do_not_remove_callers_copy(self):
        data = self.job()
        copied = self.root / 'copied.mp4'
        with jobs.artifact(self.project, self.sid, self.rid) as (video, info):
            with video.open('rb') as source:
                transfer(source, copied, info['size'], info['sha256'])
        data['finished_at'] -= jobs.RETENTION + 1
        self.save(data)
        jobs.cleanup(self.project)
        self.assertEqual(jobs.read(self.project, self.sid, self.rid)['state'], 'expired')
        self.assertFalse(jobs.payload(self.project, self.sid, self.rid).exists())
        self.assertTrue(copied.exists())

    def test_download_pin_blocks_delete_and_expiry(self):
        data = self.job()
        with jobs.artifact(self.project, self.sid, self.rid):
            with self.assertRaises(jobs.RecordingError) as error:
                jobs.delete(self.project, self.sid, self.rid)
            self.assertEqual(error.exception.code, 'busy')
            data['finished_at'] -= jobs.RETENTION + 1
            self.save(data)
            jobs.cleanup(self.project)
            self.assertTrue(jobs.payload(self.project, self.sid, self.rid).exists())
        jobs.cleanup(self.project)
        self.assertEqual(jobs.read(self.project, self.sid, self.rid)['state'], 'expired')

    def test_streamed_frames_and_mapping_after_game_exit(self):
        self.job()
        def extract(arguments, **kwargs):
            target = Path(arguments[arguments.index('--output') + 1])
            for index in arguments[-1].split(','):
                (target / ('frame-' + index + '.png')).write_bytes(window.png_bytes(2, 2, b'\xff\0\0\0' * 4))
            return Mock(returncode=0)
        with patch.object(jobs, 'helper', return_value=Path('helper.exe')), \
             patch.object(jobs.subprocess, 'run', side_effect=extract):
            with jobs.frames_archive(self.project, self.sid, self.rid, [30, 0]) as (archive, info):
                target = self.root / 'frames'
                with archive.open('rb') as source:
                    transfer(source, target, info['size'], info['sha256'], publish=False)
        manifest = json.loads((target / 'manifest.json').read_text())
        self.assertEqual([e['frame'] for e in manifest['frames']], [0, 30])
        self.assertTrue(manifest['frames'][1]['repeated'])
        self.assertIn('source_time', manifest['frames'][0])

    def test_session_stop_finishes_recording_before_game_termination(self):
        with patch.object(sessions, 'read', return_value={'game': self.game, 'worker': None, 'state': 'running'}), \
             patch.object(jobs, 'stop_session') as stop_recording, \
             patch.object(sessions, 'checked_process', return_value=Mock()) as game:
            actions = []
            stop_recording.side_effect = lambda *a: actions.append('recording')
            game.return_value.terminate.side_effect = lambda: actions.append('game')
            sessions.stop(self.project, self.sid)
        self.assertEqual(actions, ['recording', 'game'])

    def test_worker_publishes_only_after_successful_native_finalization(self):
        for events, returncode, expected in (([{'event': 'ready', 'width': 2, 'height': 2},
                {'event': 'finalizing'}, {'event': 'completed', 'frames_written': 10,
                 'frames_captured': 7, 'frames_repeated': 3, 'source_frames_skipped': 0,
                 'end_reason': 'requested_stop'}], 0, 'completed'),
                ([{'event': 'cancelled'}], 0, 'cancelled'),
                ([{'event': 'ready', 'width': 2, 'height': 2}], 0, 'failed'),
                ([{'event': 'completed', 'frames_written': 10}], 2, 'failed')):
            with self.subTest(expected=expected, returncode=returncode):
                self.rid = uuid.uuid4().hex
                path = jobs.record_path(self.project, self.sid, self.rid)
                path.parent.mkdir(exist_ok=True)
                sessions.save(path, {'project': str(self.project), 'session': self.sid, 'recording': self.rid,
                    'state': 'starting', 'duration': 10, 'fps': 30, 'game': self.game, 'frames_written': 0})
                target = Mock()
                target._client_area.return_value = (2, 2, None)
                target.hwnd = 1
                target.owner.return_value = self.game['pid']
                target.usable.return_value = True
                target.user.IsIconic.return_value = False
                process = Mock()
                process.stdout = io.BytesIO(b''.join(json.dumps(e).encode() + b'\n' for e in events))
                process.poll.return_value = returncode
                process.returncode = returncode
                def spawn(*args, **kwargs):
                    (jobs.payload(self.project, self.sid, self.rid) / 'video.partial.mp4').write_bytes(b'video')
                    return process
                with patch.object(recording_worker, 'GameWindow', return_value=target), \
                     patch.object(recording_worker, 'identity', return_value={'pid': 123}), \
                     patch.object(recording_worker, 'desktop_state', return_value={'available': True}), \
                     patch.object(jobs, 'helper', return_value=Path('helper.exe')), \
                     patch.object(recording_worker.subprocess, 'Popen', side_effect=spawn):
                    recording_worker.run(self.project, self.sid, self.rid)
                data = jobs.raw_record(self.project, self.sid, self.rid)
                self.assertEqual(data['state'], expected)
                self.assertEqual((jobs.payload(self.project, self.sid, self.rid) / 'video.mp4').exists(), expected == 'completed')
                if expected == 'completed':
                    self.assertTrue(data['truncated'])
                    self.assertEqual(data['end_reason'], 'requested_stop')
                target.close.assert_called_once()

    def test_cancel_before_worker_starts_does_not_open_window_or_spawn_native(self):
        data = self.job('starting')
        data['game'] = self.game
        self.save(data)
        jobs.record_path(self.project, self.sid, self.rid).with_suffix('.stop').touch()
        with patch.object(recording_worker, 'identity', return_value={'pid': 123}), \
             patch.object(recording_worker, 'GameWindow') as target, \
             patch.object(recording_worker.subprocess, 'Popen') as spawn:
            self.assertEqual(recording_worker.run(self.project, self.sid, self.rid), 0)
        target.assert_not_called()
        spawn.assert_not_called()
        self.assertEqual(jobs.raw_record(self.project, self.sid, self.rid)['state'], 'cancelled')


class Transfers(RecordingFixture):
    def test_small_rpc_does_not_preallocate_the_response_limit_on_python39(self):
        class LegacyHTTPResponse(io.BytesIO):
            status = 200
            headers = Message()
            def read(self, amount):
                buffer = bytearray(amount)
                content = super().read(amount)
                buffer[:len(content)] = content
                return bytes(memoryview(buffer)[:len(content)])
        client = Client('http://example.test', self.root)
        response = LegacyHTTPResponse(b'{"ok":true,"value":1}')
        tracemalloc.start()
        try:
            with patch.object(client.opener, 'open', return_value=response):
                self.assertEqual(client.request('GET', '/capabilities')['value'], 1)
            self.assertLess(tracemalloc.get_traced_memory()[1], 4 * jobs.CHUNK)
        finally:
            tracemalloc.stop()

    def test_hash_length_disconnect_and_overwrite_leave_no_final_output(self):
        target = self.root / 'clip.mp4'
        data = b'contents'
        sha = hashlib.sha256(data).hexdigest()
        for content, size, digest in ((b'bad', len(data), sha), (data, len(data), '0' * 64), (data, 1, sha)):
            with self.assertRaises(jobs.RecordingError):
                transfer(io.BytesIO(content), target, size, digest)
            self.assertFalse(target.exists())
            self.assertFalse(list(self.root.glob('*.part')))
        target.write_bytes(b'old')
        with self.assertRaises(FileExistsError):
            transfer(io.BytesIO(data), target, len(data), sha)
        self.assertEqual(target.read_bytes(), b'old')

    def test_large_transfer_uses_fixed_size_reads(self):
        data = b'x' * jobs.CHUNK
        class BoundedSource:
            remaining = 68
            def read(self, size):
                self_test.assertEqual(size, jobs.CHUNK)
                if not self.remaining:
                    return b''
                self.remaining -= 1
                return data
        self_test = self
        sha = hashlib.sha256()
        for _ in range(68):
            sha.update(data)
        tracemalloc.start()
        try:
            transfer(BoundedSource(), self.root / 'large.mp4', 68 * jobs.CHUNK, sha.hexdigest())
            self.assertLess(tracemalloc.get_traced_memory()[1], 8 * jobs.CHUNK)
        finally:
            tracemalloc.stop()

    def test_archive_traversal_and_unexpected_entries_are_rejected(self):
        archive = self.root / 'bad.zip'
        png = window.png_bytes(1, 1, b'\0\0\xff\0')
        manifest = {'frames': [{'frame': 0, 'image': 'frame-0.png', 'size': len(png),
                                'sha256': hashlib.sha256(png).hexdigest()}]}
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.writestr('manifest.json', json.dumps(manifest))
            bundle.writestr('frame-0.png', png)
            bundle.writestr('../escape', b'bad')
        target = self.root / 'frames'
        with self.assertRaises(jobs.RecordingError):
            unpack(archive, target)
        self.assertFalse(target.exists())
        self.assertFalse((self.root / 'escape').exists())

    def test_stream_disconnect_cleans_temporary_file(self):
        class Disconnected:
            calls = 0
            def read(self, size):
                self.calls += 1
                if self.calls == 1:
                    return b'partial'
                raise ConnectionResetError('disconnected')
        target = self.root / 'clip.mp4'
        with self.assertRaises(ConnectionResetError):
            transfer(Disconnected(), target, 100, '0' * 64)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('*.part')))


class RemoteRecordings(RecordingFixture):
    def setUp(self):
        super().setUp()
        self.job()
        self.service = api.GameService(self.project)
        patch.object(api, 'capabilities', return_value={'protocol_version': 1,
                     'capabilities': api.ACTIONS + ['record', 'record-frames']}).start()
        self.http = GameHTTPServer(('127.0.0.1', 0), self.service, token='fixture-token')
        self.thread = threading.Thread(target=self.http.serve_forever, kwargs={'poll_interval': .01})
        self.thread.start()
        self.addCleanup(self.shutdown)
        self.url = 'http://127.0.0.1:' + str(self.http.server_port)
        self.client = Client(self.url, self.root, token='fixture-token')
        patch.dict(os.environ, {'MCPY_REMOTE_TOKEN': 'fixture-token'}).start()

    def shutdown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(2)

    def call(self, *args):
        return CliRunner().invoke(cli, ['--remote', self.url, '--project', str(self.root),
                                      '--non-interactive', 'record', *args, '--json'])

    def test_record_status_does_not_route_to_game_status(self):
        result = self.call('status', '--session', self.sid, '--recording', self.rid)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.output)['recording'], self.rid)
        result = self.call('status', '--session', self.sid, '--list')
        self.assertEqual(len(json.loads(result.output)['recordings']), 1)

    def test_recording_does_not_take_input_lock(self):
        self.service.desktop_lock.acquire()
        try:
            result = self.call('status', '--session', self.sid, '--recording', self.rid)
            self.assertEqual(result.exit_code, 0, result.output)
            with patch.object(jobs, 'start', return_value={'state': 'recording', 'recording': self.rid}):
                result = self.call('start', '--session', self.sid)
                self.assertEqual(result.exit_code, 0, result.output)
        finally:
            self.service.desktop_lock.release()
        with jobs.file_lock(jobs.directory(self.project, self.sid) / 'recording.lock'), \
             patch.object(window, 'operate', return_value={'sent': True, 'released': True}):
            self.assertTrue(self.service.desktop(self.sid, 'key', {'keys': ['W']})['sent'])

    def test_service_close_stops_recordings_even_after_game_exit(self):
        with patch.object(jobs, 'stop_session') as stop:
            self.service.close()
        stop.assert_called_once_with(self.project, self.sid)
        self.assertTrue(self.service.closing.is_set())

    def test_recording_cleanup_failure_does_not_skip_game_cleanup(self):
        with patch.object(jobs, 'stop_session', side_effect=ValueError('recording cleanup failed')), \
             patch.object(self.service, 'list_sessions', return_value={'sessions': [{'session': self.sid, 'state': 'running'}]}), \
             patch.object(self.service, 'stop') as stop:
            with self.assertRaises(api.RemoteError) as error:
                self.service.close()
        self.assertEqual(error.exception.code, 'cleanup_failed')
        stop.assert_called_once_with(self.sid)

    def test_remote_frame_archive_uses_the_same_streaming_download(self):
        def extract(arguments, **kwargs):
            target = Path(arguments[arguments.index('--output') + 1])
            for index in arguments[-1].split(','):
                (target / ('frame-' + index + '.png')).write_bytes(window.png_bytes(2, 2, b'\xff\0\0\0' * 4))
            return Mock(returncode=0)
        output = self.root / 'remote-frames'
        with patch.object(jobs, 'helper', return_value=Path('helper.exe')), \
             patch.object(jobs.subprocess, 'run', side_effect=extract):
            result = self.call('frames', '--session', self.sid, '--recording', self.rid,
                               '--at', '0', '--at', '1', '--output', str(output))
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.output)
        self.assertEqual([e['frame'] for e in data['frames']], [0, 30])
        self.assertTrue(all(Path(image).is_file() for image in data['images']))

    def test_authenticated_download_over_64_mib_is_bounded(self):
        self.job(size=68 * jobs.CHUNK)
        output = self.root / 'download.mp4'
        tracemalloc.start()
        try:
            result = self.call('download', '--session', self.sid, '--recording', self.rid, '--output', str(output))
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertLess(tracemalloc.get_traced_memory()[1], 16 * jobs.CHUNK)
        finally:
            tracemalloc.stop()
        self.assertEqual(output.stat().st_size, 68 * jobs.CHUNK)
        result = self.call('download', '--session', self.sid, '--recording', self.rid, '--output', str(output))
        self.assertNotEqual(result.exit_code, 0)
        with self.assertRaises(ValueError):
            Client(self.url, self.root, token='wrong').download('GET',
                '/sessions/' + self.sid + '/recordings/' + self.rid + '/video', self.root / 'unauthorized.mp4')

    def test_unknown_fields_and_cross_session_recording_are_rejected(self):
        path = '/sessions/' + self.sid + '/recordings'
        for data in ({'output': 'C:/private'}, {'duration': True}, {'fps': 61}):
            with self.assertRaises(ValueError):
                self.client.request('POST', path, data)
        with self.assertRaises(ValueError):
            self.client.request('GET', path + '/' + 'c' * 32)


if __name__ == '__main__':
    unittest.main()

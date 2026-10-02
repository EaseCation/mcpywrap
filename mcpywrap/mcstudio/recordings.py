"""Session-owned recording jobs and bounded, disk-backed artifacts."""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile

from . import sessions
from .processes import background_options, checked_process

CHUNK = 1024 * 1024
MAX_VIDEO = 2 * 1024 ** 3
RETENTION = 24 * 60 * 60
ACTIVE = {'starting', 'recording', 'finalizing'}


class RecordingError(ValueError):
    def __init__(self, message, code='recording_failed', hint=None, status=400):
        super().__init__(message)
        self.code, self.hint, self.status = code, hint, status


def identifier(value):
    if not isinstance(value, str) or len(value) != 32 or any(c not in '0123456789abcdef' for c in value):
        raise RecordingError('Invalid session/recording/request ID', 'invalid_request')
    return value


@contextmanager
def file_lock(path, wait=0):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('a+b')
    try:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b'0')
            stream.flush()
        deadline = time.monotonic() + wait
        while True:
            stream.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RecordingError('Recording resource is busy', 'busy', status=409) from None
                time.sleep(.02)
        yield
    finally:
        stream.close()


def directory(project, session):
    return sessions.session_path(project, identifier(session)) / 'recordings'


def record_path(project, session, recording):
    return directory(project, session) / (identifier(recording) + '.json')


def payload(project, session, recording):
    owner = hashlib.sha256(os.path.normcase(str(Path(project).resolve())).encode('utf-8')).hexdigest()[:24]
    base = Path(tempfile.gettempdir()) / 'mcpywrap-recordings' / owner
    target = base / identifier(session) / identifier(recording)
    # Never follow an artifact-directory link out of this owner's temporary namespace.
    if target.resolve() != base.resolve() / session / recording:
        raise RecordingError('Recording artifact directory was redirected', 'invalid_artifact')
    return target


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(CHUNK), b''):
            result.update(block)
    return result.hexdigest()


def helper():
    from .window import GameWindow
    return GameWindow._background_helper(None)


def inspect_media():
    result = {'component_available': False, 'wgc': False, 'h264_encoder': False,
              'h264_decoder': False, 'record_available': False, 'frames_available': False}
    if os.name != 'nt':
        result['reason'] = 'Recording execution requires Windows'
        return result
    try:
        executable = helper()
        manifest = json.loads(executable.with_name('manifest.json').read_text(encoding='utf-8'))
        if manifest.get('media_protocol') != 1:
            raise ValueError('Native helper does not support recording protocol 1')
        result['component_available'] = True
        probe = subprocess.run([str(executable), '--capabilities'], stdin=subprocess.DEVNULL,
                               capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        if probe.returncode:
            raise ValueError('Windows media capability probe failed')
        info = json.loads(probe.stdout)
        if info.get('protocol') != 1:
            raise ValueError('Unsupported native media protocol')
        for key in ('wgc', 'h264_encoder', 'h264_decoder'):
            result[key] = info.get(key) is True
        result['record_available'] = result['wgc'] and result['h264_encoder']
        result['frames_available'] = result['h264_decoder']
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        result['reason'] = str(exc)
    return result


def validate_parameters(duration, fps):
    if type(duration) is not int or not 1 <= duration <= 300:
        raise RecordingError('duration must be an integer in 1..300', 'invalid_request')
    if type(fps) is not int or not 1 <= fps <= 60:
        raise RecordingError('fps must be an integer in 1..60', 'invalid_request')


def raw_record(project, session, recording):
    path = record_path(project, session, recording)
    if not path.is_file():
        raise RecordingError('Recording not found in this session', 'recording_not_found', status=404)
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('session') != session or data.get('recording') != recording or data.get('project') != str(Path(project).resolve()):
        raise RecordingError('Recording ownership mismatch', 'invalid_artifact')
    return data


def read(project, session, recording):
    data = raw_record(project, session, recording)
    if data['state'] in ACTIVE:
        worker = data.get('worker')
        if worker:
            try:
                live = checked_process(worker)
            except ValueError:
                live = None
        else:
            live = time.time() - data['created_at'] < 30
        if not live:
            with file_lock(record_path(project, session, recording).with_suffix('.artifact.lock')):
                data = raw_record(project, session, recording)
                if data['state'] in ACTIVE:
                    native = data.get('native')
                    if native:
                        try:
                            process = checked_process(native)
                            if process:
                                process.terminate()
                                process.wait(timeout=5)
                        except ValueError:
                            pass  # Never terminate a reused identity.
                    data.update(state='interrupted', error='Recording worker exited', finished_at=time.time())
                    sessions.save(record_path(project, session, recording), data)
    return data


def cleanup(project):
    root = Path(project) / '.runtime' / 'sessions'
    for path in root.glob('*/recordings/*.json'):
        try:
            session, recording = path.parent.parent.name, path.stem
            data = read(project, session, recording)
            if data['state'] not in ACTIVE | {'deleted', 'expired'} and time.time() - data.get('finished_at', time.time()) >= RETENTION:
                delete(project, session, recording, expired=True)
        except RecordingError as exc:
            if exc.code != 'busy':
                raise


def status(project, session, recording=None):
    sessions.read(project, session)
    cleanup(project)
    if recording:
        return read(project, session, recording)
    return {'session': session, 'recordings': [read(project, session, p.stem)
            for p in sorted(directory(project, session).glob('*.json'))]}


def start(project, session, duration=10, fps=30, request_id=None, timeout=15):
    from .window import session_game
    validate_parameters(duration, fps)
    request_id = identifier(request_id or uuid.uuid4().hex)
    project = Path(project).resolve()
    cleanup(project)
    path = record_path(project, session, request_id)
    with file_lock(directory(project, session) / 'start.lock', wait=5):
        if path.exists():
            existing = read(project, session, request_id)
            if (existing['duration'], existing['fps']) != (duration, fps):
                raise RecordingError('Request ID already used with different parameters', 'request_conflict', status=409)
        else:
            game = session_game(project, session)
            for item in directory(project, session).glob('*.json'):
                if read(project, session, item.stem)['state'] in ACTIVE:
                    raise RecordingError('This session already has an active recording', 'busy', status=409)
            media = inspect_media()
            if not media['record_available']:
                raise RecordingError(media.get('reason') or 'WGC/software H.264 encoder unavailable', 'capability_missing')
            data = {'project': str(project), 'session': session, 'recording': request_id,
                    'request_id': request_id, 'duration': duration, 'fps': fps, 'state': 'starting',
                    'created_at': time.time(), 'worker': None, 'native': None, 'game': game,
                    'frames_written': 0, 'error': None, 'capture': 'background-window'}
            sessions.save(path, data)
            with path.with_suffix('.log').open('wb') as log:
                try:
                    subprocess.Popen([sys.executable, '-m', 'mcpywrap.mcstudio.recording_worker',
                                      str(project), session, request_id], cwd=project,
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     env=dict(os.environ, PYTHONIOENCODING='utf-8'), **background_options())
                except OSError as exc:
                    data.update(state='failed', error=str(exc), finished_at=time.time())
                    sessions.save(path, data)
                    raise
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = read(project, session, request_id)
        if data['state'] != 'starting':
            return {**data, 'ok': data['state'] in {'recording', 'finalizing', 'completed'}}
        time.sleep(.05)
    raise RecordingError('Recording startup result unknown', 'recording_timeout',
                         hint='Query record status --session ' + session + ' --recording ' + request_id)


def stop(project, session, recording, timeout=10):
    data = read(project, session, recording)
    if data['state'] not in ACTIVE:
        return data
    record_path(project, session, recording).with_suffix('.stop').touch()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = read(project, session, recording)
        if data['state'] not in ACTIVE:
            return data
        time.sleep(.05)
    # Only retire processes whose saved identity still matches.
    for key in ('native', 'worker'):
        if data.get(key):
            try:
                process = checked_process(data[key])
                if process:
                    process.terminate()
                    process.wait(timeout=5)
            except ValueError:
                pass
    return read(project, session, recording)


def stop_session(project, session):
    for path in directory(project, session).glob('*.json'):
        data = read(project, session, path.stem)
        if data['state'] in ACTIVE:
            stop(project, session, path.stem)


def delete(project, session, recording, expired=False):
    path = record_path(project, session, recording)
    read(project, session, recording)
    with file_lock(path.with_suffix('.artifact.lock')):
        data = raw_record(project, session, recording)
        if data['state'] in ACTIVE:
            raise RecordingError('Stop the recording before deleting it', 'busy', status=409)
        if data['state'] not in {'deleted', 'expired'}:
            folder = payload(project, session, recording)
            if folder.exists():
                shutil.rmtree(folder)
            data.update(state='expired' if expired else 'deleted', artifact_available=False)
            sessions.save(path, data)
        return data


@contextmanager
def artifact(project, session, recording):
    path = record_path(project, session, recording)
    cleanup(project)
    read(project, session, recording)
    with file_lock(path.with_suffix('.artifact.lock')):
        data = raw_record(project, session, recording)
        if data['state'] != 'completed':
            raise RecordingError('Recording has no completed artifact: ' + data['state'], 'artifact_unavailable', status=409)
        video = payload(project, session, recording) / 'video.mp4'
        if not video.is_file() or video.stat().st_size != data['size']:
            raise RecordingError('Recording video is missing or changed', 'invalid_artifact')
        yield video, data


def frame_indices(data, frames=(), times=()):
    if bool(frames) == bool(times) or len(frames) + len(times) > 100:
        raise RecordingError('Specify 1..100 --frame values or --at values', 'invalid_request')
    if times:
        if any(type(t) not in (int, float) or not math.isfinite(t) or t < 0 for t in times):
            raise RecordingError('Invalid frame time', 'invalid_request')
        if any(t >= data['frames_written'] / data['fps'] for t in times):
            raise RecordingError('Frame time out of range', 'invalid_request')
        frames = [math.floor(t * data['fps']) for t in times]
    if any(type(i) is not int or not 0 <= i < data['frames_written'] for i in frames):
        raise RecordingError('Frame out of range', 'invalid_request')
    return sorted(set(frames))


@contextmanager
def frames_archive(project, session, recording, frames=(), times=()):
    with artifact(project, session, recording) as (video, data):
        selected = frame_indices(data, frames, times)
        with tempfile.TemporaryDirectory(prefix='frames-', dir=video.parent) as temporary:
            folder = Path(temporary)
            try:
                result = subprocess.run([str(helper()), '--extract', '--input', str(video), '--output', str(folder),
                                         '--frames', ','.join(map(str, selected))], stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300,
                                        **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
            except subprocess.TimeoutExpired:
                raise RecordingError('Frame extraction timed out; request fewer frames', 'frames_timeout') from None
            if result.returncode:
                raise RecordingError('Frame extraction failed: ' + result.stderr.decode('utf-8', errors='replace')[:2000])
            entries = []
            with (video.parent / 'mapping.jsonl').open(encoding='utf-8') as stream:
                for line in stream:
                    entry = json.loads(line)
                    if entry['frame'] in selected:
                        entry['source_time'] = entry['source_time_100ns'] / 10 ** 7
                        image = folder / ('frame-' + str(entry['frame']) + '.png')
                        entry.update(image=image.name, sha256=digest(image), size=image.stat().st_size)
                        entries.append(entry)
            if [e['frame'] for e in entries] != selected:
                raise RecordingError('Incomplete frame mapping', 'invalid_artifact')
            manifest = {'session': session, 'recording': recording, 'fps': data['fps'],
                        'width': data['width'], 'height': data['height'], 'frames': entries}
            (folder / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=True), encoding='utf-8')
            archive = folder / 'frames.zip'
            with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as bundle:
                bundle.write(folder / 'manifest.json', 'manifest.json')
                for entry in entries:
                    bundle.write(folder / entry['image'], entry['image'])
            if archive.stat().st_size > MAX_VIDEO:
                raise RecordingError('Frame archive exceeds 2 GiB', 'artifact_too_large')
            yield archive, {'size': archive.stat().st_size, 'sha256': digest(archive)}

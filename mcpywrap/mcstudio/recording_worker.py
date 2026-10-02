"""Detached recording supervisor; owns state writes and never takes the input lock."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from . import recordings as jobs, sessions
from .processes import background_options, identity
from .window import GameWindow, desktop_state


def receive(stream, events):
    try:
        while True:
            line = stream.readline(4097)
            if not line:
                break
            if len(line) > 4096 or not line.endswith(b'\n'):
                raise ValueError('Native event exceeds protocol limit')
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError('Invalid native recording event')
            events.put(event)
    except Exception as exc:
        events.put({'event': 'protocol_error', 'error': str(exc)})
    finally:
        events.put({'event': 'eof'})


def run(project, session, recording):
    path = jobs.record_path(project, session, recording)
    data = jobs.raw_record(project, session, recording)
    process = None
    window = None
    completed = False
    reader = None
    events = queue.Queue(maxsize=8)
    try:
        with jobs.file_lock(jobs.directory(project, session) / 'recording.lock'):
            data['worker'] = identity(os.getpid())
            sessions.save(path, data)
            stop_path = path.with_suffix('.stop')
            if stop_path.exists():
                data.update(state='cancelled', end_reason='requested_stop', artifact_available=False)
                return 0
            folder = jobs.payload(project, session, recording)
            folder.mkdir(parents=True, exist_ok=False)
            window = GameWindow(data['game'])
            width, height, _ = window._client_area(require_foreground=False, require_uncovered=False)
            if width * height > 16000000 or window.user.IsIconic(window.hwnd):
                raise ValueError('Game window is unavailable for recording')
            with path.with_suffix('.native.log').open('wb') as errors:
                process = subprocess.Popen([str(jobs.helper()), '--record', '--hwnd', str(int(window.hwnd)),
                    '--fps', str(data['fps']), '--duration', str(data['duration']),
                    '--output', str(folder / 'video.partial.mp4'), '--mapping', str(folder / 'mapping.jsonl'),
                    '--stop-file', str(stop_path)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=errors, **background_options())
                data['native'] = identity(process.pid)
                sessions.save(path, data)
                reader = threading.Thread(target=receive, args=(process.stdout, events), daemon=True)
                reader.start()
                ready_at = None
                stop_reason = None
                finalizing_at = None
                launched = time.monotonic()
                while True:
                    if data['state'] in ('starting', 'recording'):
                        try:
                            window.validate_process()
                            if window.owner(window.hwnd) != data['game']['pid'] or not window.usable(window.hwnd):
                                raise ValueError('window_unavailable')
                            if window.user.IsIconic(window.hwnd):
                                raise ValueError('window_minimized')
                            if not desktop_state()['available']:
                                raise ValueError('desktop_unavailable')
                        except ValueError as exc:
                            stop_reason = str(exc)
                            stop_path.touch()
                    if ready_at is None and time.monotonic() - launched > 15:
                        raise ValueError('Native capture startup timed out')
                    if ready_at and time.monotonic() - ready_at > data['duration'] + 15:
                        raise ValueError('Native recording exceeded its deadline')
                    if finalizing_at and time.monotonic() - finalizing_at > 10:
                        raise ValueError('MP4 finalization timed out')
                    partial = folder / 'video.partial.mp4'
                    if partial.exists() and partial.stat().st_size > jobs.MAX_VIDEO:
                        raise ValueError('Video exceeds 2 GiB')
                    try:
                        event = events.get(timeout=.1)
                    except queue.Empty:
                        continue
                    kind = event.pop('event')
                    if kind == 'eof':
                        break
                    if kind == 'protocol_error':
                        raise ValueError(event['error'])
                    if kind == 'ready':
                        data.update(event, state='recording', frames_written=1, started_at=time.time())
                        ready_at = time.monotonic()
                    elif kind == 'progress':
                        data['frames_written'] = event['frames_written']
                    elif kind == 'finalizing':
                        data['state'] = 'finalizing'
                        finalizing_at = time.monotonic()
                    elif kind == 'completed':
                        data.update(event)
                        if stop_reason:
                            data['end_reason'] = stop_reason
                        completed = True
                    elif kind == 'cancelled':
                        data.update(state='cancelled', end_reason=stop_reason or 'requested_stop')
                    else:
                        raise ValueError('Unknown native event')
                    sessions.save(path, data)
                process.wait(timeout=10)
                if process.returncode:
                    with path.with_suffix('.native.log').open('rb') as log:
                        raise ValueError('Native recording failed: ' + log.read(4096).decode('utf-8', errors='replace'))
                if completed:
                    size = partial.stat().st_size
                    if not 0 < size <= jobs.MAX_VIDEO:
                        raise ValueError('Invalid MP4 size')
                    sha256 = jobs.digest(partial)
                    partial.rename(folder / 'video.mp4')
                    data.update(state='completed', size=size, sha256=sha256, artifact_available=True,
                                actual_duration=data['frames_written'] / data['fps'],
                                truncated=data['frames_written'] != data['duration'] * data['fps'])
                elif data['state'] != 'cancelled':
                    raise ValueError('Native process did not finalize the video')
    except Exception as exc:
        data.update(state='failed', error=str(exc), artifact_available=False)
    finally:
        if process:
            try:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired) as exc:
                data.update(state='failed', error='Native cleanup failed: ' + str(exc), artifact_available=False)
            finally:
                process.stdout.close()
        if window:
            window.close()
        data['finished_at'] = time.time()
        sessions.save(path, data)
    return 0 if data['state'] in ('completed', 'cancelled') else 1


if __name__ == '__main__':
    raise SystemExit(run(Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3]))

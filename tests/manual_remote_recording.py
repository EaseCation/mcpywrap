"""Opt-in real Windows remote-protocol acceptance against a loopback-hosted game session."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

from mcpywrap.remote.service import GameService
from mcpywrap.remote.http_server import GameHTTPServer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--command', default='mcpy')
    args = parser.parse_args()
    project = args.project.resolve()
    project.mkdir(parents=True, exist_ok=True)
    service = GameService(project / 'Windows-service')
    token = uuid.uuid4().hex
    server = GameHTTPServer(('127.0.0.1', 0), service, token=token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = 'http://127.0.0.1:' + str(server.server_port)
    environment = dict(os.environ, MCPY_REMOTE_TOKEN=token, PYTHONIOENCODING='utf-8')
    def call(*parameters, allow_error=False):
        result = subprocess.run([args.command, '--remote', endpoint, '--project', str(project),
            '--non-interactive', *parameters, '--json'], capture_output=True,
            text=True, encoding='utf-8', timeout=120, env=environment)
        data = json.loads(result.stdout)
        print(json.dumps(data, ensure_ascii=True), flush=True)
        if result.returncode and not allow_error:
            raise RuntimeError(data.get('error'))
        return data
    session = None
    try:
        call('doctor', '--capabilities')
        # No external server is required: this verifies the game process/capture, not joining a server.
        session = call('connect', '127.0.0.1', '--port', '19132', '--detach')['session']
        deadline = time.monotonic() + 60
        while True:
            probe = call('screenshot', '--session', session, '--output', str(project / ('ready-' + session + '.png')),
                         allow_error=True)
            if probe['ok']:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('Remote game window was not ready')
            time.sleep(1)
        recording = call('record', 'start', '--session', session, '--duration', '5', '--fps', '30')['recording']
        call('key', '--session', session, 'W', '--hold-ms', '500')
        deadline = time.monotonic() + 20
        while True:
            state = call('record', 'status', '--session', session, '--recording', recording)
            if state['state'] == 'completed':
                break
            if state['state'] not in ('starting', 'recording', 'finalizing') or time.monotonic() >= deadline:
                raise RuntimeError('Remote recording did not complete')
            time.sleep(.5)
        video = project / ('remote-' + recording + '.mp4')
        call('stop', '--session', session)
        call('record', 'download', '--session', session, '--recording', recording, '--output', str(video))
        call('record', 'frames', '--session', session, '--recording', recording,
             '--frame', '0', '--frame', '75', '--frame', '149', '--output', str(project / ('frames-' + recording)))
        call('record', 'delete', '--session', session, '--recording', recording)
        print(json.dumps({'ok': True, 'video': str(video), 'frames': state['frames_written'],
                          'network_connection_verified': False, 'transport': 'authenticated-loopback'}))
    finally:
        try:
            service.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)


if __name__ == '__main__':
    main()

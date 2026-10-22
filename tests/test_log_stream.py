import json
import itertools
import os
from contextlib import ExitStack
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from mcpywrap_core.cli import cli
from mcpywrap_core.mcstudio.log_stream import LogCursor, follow, CHUNK, HISTORY_LIMIT


class LogStreamTests(unittest.TestCase):
    def test_incremental_utf8_and_repeated_lines_are_not_lost_or_duplicated(self):
        with tempfile.TemporaryDirectory() as root, ExitStack() as stack:
            path = Path(root)/'game.log'
            path.write_bytes(b'old\n')
            cursor = stack.enter_context(LogCursor(path, 1))
            self.assertEqual(cursor.read()[0], 'old\n')
            data = '中文\n中文\n'.encode('utf-8')
            with path.open('ab') as stream:
                stream.write(data[:2])
            self.assertEqual(cursor.read()[0], '')
            with path.open('ab') as stream:
                stream.write(data[2:])
            self.assertEqual(cursor.read()[0], '中文\n中文\n')
            self.assertEqual(cursor.read()[0], '')

    def test_late_file_and_truncation_read_from_start(self):
        with tempfile.TemporaryDirectory() as root, ExitStack() as stack:
            path = Path(root)/'engine.log'
            cursor = stack.enter_context(LogCursor(path, 0))
            self.assertEqual(cursor.read()[0], '')
            path.write_bytes(b'first log\n')
            self.assertEqual(cursor.read()[0], 'first log\n')
            path.write_bytes(b'new\n')
            self.assertEqual(cursor.read(), ('new\n', True))

    def test_history_read_is_bounded(self):
        with tempfile.TemporaryDirectory() as root, ExitStack() as stack:
            path = Path(root)/'large.log'
            path.write_bytes(b'x\n' * HISTORY_LIMIT)
            cursor = stack.enter_context(LogCursor(path, 2))
            self.assertEqual(cursor.read()[0], 'x\nx\n')
            self.assertEqual(cursor.read()[0], '')

    def test_rotation_releases_windows_handles_and_resets_decoder(self):
        with tempfile.TemporaryDirectory() as root, ExitStack() as stack:
            path = Path(root)/'game.log'
            path.write_bytes(b'old\n\xe4\xb8')
            cursor = stack.enter_context(LogCursor(path, 10))
            self.assertEqual(cursor.read(), ('old\n', False))
            path.replace(path.with_suffix('.old'))
            path.write_bytes('新日志\n'.encode('utf-8'))
            self.assertEqual(cursor.read(), ('新日志\n', True))
            self.assertEqual(cursor.read(), ('', False))
            path.unlink()  # A subscribed reader must not prevent deletion.
            self.assertEqual(cursor.read(), ('', False))
            path.write_bytes(b'recreated\n')
            self.assertEqual(cursor.read(), ('recreated\n', True))

    def test_rotation_during_open_uses_the_opened_file_identity(self):
        with tempfile.TemporaryDirectory() as root, ExitStack() as stack:
            path = Path(root)/'game.log'
            path.write_bytes(b'old\n')
            original_open = Path.open
            rotate = True
            def rotating_open(candidate, *args, **kwargs):
                nonlocal rotate
                if candidate == path and rotate:
                    rotate = False
                    path.replace(path.with_suffix('.old'))
                    path.write_bytes(b'new\n')
                return original_open(candidate, *args, **kwargs)
            cursor = stack.enter_context(LogCursor(path, 10))
            with patch.object(Path, 'open', rotating_open):
                self.assertEqual(cursor.read(), ('new\n', False))
                self.assertEqual(cursor.read(), ('', False), 'must not replay the same rotated file')

    def test_late_file_reads_from_start_even_with_history_limit(self):
        with tempfile.TemporaryDirectory() as root, ExitStack() as stack:
            path = Path(root)/'game.log'
            cursor = stack.enter_context(LogCursor(path, 1))
            self.assertEqual(cursor.read(), ('', False))
            path.write_bytes(b'first\nsecond\n')
            self.assertEqual(cursor.read(), ('first\nsecond\n', False))

    def test_observed_disappearance_resets_even_if_file_identity_is_reused(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root, ExitStack() as stack:
            path = Path(root)/'game.log'
            path.write_bytes(b'old\n')
            cursor = stack.enter_context(LogCursor(path, 10))
            original_fstat = os.fstat
            def reused_identity(fd):
                return SimpleNamespace(st_dev=1, st_ino=1, st_size=original_fstat(fd).st_size)
            with patch('mcpywrap_core.mcstudio.log_stream.os.fstat', side_effect=reused_identity):
                self.assertEqual(cursor.read(), ('old\n', False))
                path.unlink()
                self.assertEqual(cursor.read(), ('', False))
                path.write_bytes(b'new longer log\n')
                self.assertEqual(cursor.read(), ('new longer log\n', True))
                self.assertEqual(cursor.read(), ('', False))

    def test_terminal_burst_drains_all_chunks_roles_and_incomplete_utf8(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            payload = (b'x' * (CHUNK-1) + '中文\n'.encode('utf-8')) * 4 + b'\xe4\xb8'
            with patch('mcpywrap_core.mcstudio.log_stream.sessions.read', side_effect=[
                    {'state': 'running', 'role': 'host'}, {'state': 'exited', 'role': 'host'}]), \
                    patch('mcpywrap_core.mcstudio.log_stream.sessions.session_path', return_value=directory), \
                    patch('mcpywrap_core.mcstudio.log_stream.time.monotonic', side_effect=itertools.count(0, 2)), \
                    patch('mcpywrap_core.mcstudio.log_stream.time.sleep', side_effect=lambda _: (directory/'game.log').write_bytes(payload)), \
                    patch('mcpywrap_core.mcstudio.sessions.stop') as stop:
                events = list(follow(root, session='a'*32, source='game', tail=0))
            chunks = [e for e in events if e['event'] == 'log']
            self.assertEqual(''.join(e['text'] for e in chunks), payload.decode('utf-8', 'replace'))
            self.assertTrue(all(e['role'] == 'host' for e in chunks))
            self.assertEqual(events[-1]['event'], 'end')
            stop.assert_not_called()

    def test_group_keeps_following_pending_members_and_new_sessions(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            host, guest = 'a'*32, 'b'*32
            for sid in (host, guest):
                (directory/sid).mkdir()
                (directory/sid/'game.log').write_bytes((sid[0]+'\n').encode('ascii'))
            with patch('mcpywrap_core.runtime.groups.status', side_effect=[
                    {'members': [{'session': host, 'state': 'exited', 'role': 'host'}, {'state': 'pending', 'role': 'guest'}]},
                    {'members': [{'session': host, 'state': 'exited', 'role': 'host'}, {'session': guest, 'state': 'exited', 'role': 'guest'}]}]), \
                    patch('mcpywrap_core.mcstudio.log_stream.sessions.session_path', side_effect=lambda _, sid: directory/sid), \
                    patch('mcpywrap_core.mcstudio.log_stream.time.monotonic', side_effect=itertools.count(0, 2)), \
                    patch('mcpywrap_core.mcstudio.log_stream.time.sleep') as sleep:
                events = list(follow(root, group='c'*32, source='game'))
            self.assertEqual([(e['session'], e['role'], e['text']) for e in events if e['event'] == 'log'],
                             [(host, 'host', 'a\n'), (guest, 'guest', 'b\n')])
            sleep.assert_called_once()
            self.assertEqual(events[-1]['event'], 'end')

    def test_final_drain_preserves_rotation_event(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            path = directory/'game.log'
            path.write_bytes(b'old\n')
            with patch('mcpywrap_core.mcstudio.log_stream.sessions.read', return_value={'state': 'exited'}), \
                    patch('mcpywrap_core.mcstudio.log_stream.sessions.session_path', return_value=directory):
                stream = follow(root, session='a'*32, source='game')
                self.assertEqual(next(stream)['event'], 'state')
                self.assertEqual(next(stream)['text'], 'old\n')
                path.replace(directory/'old.log')
                path.write_bytes(b'new\n')
                self.assertEqual(next(stream)['event'], 'reset')
                self.assertEqual(next(stream)['text'], 'new\n')
                self.assertEqual(next(stream)['event'], 'end')
                stream.close()

    def test_terminal_session_drains_sources_and_ends_without_stopping_game(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            for source in ('game', 'engine', 'worker'):
                (directory/(source+'.log')).write_text(source+'\n', encoding='utf-8')
            with patch('mcpywrap_core.mcstudio.log_stream.sessions.read', return_value={'state':'exited'}), \
                    patch('mcpywrap_core.mcstudio.log_stream.sessions.session_path', return_value=directory), \
                    patch('mcpywrap_core.mcstudio.sessions.stop') as stop:
                events = list(follow(root, session='a'*32))
            self.assertEqual({e['source'] for e in events if e['event']=='log'}, {'game','engine','worker'})
            self.assertEqual(events[-1]['event'], 'end')
            stop.assert_not_called()

    def test_cli_jsonl_and_finite_json_remain_distinct(self):
        events = [{'schema_version':1,'event':'log','session':'a'*32,'source':'game','text':'中文\n'},
                  {'schema_version':1,'event':'end'}]
        with patch('mcpywrap_core.mcstudio.log_stream.follow', return_value=(event for event in events)):
            result = CliRunner().invoke(cli, ['--local','logs','--session','a'*32,'--follow','--source','all','--format','jsonl'])
        self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual([json.loads(line) for line in result.output.splitlines()], events)
        result = CliRunner().invoke(cli,['--local','logs','--session','a'*32,'--follow','--json'])
        self.assertNotEqual(result.exit_code,0)
        result = CliRunner().invoke(cli,['--remote','http://127.0.0.1:1','logs','--session','a'*32,'--follow','--format','jsonl'])
        self.assertNotEqual(result.exit_code,0)
        self.assertIn('--local',result.output)

    def test_jsonl_errors_stay_on_stderr_and_close_the_subscription(self):
        closed = []
        def broken_stream(*args, **kwargs):
            try:
                yield {'schema_version': 1, 'event': 'state', 'session': 'a'*32, 'state': 'running'}
                raise PermissionError('log access denied')
            finally:
                closed.append(True)
        # Click 8.1 (Python 3.9) mixes stderr by default; 8.2+ always isolates it
        # and removed this constructor option. Verify the same pipe contract.
        try:
            runner = CliRunner(mix_stderr=False)
        except TypeError:
            runner = CliRunner()
        with patch('mcpywrap_core.mcstudio.log_stream.follow', broken_stream):
            result = runner.invoke(cli, ['--local', 'logs', '--session', 'a'*32, '--follow', '--format', 'jsonl'])
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(json.loads(result.stdout)['event'], 'state')
        self.assertIn('log access denied', result.stderr)
        self.assertEqual(closed, [True])

    def test_cli_interrupt_closes_stream_without_stopping_game(self):
        closed = []
        def interrupted_stream(*args, **kwargs):
            try:
                yield {'schema_version': 1, 'event': 'state', 'session': 'a'*32, 'state': 'running'}
                raise KeyboardInterrupt
            finally:
                closed.append(True)
        with patch('mcpywrap_core.mcstudio.log_stream.follow', interrupted_stream), patch('mcpywrap_core.mcstudio.sessions.stop') as stop:
            result = CliRunner().invoke(cli, ['--local', 'logs', '--session', 'a'*32, '--follow', '--format', 'jsonl'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(closed, [True])
        stop.assert_not_called()

    def test_snapshot_contract_and_stream_only_options(self):
        with patch('mcpywrap_core.mcstudio.sessions.logs', return_value='legacy snapshot\n') as logs:
            result = CliRunner().invoke(cli, ['--local', 'logs', '--session', 'a'*32, '--json'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.stdout)['text'], 'legacy snapshot\n')
        self.assertEqual(logs.call_args.args[1:], ('a'*32, 100, 'game'))
        for options in (['--source', 'all'], ['--format', 'jsonl'], ['--tail', '0']):
            with self.subTest(options=options):
                result = CliRunner().invoke(cli, ['--local', 'logs', '--session', 'a'*32, *options])
                self.assertEqual(result.exit_code, 2, result.output)

    def test_public_cli_consumer_disconnect_never_stops_session(self):
        with tempfile.TemporaryDirectory() as root:
            sid = 'a'*32
            directory = Path(root)/'.runtime/sessions'/sid
            directory.mkdir(parents=True)
            metadata = json.dumps({'state': 'pending'})
            (directory/'session.json').write_text(metadata, encoding='utf-8')
            (directory/'game.log').write_bytes(b'x' * CHUNK + b'\n')
            with subprocess.Popen([sys.executable, '-m', 'mcpywrap_core', '--local', '--project', root,
                                   '--non-interactive', 'logs', '--session', sid, '--follow', '--format', 'jsonl'],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
                try:
                    process.stdout.close()
                    process.wait(timeout=10)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
            self.assertEqual((directory/'session.json').read_text(encoding='utf-8'), metadata)
            self.assertFalse((directory/'stop').exists())

    def test_public_cli_process_emits_stream_without_wrapping_it_as_one_json(self):
        with tempfile.TemporaryDirectory() as root:
            sid = 'a'*32
            directory = Path(root)/'.runtime/sessions'/sid
            directory.mkdir(parents=True)
            (directory/'session.json').write_text(json.dumps({'state':'exited'}), encoding='utf-8')
            (directory/'engine.log').write_text('engine output\n', encoding='utf-8')
            (directory/'game.log').write_bytes('中文\n中文\n'.encode('utf-8'))
            process = subprocess.run([sys.executable,'-m','mcpywrap_core','--local','--project',root,
                                      '--non-interactive','logs','--session',sid,'--follow',
                                      '--source','all','--format','jsonl'], capture_output=True, timeout=10,
                                     env=dict(os.environ, PYTHONIOENCODING='gbk'))
            self.assertEqual(process.returncode,0,process.stderr.decode('utf-8','replace'))
            events = [json.loads(line) for line in process.stdout.decode('ascii').splitlines()]
            self.assertEqual(events[-1]['event'],'end')
            self.assertEqual(next(e['text'] for e in events if e.get('source')=='game'),'中文\n中文\n')

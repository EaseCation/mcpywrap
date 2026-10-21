import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from mcpywrap.cli import cli
from mcpywrap.mcstudio.log_stream import LogCursor, follow, HISTORY_LIMIT


class LogStreamTests(unittest.TestCase):
    def test_incremental_utf8_and_repeated_lines_are_not_lost_or_duplicated(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'game.log'
            path.write_bytes(b'old\n')
            cursor = LogCursor(path, 1)
            self.addCleanup(cursor.close)
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
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'engine.log'
            cursor = LogCursor(path, 0)
            self.addCleanup(cursor.close)
            self.assertEqual(cursor.read()[0], '')
            path.write_text('first log\n', encoding='utf-8')
            self.assertEqual(cursor.read()[0], 'first log\n')
            path.write_text('new\n', encoding='utf-8')
            self.assertEqual(cursor.read(), ('new\n', True))

    def test_history_read_is_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'large.log'
            path.write_bytes(b'x\n' * HISTORY_LIMIT)
            cursor = LogCursor(path, 2)
            self.addCleanup(cursor.close)
            self.assertEqual(cursor.read()[0], 'x\nx\n')
            self.assertEqual(cursor.read()[0], '')

    def test_terminal_session_drains_sources_and_ends_without_stopping_game(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            for source in ('game', 'engine', 'worker'):
                (directory/(source+'.log')).write_text(source+'\n', encoding='utf-8')
            with patch('mcpywrap.mcstudio.log_stream.sessions.read', return_value={'state':'exited'}), \
                    patch('mcpywrap.mcstudio.log_stream.sessions.session_path', return_value=directory), \
                    patch('mcpywrap.mcstudio.sessions.stop') as stop:
                events = list(follow(root, session='a'*32))
            self.assertEqual({e['source'] for e in events if e['event']=='log'}, {'game','engine','worker'})
            self.assertEqual(events[-1]['event'], 'end')
            stop.assert_not_called()

    def test_cli_jsonl_and_finite_json_remain_distinct(self):
        events = [{'schema_version':1,'event':'log','session':'a'*32,'source':'game','text':'中文\n'},
                  {'schema_version':1,'event':'end'}]
        with patch('mcpywrap.mcstudio.log_stream.follow', return_value=iter(events)):
            result = CliRunner().invoke(cli, ['--local','logs','--session','a'*32,'--follow','--source','all','--format','jsonl'])
        self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual([json.loads(line) for line in result.output.splitlines()], events)
        result = CliRunner().invoke(cli,['--local','logs','--session','a'*32,'--follow','--json'])
        self.assertNotEqual(result.exit_code,0)
        result = CliRunner().invoke(cli,['--remote','http://127.0.0.1:1','logs','--session','a'*32,'--follow','--format','jsonl'])
        self.assertNotEqual(result.exit_code,0)
        self.assertIn('--local',result.output)

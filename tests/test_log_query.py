import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from click.testing import CliRunner
from mcpywrap_core.cli import cli
from mcpywrap_core.mcstudio.log_query import snapshot, StreamFilter, HISTORY_BYTES
from mcpywrap_core.command_context import restart_handoff


class LogQueryTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name);self.log=self.root/'game.log'

    def write_log(self,text):
        self.log.write_bytes(text.encode('utf-8'))

    def test_sparse_matches_are_filtered_before_tail_and_counted_before_limit(self):
        self.write_log('[Demo] missing label\n'+('noise\n'*756)+'[Demo] missing label\n[Demo] ready\n')
        value=snapshot(self.log,contains='[Demo]',tail=1,summary=True)
        self.assertEqual(value['text'],'[Demo] ready\n')
        self.assertEqual(value['matched_lines'],3)
        self.assertEqual(value['summary'],[{'text':'[Demo] missing label','count':2}])
        self.assertFalse(value['scan_truncated'])

    def test_snapshot_preserves_windows_line_endings(self):
        self.log.write_bytes(b'needle\r\nnoise\r\nneedle\r\n')
        value=snapshot(self.log,contains='needle',summary=True)
        self.assertEqual(value['text'],'needle\r\nneedle\r\n')
        self.assertEqual(value['summary'][0]['count'],2)

    def test_filter_is_literal_and_case_sensitive(self):
        self.write_log('x.*y\nxy\nX.*Y\n')
        self.assertEqual(snapshot(self.log,contains='.*')['text'],'x.*y\nX.*Y\n')
        self.assertEqual(snapshot(self.log,contains='x.*')['matched_lines'],1)

    def test_bounded_search_reports_truncation_and_missing_distinctly(self):
        self.assertFalse(snapshot(self.log)['available'])
        self.write_log('old needle\n'+'x\n'*(HISTORY_BYTES//2)+'new\n')
        result=snapshot(self.log,contains='needle')
        self.assertTrue(result['available']);self.assertTrue(result['scan_truncated'])
        self.assertEqual(result['matched_lines'],0)

    def test_follow_keeps_partial_writes_and_final_line(self):
        stream=StreamFilter('[Demo]')
        self.assertEqual(stream.feed('[De'),'')
        self.assertEqual(stream.feed('mo] hello\nnoise\n[Demo] final'),'[Demo] hello\n')
        self.assertEqual(stream.feed('',final=True),'[Demo] final')

    def test_follow_history_filters_before_tail(self):
        from mcpywrap_core.mcstudio.log_stream import LogCursor
        self.write_log('[Demo] evidence\n'+'noise\n'*756)
        with LogCursor(self.log,1,contains='[Demo]') as cursor:
            self.assertEqual(cursor.read()[0],'[Demo] evidence\n')

    def test_local_cli_uses_same_query_without_engine(self):
        sid='a'*32
        directory=self.root/'.runtime/sessions'/sid;directory.mkdir(parents=True)
        (directory/'session.json').write_text('{}')
        (directory/'game.log').write_text('needle\nnoise\nneedle\n')
        with patch('mcpywrap_core.mobile_host.profiles.select',return_value=None),patch('mcpywrap_core.remote.client.routed_command',return_value=(False,None)):
            value=CliRunner().invoke(cli,['--project',str(self.root),'logs','--session',sid,'--filter','needle','--summary','--json'])
        self.assertEqual(value.exit_code,0,value.output)
        self.assertEqual(json.loads(value.stdout)['summary'][0]['count'],2)

    def test_restart_handoff_never_changes_target_or_discards_diagnostics(self):
        value=restart_handoff({'session':'new','hint':'prepared','ok':False},'old')
        self.assertEqual(value['previous_session'],'old');self.assertTrue(value['session_changed'])
        self.assertIn('--session new',value['hint']);self.assertFalse(value['ok'])
        self.assertNotIn('session_changed',restart_handoff({'session':'old'},'old'))

    def test_windows_v1_filters_existing_endpoint_and_reports_scope(self):
        from mcpywrap_core.remote.client import routed_command
        with patch('mcpywrap_core.command_context.remote_url',return_value='http://127.0.0.1:17651'),patch('mcpywrap_core.command_context.json_output',return_value=True),patch('mcpywrap_core.remote.client.Client.require'),patch('mcpywrap_core.remote.client.Client.request',return_value={'text':'needle\nnoise\nneedle\n'}) as request:
            routed,result=routed_command('logs',{'session':'a'*32,'source':'game','tail':1,'contains':'needle','summary':True})
        self.assertTrue(routed);self.assertIn('tail=10000',request.call_args.args[1])
        self.assertEqual(result['summary'][0]['count'],2)
        self.assertEqual(result['scan_scope'],'remote_last_10000_lines')

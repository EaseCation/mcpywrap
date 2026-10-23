"""配对中断恢复，不重复授权或泄露私有握手凭据。"""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from mcpywrap_core.mobile_host import profiles
from mcpywrap_core.mobile_host.client import Client, pair
from mcpywrap_core.remote.protocol import RemoteError


class PairingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.workspace = self.root/'public'; self.workspace.mkdir()
        env = patch.dict(os.environ, MCPY_HOST_CONFIG=str(self.root/'private/hosts.json'))
        env.start(); self.addCleanup(env.stop)
        self.pending = {'id':'request', 'secret':'private-handshake', 'probe':'.bridge/probes/test.txt', 'challenge':'write-proof'}
        self.approved = {'state':'approved', 'token':'private-token', 'client_id':'client', 'installation_id':'installation'}
        self.url = 'http://127.0.0.1:17653'
        self.output = io.StringIO()

    def invoke(self):
        with contextlib.redirect_stderr(self.output):
            return pair(self.url, 'test-code', self.workspace, timeout=1)

    def test_directory_repair_resumes_same_request_and_receipt_is_private(self):
        def first(client, method, path, data=None, **kwargs):
            if path=='/capabilities': return {'pairing':{'resume':True}}
            if path=='/pairings': return self.pending
            if path.endswith('/result'): return {'state':'verifying'}
            self.fail(path)
        with patch.object(Client,'request',first):
            with self.assertRaises(RemoteError) as error: self.invoke()
        self.assertEqual(error.exception.code, 'workspace_unavailable')
        receipts=list((self.root/'private').glob('pairing-*.json')); self.assertEqual(len(receipts),1)
        if os.name != 'nt': self.assertEqual(receipts[0].stat().st_mode&0o777,0o600)
        probe=self.workspace/self.pending['probe'];probe.parent.mkdir(parents=True);probe.write_text('shared-proof')
        verified=False
        def repaired(client, method, path, data=None, **kwargs):
            nonlocal verified
            if path=='/capabilities':return {'pairing':{'resume':True}}
            if path.endswith('/result'):return self.approved if verified else {'state':'verifying'}
            if path.endswith('/verify'):
                self.assertEqual(probe.with_suffix('.response').read_text(),'write-proof');verified=True;probe.unlink()
                return {'state':'pending'}
            self.fail('Must not begin another pairing: '+path)
        with patch.object(Client,'request',repaired): result=self.invoke()
        self.assertTrue(result['paired']);self.assertNotIn('token',result)
        self.assertFalse(receipts[0].exists())
        self.assertNotIn('private-handshake',self.output.getvalue());self.assertNotIn('private-token',self.output.getvalue())
        self.assertEqual(profiles.read()[0]['token'],'private-token')

    def test_lost_begin_reply_reuses_request_identity(self):
        starts=[]
        def server(client,method,path,data=None,**kwargs):
            if path=='/capabilities':return {'pairing':{'resume':True}}
            if path=='/pairings':
                starts.append(dict(data))
                if len(starts)==1:raise RemoteError('offline','host_unavailable')
                return self.pending
            if path.endswith('/result'):return self.approved
            self.fail(path)
        with patch.object(Client,'request',server),patch('mcpywrap_core.mobile_host.client.time.sleep'):
            self.assertTrue(self.invoke()['paired'])
        self.assertEqual(len(starts),2);self.assertEqual(starts[0],starts[1]);self.assertEqual(len(starts[0]['request_id']),32)

    def test_older_host_does_not_replay_lost_begin_reply(self):
        starts=[]
        def server(client,method,path,data=None,**kwargs):
            if path=='/capabilities':return {}
            starts.append(data);raise RemoteError('offline','host_unavailable')
        with patch.object(Client,'request',server):
            with self.assertRaises(RemoteError):self.invoke()
        self.assertEqual(len(starts),1);self.assertNotIn('request_id',starts[0])

    def test_approved_resume_does_not_require_deleted_probe(self):
        def server(client,method,path,data=None,**kwargs):
            if path=='/capabilities':return {'pairing':{'resume':True}}
            if path=='/pairings':return self.pending
            if path.endswith('/result'):return self.approved
            self.fail(path)
        with patch.object(Client,'request',server): self.assertTrue(self.invoke()['paired'])

    def test_concurrent_bindings_cannot_overwrite_another_workspace(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from mcpywrap_core.utils.locks import LockBusy
        first={'workspace':str(self.workspace),'endpoint':self.url,'token':'first-token','installation_id':'first','client_id':'first'}
        second=dict(first,workspace=str(self.root/'other'),installation_id='second',client_id='second')
        entered,release=Event(),Event();write=profiles.write
        def paused(records):
            entered.set()
            if not release.wait(5):raise AssertionError('test coordination timed out')
            write(records)
        with ThreadPoolExecutor(max_workers=1) as pool,patch.object(profiles,'write',side_effect=paused):
            pending=pool.submit(profiles.bind,first)
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaises(LockBusy):profiles.bind(second)
            finally:release.set()
            pending.result(timeout=5)
        profiles.bind(second)
        self.assertEqual({r['installation_id'] for r in profiles.read()},{'first','second'})
        profiles.unbind(first['workspace'])
        self.assertEqual([r['installation_id'] for r in profiles.read()],['second'])

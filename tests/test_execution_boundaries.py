"""Mobile hints must be selected by workspace binding, never leak into desktop commands."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from click.testing import CliRunner
from mcpywrap_core.cli import cli
from mcpywrap_core.mobile_host import profiles
from mcpywrap_core.mobile_host.client import Client
from mcpywrap_core.remote.protocol import RemoteError

ROOT=Path(__file__).resolve().parents[1]
PHONE_TERMS=('画中画','无限制','切回 mcpy','mcpy://service/start','needs_user_action','ask_user','Minis','PRoot')


class ExecutionBoundaryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.mobile=self.root/'mobile';self.desktop=self.root/'desktop'
        self.mobile.mkdir();self.desktop.mkdir()
        env=patch.dict(os.environ,MCPY_HOST_CONFIG=str(self.root/'private/hosts.json'))
        env.start();self.addCleanup(env.stop)
        profiles.bind({'workspace':str(self.mobile),'endpoint':'http://127.0.0.1:17653','token':'test-token',
                       'installation_id':'phone','client_id':'client'})

    def invoke(self,project,*args):
        return CliRunner().invoke(cli,['--project',str(project),*args])

    def assert_desktop(self,text):
        for term in PHONE_TERMS:self.assertNotIn(term,text)

    def test_help_exposes_only_target_options_on_every_client_platform(self):
        with patch.object(Client,'request',side_effect=AssertionError('help must not contact a host')):
            for platform in ('win32','darwin','linux'):
                with self.subTest(platform=platform),patch.object(sys,'platform',platform):
                    for command in ('run','restart','logs'):
                        plain=self.invoke(self.desktop,command,'--help')
                        self.assertEqual(plain.exit_code,0,plain.output);self.assert_desktop(plain.output)
                        self.assertNotIn('--launch-timeout',plain.output);self.assertNotIn('--since-ms',plain.output)
                        if command=='logs':self.assertIn('[game|engine|worker|all]',plain.output)
                        bound=self.invoke(self.mobile,command,'--help')
                        self.assertEqual(bound.exit_code,0,bound.output)
                        self.assertIn('--since-ms' if command=='logs' else '--launch-timeout',bound.output)

    def test_desktop_logs_still_use_local_reader_with_an_unrelated_phone_binding(self):
        with patch.object(Client,'request',side_effect=AssertionError('unrelated phone contacted')),patch('mcpywrap_core.mcstudio.sessions.logs',return_value='desktop output\n') as logs:
            result=self.invoke(self.desktop,'logs','--session','a'*32,'--json')
        self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual(json.loads(result.stdout)['text'],'desktop output\n')
        self.assert_desktop(result.output);logs.assert_called_once()

    def test_desktop_failure_does_not_acquire_mobile_permission_hints(self):
        with patch.object(Client,'request',side_effect=AssertionError('unrelated phone contacted')),patch('mcpywrap_core.mcstudio.sessions.stop',side_effect=OSError('desktop process unavailable')):
            result=self.invoke(self.desktop,'stop','--session','a'*32,'--json')
        self.assertNotEqual(result.exit_code,0);self.assert_desktop(result.output)
        self.assertNotIn('needs_user_action',json.loads(result.stdout))

    def test_windows_remote_failure_remains_a_windows_remote_failure(self):
        for code in ('remote_unavailable','host_unavailable'):
            with self.subTest(code=code),patch.object(Client,'request',side_effect=AssertionError('phone contacted')),patch('mcpywrap_core.remote.client.Client.request',side_effect=RemoteError('Windows host unavailable',code)):
                result=self.invoke(self.desktop,'--remote','http://127.0.0.1:17651','status','--session','a'*32,'--json')
            self.assertNotEqual(result.exit_code,0);self.assert_desktop(result.output)
            self.assertEqual(json.loads(result.stdout)['code'],code)

    def test_binding_probe_never_falls_back_to_another_workspace_or_network(self):
        with patch.object(Client,'capabilities',side_effect=AssertionError('binding probe contacted host')):
            unbound=json.loads(self.invoke(self.desktop,'host','status','--binding-only','--json').stdout)
            bound=json.loads(self.invoke(self.mobile,'host','status','--binding-only','--json').stdout)
        self.assertFalse(unbound['bound_for_project']);self.assertNotIn('endpoint',unbound)
        self.assertTrue(bound['bound_for_project']);self.assertNotIn('token',bound)

    def test_bootstrap_unbound_workspace_never_asks_phone_for_live_status(self):
        spec=importlib.util.spec_from_file_location('bootstrap_boundary',ROOT/'skills/mcpywrap/scripts/bootstrap.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        def invoke(args):
            if args==['mcpy','--help']:
                return Mock(returncode=0,stdout='--project --non-interactive --json status logs stop package\n  host  connection')
            if 'host' in args:
                self.assertIn('--binding-only',args)
                return Mock(returncode=0,stdout=json.dumps({'ok':True,'bound_for_project':False}))
            return Mock(returncode=0,stdout='--no-gui --detach')
        with patch.object(module,'invoke',side_effect=invoke):value=module.capabilities('mcpy')
        self.assertNotEqual(value.get('execution'),'host');self.assertNotIn('application_host',value)

    def test_standard_skill_keeps_phone_procedures_in_opt_in_reference(self):
        main=(ROOT/'skills/mcpywrap/SKILL.md').read_text()
        for term in ('needs_user_action','无限制','mcpy://service/start','/var/minis'):
            self.assertNotIn(term,main)
        self.assertIn('application-host.md',main)
        phone=(ROOT/'skills/mcpywrap/references/application-host.md').read_text()
        self.assertIn('needs_user_action',phone);self.assertIn('无限制',phone)

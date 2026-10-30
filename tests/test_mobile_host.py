"""A paired CLI must never silently invoke the local engineering implementation."""
import json
import inspect
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from click.testing import CliRunner
from mcpywrap_core.cli import cli
from mcpywrap_core.mobile_host import profiles
from mcpywrap_core.mobile_host.client import Client
from mcpywrap_core.remote.protocol import RemoteError
from mcpywrap_core.host import HostServices, host_scope

def cli_runner():
    options = {'mix_stderr': False} if 'mix_stderr' in inspect.signature(CliRunner).parameters else {}
    return CliRunner(**options)


class MobileHostTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.project=self.root/'projects/demo';self.project.mkdir(parents=True)
        self.env=patch.dict(os.environ,MCPY_HOST_CONFIG=str(self.root/'private/hosts.json'));self.env.start();self.addCleanup(self.env.stop)
        self.record={'workspace':str(self.root),'endpoint':'http://127.0.0.1:17653','token':'not-a-real-token','installation_id':'test','client_id':'client'}
        profiles.bind(self.record)
    def test_build_routes_before_local_core_even_without_project_toml(self):
        with patch.object(Client,'operation',return_value={'output':'host-output'}) as remote, patch('mcpywrap_core.api.Core.execute',side_effect=AssertionError('local build forbidden')):
            result=cli_runner().invoke(cli,['--project',str(self.project),'build','--json'])
        self.assertEqual(result.exit_code,0,result.output);self.assertEqual(remote.call_args.args[0],'build')
        self.assertEqual(json.loads(result.output)['output'],'host-output')
    def test_dependency_preview_has_the_same_cli_shape_when_bound(self):
        selection={'purpose':'release','includes_unbundled':False,'dependencies':[],
                   'excluded':[{'dependency':'helper','unbundled':True,'reason':'unbundled'}]}
        for structured in (False,True):
            with self.subTest(json=structured), patch.object(Client,'operation',return_value={'dependency_selection':selection}) as remote, patch('mcpywrap_core.dependencies.DependencyService.resolve',side_effect=AssertionError('local resolution forbidden')):
                result=cli_runner().invoke(cli,['--project',str(self.project),'deps','--bundled-only',*(['--json'] if structured else [])])
            self.assertEqual(result.exit_code,0,result.output)
            self.assertEqual(remote.call_args.args[0],'resolve')
            self.assertTrue(remote.call_args.args[2]['bundled_only'])
            if structured:
                self.assertEqual(json.loads(result.stdout)['purpose'],'release')
                self.assertEqual(json.loads(result.stdout)['excluded'],selection['excluded'])
            else:
                self.assertIn('helper [已排除',result.output)
                self.assertNotIn('dependency_selection:',result.output)
    def test_dependency_preview_requires_the_host_capability_without_fallback(self):
        with patch.object(Client,'operation',return_value={'dependencies':[]}), patch('mcpywrap_core.dependencies.DependencyService.resolve') as local:
            result=cli_runner().invoke(cli,['--project',str(self.project),'deps','--json'])
        self.assertNotEqual(result.exit_code,0,result.output)
        self.assertEqual(json.loads(result.output)['code'],'host_capability_missing')
        local.assert_not_called()
    def test_explicit_local_cannot_bypass_binding(self):
        with patch.object(Client,'operation') as remote:
            result=cli_runner().invoke(cli,['--local','--project',str(self.project),'build','--json'])
        self.assertNotEqual(result.exit_code,0);remote.assert_not_called()
    def test_failure_never_falls_back(self):
        with patch.object(Client,'operation',side_effect=RemoteError('offline','host_unavailable')),patch('mcpywrap_core.api.Core.execute') as local:
            result=cli_runner().invoke(cli,['--project',str(self.project),'build','--json'])
        self.assertNotEqual(result.exit_code,0);local.assert_not_called()
    def test_unpaired_workspace_keeps_desktop_execution(self):
        profiles.write([])
        with patch('mcpywrap_core.api.Core.execute',return_value={'output':'local'}) as local:
            (self.project/'pyproject.toml').write_text('[project]\nname="example"\nversion="1"\n')
            result=cli_runner().invoke(cli,['--project',str(self.project),'build','--json'])
        self.assertEqual(result.exit_code,0,result.output);local.assert_called_once()
    def test_nested_runtime_command_routes_with_code_file_contents(self):
        path=self.project/'probe.py';path.write_text('_result = 42')
        with patch.object(Client,'operation',return_value={'value':42}) as remote:
            result=cli_runner().invoke(cli,['--project',str(self.project),'runtime','py','--session','s','--side','server','--file',str(path),'--json'])
        self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual(remote.call_args.args[0],'runtime.py');self.assertEqual(remote.call_args.args[2]['code'],'_result = 42')
    def test_credentials_private_and_not_returned_by_status(self):
        if os.name != 'nt': self.assertEqual(profiles.location().stat().st_mode&0o777,0o600)
        with patch.object(Client,'capabilities',return_value={'core_version':'0.6.2'}):
            result=cli_runner().invoke(cli,['--project',str(self.project),'host','status','--json'])
        self.assertEqual(result.exit_code,0,result.output);self.assertNotIn('not-a-real-token',result.output)
    def test_paths_are_mount_relative(self):
        self.assertEqual(profiles.project_path(self.record,self.project),'projects/demo')
        with self.assertRaises(ValueError):profiles.project_path(self.record,self.root.parent/'outside')
    def test_only_loopback_endpoints(self):
        for url in ('http://192.168.1.1:17653','https://example.org','http://127.0.0.1:17653/unsafe','http://user:pass@127.0.0.1:17653'):
            with self.assertRaises(ValueError):profiles.endpoint(url)
    def test_host_distribution_provider_replaces_process_metadata(self):
        from mcpywrap_core.host import distribution
        with host_scope(HostServices(distribution_provider=lambda name:('remote',name))):
            self.assertEqual(distribution('shared-addon'),('remote','shared-addon'))

class RecoveryTests(unittest.TestCase):
    setUp = MobileHostTests.setUp
    def test_lost_submission_preserves_queryable_id_without_retry(self):
        from mcpywrap_core.mobile_host.receipts import Receipts
        client=Client(self.record)
        with patch.object(client,'capabilities',return_value={'operations':['build'],'core_version':'0.6.2'}), patch.object(client,'request',side_effect=RemoteError('connection lost','host_unavailable')) as request:
            with self.assertRaises(RemoteError) as failure: client.operation('build',self.project,{})
        request.assert_called_once()
        saved=Receipts(self.record).recent()
        self.assertEqual(len(saved),1)
        self.assertIn(saved[0]['operation_id'],failure.exception.hint)
        self.assertNotIn(self.record['token'],Receipts(self.record).path.read_bytes().decode('latin1'))
        if os.name != 'nt': self.assertEqual(Receipts(self.record).path.stat().st_mode&0o777,0o600)

    def test_completed_stage_result_survives_new_client(self):
        from mcpywrap_core.mobile_host.receipts import Receipts
        from unittest.mock import Mock
        step={'id':'stage','kind':'script','core_version':'0.6.2','options':{}}
        execute=Mock(return_value={'ok':True,'result':{'exit_code':0}})
        first=Receipts(self.record).execute('operation',step,execute)
        second=Receipts(self.record).execute('operation',step,execute)
        self.assertEqual(first,second);execute.assert_called_once()
        with self.assertRaisesRegex(RemoteError,'内容发生变化'):
            Receipts(self.record).execute('operation',dict(step,kind='pip'),execute)

    def test_crash_during_stage_never_replays_side_effect(self):
        from mcpywrap_core.mobile_host.receipts import Receipts
        from unittest.mock import Mock
        step={'id':'stage','kind':'script','options':{}}
        execute=Mock(side_effect=KeyboardInterrupt)
        with self.assertRaises(KeyboardInterrupt):Receipts(self.record).execute('operation',step,execute)
        with self.assertRaises(RemoteError) as failure:Receipts(self.record).execute('operation',step,execute)
        self.assertEqual(failure.exception.code,'preparation_unknown');execute.assert_called_once()

    def test_reconnect_resends_result_without_executing_stage(self):
        from mcpywrap_core import __version__
        from mcpywrap_core.mobile_host.preparation import LocalPreparation
        from mcpywrap_core.mobile_host.receipts import Receipts
        from unittest.mock import Mock
        operation='a'*64
        step={'id':'step','kind':'script','core_version':__version__,'options':{}}
        client=Client(self.record)
        execute=Mock(return_value={'ok':True,'result':42})
        with patch.object(LocalPreparation,'execute',execute), patch.object(client,'request',side_effect=[{'state':'waiting_preparation','preparation':step},RemoteError('lost','host_unavailable')]):
            with self.assertRaises(RemoteError):client.wait(operation,{'core_version':__version__})
        with patch.object(LocalPreparation,'execute',execute), patch.object(client,'request',side_effect=[{'state':'waiting_preparation','preparation':step},{'ok':True},{'state':'completed','result':{'answer':42}}]), patch('time.sleep'):
            result=client.wait(operation,{'core_version':__version__})
        self.assertEqual(result['answer'],42);execute.assert_called_once()


class SkillInstallTests(unittest.TestCase):
    def test_complete_skill_tree_installs_without_app_specific_fork(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'agent/skills/mcpywrap'
            result=cli_runner().invoke(cli,['skill','install','--directory',str(target),'--json'])
            self.assertEqual(result.exit_code,0,result.output)
            for path in ('SKILL.md','scripts/bootstrap.py','references/application-host.md','assets/consumer-prepare/framework/build_tools/schema.json'):
                self.assertTrue((target/path).is_file(),path)
            original=(target/'SKILL.md').read_bytes()
            rejected=cli_runner().invoke(cli,['skill','install','--directory',str(target),'--json'])
            self.assertNotEqual(rejected.exit_code,0)
            self.assertEqual((target/'SKILL.md').read_bytes(),original)

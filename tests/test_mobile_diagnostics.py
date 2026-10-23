"""失败现场的状态、恢复与开发端工具边界。"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from click.testing import CliRunner
from mcpywrap_core.cli import cli
from mcpywrap_core.mobile_host.client import Client
from mcpywrap_core.mobile_host import profiles
from mcpywrap_core.mobile_host.receipts import Receipts
from mcpywrap_core.remote.protocol import RemoteError
from mcpywrap_core.minecraft import modsdk_versions
from mcpywrap_core import __version__

class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();self.project=self.root/'projects/WelcomeTitle';self.project.mkdir(parents=True)
        env=patch.dict(os.environ,MCPY_HOST_CONFIG=str(self.root/'private/hosts.json'),XDG_CACHE_HOME=str(self.root/'cache'))
        env.start();self.addCleanup(env.stop)
        self.profile={'workspace':str(self.root),'endpoint':'http://127.0.0.1:17653','token':'test-private-token','installation_id':'test','client_id':'client'}
        profiles.bind(self.profile)

    def test_resume_observes_same_session_without_post_or_local_build(self):
        client=Client(self.profile)
        observed={'state':'running','session':'original-session','pid':42,'process_alive':True,'pipRequested':True,'pip':True}
        with patch.object(client,'request',return_value={'state':'unknown','observation':observed,'result':{'session':'original-session'}}) as request:
            value=client.wait('a'*64,{'core_version':__version__},reconcile=True)
        self.assertTrue(value['reconciled']);self.assertEqual(value['session'],'original-session')
        self.assertEqual(request.call_args.args,('GET','/operations/'+'a'*64))

    def test_resume_does_not_turn_dead_or_unconfirmed_process_into_success(self):
        client=Client(self.profile)
        observation={'state':'unknown','pid':0,'process_alive':None,'hint':'check evidence'}
        with patch.object(client,'request',return_value={'state':'unknown','code':'game_start_unknown','observation':observation,'result':{'session':'original'}}):
            with self.assertRaises(RemoteError) as failure:client.wait('a'*64,{'core_version':__version__},reconcile=True)
        self.assertEqual(failure.exception.details['observation'],observation)
        self.assertIn('check evidence',failure.exception.hint)

    def test_waiting_user_returns_action_prompt_without_polling_or_replaying(self):
        client=Client(self.profile)
        job={'state':'waiting_user','code':'vendor_background_launch_denied','hint':'切回 mcpy；后台弹出界面被拒绝',
             'observation':{'hint':'generic observation'},
             'result':{'session':'same-session','game_started':False,'prepared':True,'recovery_uri':'mcpy://service/start'}}
        with patch.object(client,'request',return_value=job) as request:
            with self.assertRaises(RemoteError) as failure:client.wait('b'*64,{'core_version':__version__})
        request.assert_called_once_with('GET','/operations/'+'b'*64)
        self.assertEqual(failure.exception.details['operation_state'],'waiting_user')
        self.assertFalse(failure.exception.details['game_started'])
        self.assertIn('不要重新 run --new',failure.exception.hint)
        self.assertIn('后台弹出界面被拒绝',failure.exception.hint)

    def test_waiting_result_has_top_level_human_guidance_in_cli_json(self):
        job={'state':'waiting_user','code':'background_launch_unconfirmed',
             'result':{'session':'same-session','prepared':True,'game_started':False}}
        with patch.object(Client,'capabilities',return_value={'operations':['run'],'core_version':__version__}),patch.object(Client,'request') as request:
            def respond(method,path,data=None):
                if method=='POST':
                    import hashlib
                    return {'operation_id':hashlib.sha256((self.profile['client_id']+':'+data['request_id']).encode()).hexdigest()}
                return job
            request.side_effect=respond
            result=CliRunner().invoke(cli,['--project',str(self.project),'run','--no-gui','--detach','--json'])
        value=json.loads(result.stdout)
        self.assertNotEqual(result.exit_code,0,result.output)
        self.assertTrue(value['needs_user_action']);self.assertFalse(value['retryable'])
        self.assertEqual(value['next_action'],'ask_user');self.assertEqual(value['session'],'same-session')
        self.assertIn('手动切回',value['user_message']);self.assertIn('停止自动',value['hint'])
        self.assertIn('host resume --operation',value['resume_command'])
        self.assertEqual(request.call_count,2)

    def test_plain_terminal_resume_shows_human_step_without_json(self):
        job={'state':'waiting_user','code':'background_launch_unconfirmed','result':{'session':'same'}}
        with patch.object(Client,'capabilities',return_value={'core_version':__version__}),patch.object(Client,'request',return_value=job) as request:
            result=CliRunner().invoke(cli,['--project',str(self.project),'host','resume','--operation','a'*64])
        self.assertNotEqual(result.exit_code,0)
        self.assertIn('停止自动重试',result.output);self.assertIn('手动切回',result.output)
        self.assertIn('等用户确认',result.output);request.assert_called_once()

    def test_unreachable_host_stops_before_submission_and_preserves_uncertainty(self):
        from urllib.error import URLError
        client=Client(self.profile)
        with patch.object(client.opener,'open',side_effect=URLError('timeout')) as opened:
            with self.assertRaises(RemoteError) as raised:client.operation('run',self.project,{})
        value=raised.exception.details
        self.assertEqual(raised.exception.code,'host_unavailable');self.assertEqual(value['next_action'],'ask_user')
        self.assertFalse(value['retryable']);self.assertNotIn('prepared',value);self.assertNotIn('game_started',value)
        self.assertIn('无限制',value['user_message']);opened.assert_called_once()

    def test_poll_disconnect_keeps_original_operation_and_handoff(self):
        client=Client(self.profile)
        error=RemoteError('disconnected','host_unavailable')
        with patch.object(client,'request',side_effect=error) as request:
            with self.assertRaises(RemoteError) as raised:client.wait('c'*64,{'core_version':__version__})
        self.assertEqual(raised.exception.details['operation_id'],'c'*64)
        self.assertIn('c'*64,raised.exception.details['resume_command'])
        self.assertEqual(raised.exception.details['retry_policy'],'after_user_confirmation')
        request.assert_called_once()

    def test_native_crash_keeps_debug_diagnostics_without_permission_advice(self):
        from mcpywrap_core.mobile_host.intervention import require_user
        error=RemoteError('native crash','engine_crashed')
        self.assertFalse(require_user(error));self.assertNotIn('needs_user_action',getattr(error,'details',{}) or {})

    def test_new_log_options_require_advertised_capability_before_post(self):
        client=Client(self.profile)
        with patch.object(client,'capabilities',return_value={'operations':['logs']}),patch.object(client,'request') as request:
            with self.assertRaises(RemoteError) as error:client.operation('logs',self.project,{'contains':'needle'})
        self.assertEqual(error.exception.code,'capability_missing');request.assert_not_called()

    def test_cached_age_is_computed_without_changing_observation(self):
        profile=dict(self.profile,last_service={'observed_at':100.0,'core_version':__version__})
        with patch('time.time',return_value=103.5):
            value=profiles.cached_service(profile)
        self.assertEqual(value['age_ms'],3500);self.assertEqual(value['observed_at'],100.0)
        self.assertNotIn('age_ms',profile['last_service'])

    def test_mobile_restart_cli_exposes_both_session_ids(self):
        with patch.object(Client,'operation',return_value={'session':'new-session','state':'loading'}):
            result=CliRunner().invoke(cli,['--project',str(self.project),'restart','--session','old-session','--json'])
        self.assertEqual(result.exit_code,0,result.output)
        value=json.loads(result.stdout)
        self.assertEqual(value['previous_session'],'old-session');self.assertTrue(value['session_changed'])
        self.assertIn('--session new-session',value['hint'])

    def test_recent_operations_show_cached_outcome_and_observation_time(self):
        receipts=Receipts(self.profile)
        receipts.submitted('operation',{'request_id':'request','operation':'run','project':'projects/WelcomeTitle'})
        self.assertEqual(receipts.recent()[0]['state'],'submitted_unobserved')
        receipts.observed('operation',{'state':'failed','error':'blocked','code':'pip_permission_missing'})
        value=Receipts(self.profile).recent()[0]
        self.assertFalse(value['ok']);self.assertTrue(value['cached']);self.assertGreater(value['observed_at'],0)
        self.assertEqual(value['code'],'pip_permission_missing')

    def test_modsdk_offline_bypasses_host_but_build_does_not(self):
        with patch.object(Client,'operation',side_effect=AssertionError('host forbidden')),patch.object(modsdk_versions.subprocess,'run',side_effect=AssertionError('network forbidden')):
            result=CliRunner().invoke(cli,['--project',str(self.project),'modsdk','--list','--offline','--json'])
        self.assertEqual(json.loads(result.stdout)['code'],'sdk_catalog_unavailable')

    def test_all_log_sources_reach_host(self):
        with patch.object(Client,'operation',return_value={'text':'[game] c\n[engine] e'}) as operation:
            result=CliRunner().invoke(cli,['--project',str(self.project),'logs','--session','s','--source','all','--json'])
        self.assertEqual(result.exit_code,0,result.output);self.assertEqual(operation.call_args.args[2]['source'],'all')

    def test_screenshot_default_path_is_unique_and_never_overwrites(self):
        with patch.object(Client,'operation',return_value={'artifact_id':'image','width':2,'height':2}),patch.object(Client,'request',return_value=b'\x89PNG\r\n\x1a\nfixture'):
            images=[]
            for _ in range(2):
                result=CliRunner().invoke(cli,['--project',str(self.project),'screenshot','--session','s','--json'])
                self.assertEqual(result.exit_code,0,result.output);images.append(Path(json.loads(result.stdout)['image']))
        self.assertNotEqual(*images)
        self.assertTrue(all(p.parent==self.project/'captures' and p.exists() for p in images))

    def test_version_cache_is_offline_and_refresh_is_bounded(self):
        path=modsdk_versions.cache_path();path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'versions':['3.9'],'fetched_at':1}))
        with patch.object(modsdk_versions.subprocess,'run',side_effect=AssertionError('network forbidden')):
            self.assertEqual(modsdk_versions.catalog()['versions'],['3.9'])
        with patch.object(modsdk_versions.subprocess,'run',side_effect=subprocess.TimeoutExpired('python',12)) as fetch:
            value=modsdk_versions.catalog(refresh=True)
        self.assertEqual(fetch.call_args.kwargs['timeout'],12);self.assertTrue(value['stale']);self.assertTrue(value['cached'])

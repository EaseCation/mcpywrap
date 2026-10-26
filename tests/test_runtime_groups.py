"""Group contracts: ownership, partial failure and real player verification."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import unittest
import os

from mcpywrap_core.runtime import groups, storage
from mcpywrap_core.mcstudio import sessions
from mcpywrap_core.engines.host import EngineError
from mcpywrap_core.mcstudio.network import ServerTarget
from click.testing import CliRunner
from mcpywrap_core.cli import cli


class GroupTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.backend = Mock(id='windows', capabilities=())

    def record(self, kind='local'):
        record = groups._new(self.root, self.backend, kind,
                             {'target': {'host': 'localhost', 'port': 19132, 'auth': 'none'}, 'overrides': {}})
        for index, member in enumerate(record['members']):
            member.update(session=str(index+1)*32, state='running')
            directory = sessions.session_path(self.root, member['session'])
            storage.write(directory/'session.json', {'state': 'exited', 'session': member['session']})
        groups.save(record)
        return record

    def test_two_running_processes_do_not_count_as_verified_players(self):
        record = self.record('network')
        with patch.object(groups, '_observe', return_value={'player': 'same-player', 'players': ['same-player']}), \
                patch.object(groups.time, 'monotonic', side_effect=[0, 0, 100]), patch.object(groups.time, 'sleep'):
            with self.assertRaises(EngineError) as error:
                groups.verify(record, timeout=1)
        self.assertEqual(error.exception.code, 'players_not_verified')
        self.assertFalse(groups.read(self.root, record['group'])['connection_verified'])

    def test_player_id_before_world_ready_does_not_start_the_next_client(self):
        record = self.record()
        data = {'state': 'running', 'world_ready': False}
        with patch.object(sessions, 'read', return_value=data), \
                patch('mcpywrap_core.mcstudio.runtime_debug.control_request') as control:
            self.assertIsNone(groups._observe(record, record['members'][0]))
        control.assert_not_called()

    def test_external_clients_must_both_observe_the_two_player_identities(self):
        record = self.record('network')
        values = [{'player': 'a', 'players': ['a', 'b'], 'player_names': {'a': 'Alpha', 'b': 'Beta'}},
                  {'player': 'b', 'players': ['a', 'b'], 'player_names': {'a': 'Alpha', 'b': 'Beta'}}]
        with patch.object(groups, '_observe', side_effect=values):
            groups.verify(record, timeout=1)
        self.assertTrue(groups.read(self.root, record['group'])['connection_verified'])

    def test_host_server_confirms_both_players(self):
        record = self.record()
        values = [{'player': 'a', 'player_names': {'a': 'Alpha'}, 'host_network_id': '42'},
                  {'player': 'b', 'player_names': {'b': 'Beta'}, 'host_network_id': '42'}]
        with patch.object(groups, '_observe', side_effect=values), patch(
                'mcpywrap_core.mcstudio.runtime_debug.control_request',
                return_value={'state': 'completed', 'value': {'server-a': 'Alpha', 'server-b': 'Beta'}}) as control:
            groups.verify(record, timeout=1)
        self.assertEqual(control.call_args.kwargs['side'], 'server')
        self.assertEqual(control.call_args.args[1], record['members'][0]['session'])

    def test_external_actor_ids_can_be_scoped_to_each_client(self):
        record = self.record('network')
        values = [{'player': '1', 'player_names': {'1': 'Alpha', '5': 'Beta'}},
                  {'player': '1', 'player_names': {'1': 'Beta', '4': 'Alpha'}}]
        with patch.object(groups, '_observe', side_effect=values):
            groups.verify(record, timeout=1)
        self.assertTrue(groups.read(self.root, record['group'])['connection_verified'])

    def test_matching_actor_ids_in_different_worlds_do_not_prove_connection(self):
        record = self.record('network')
        values = [{'player': 'a', 'player_names': {'a': 'Alpha', 'b': 'SomeoneElse'}},
                  {'player': 'b', 'player_names': {'a': 'SomeoneElse', 'b': 'Beta'}}]
        with patch.object(groups, '_observe', side_effect=values), \
                patch.object(groups.time, 'monotonic', side_effect=[0, 0, 100]), patch.object(groups.time, 'sleep'):
            with self.assertRaises(EngineError):
                groups.verify(record, timeout=1)
        self.assertFalse(groups.read(self.root, record['group'])['connection_verified'])

    def test_stop_guest_before_host_and_do_not_continue_on_uncertain_exit(self):
        record = self.record()
        with patch.object(sessions, 'stop', side_effect=ValueError('still running')) as stop:
            result = groups.stop(self.root, record['group'])
        self.assertFalse(result['ok'])
        self.assertEqual(stop.call_count, 1)
        self.assertEqual(stop.call_args.args[1], record['members'][1]['session'])

    def test_stop_does_not_terminate_host_when_guest_returns_pending(self):
        record = self.record()
        with patch.object(sessions, 'stop', return_value={'state': 'stopping'}) as stop:
            result = groups.stop(self.root, record['group'])
        self.assertFalse(result['ok'])
        self.assertEqual(stop.call_count, 1)
        self.assertEqual(stop.call_args.args[1], record['members'][1]['session'])

    def test_stop_cancels_busy_launch_without_touching_its_members(self):
        record = self.record()
        with groups.directory_lock(groups.path(self.root, record['group']).parent/'lock'), \
                patch.object(sessions, 'stop') as stop:
            with self.assertRaises(groups.LockBusy):
                groups.stop(self.root, record['group'])
        stop.assert_not_called()
        self.assertTrue(groups._cancelled(record))

    def test_restart_does_not_stop_a_replacement_for_the_requested_member(self):
        from contextlib import contextmanager
        record = self.record()
        previous = record['members'][1]['session']
        lock = groups.directory_lock

        @contextmanager
        def replace_before_lock(directory):
            record['members'][1]['session'] = 'a'*32
            groups.save(record)
            with lock(directory):
                yield

        with patch.object(groups, 'directory_lock', replace_before_lock), \
                patch.object(sessions, 'stop') as stop, \
                patch.object(groups, '_connect_member') as connect:
            with self.assertRaises(EngineError) as error:
                groups.restart(self.root, session=previous)
        self.assertEqual(error.exception.code, 'group_changed')
        stop.assert_not_called()
        connect.assert_not_called()

    def test_member_retry_does_not_launch_when_exit_is_unconfirmed(self):
        record = self.record()
        with patch.object(sessions, 'stop', return_value={'state': 'stopping'}), \
                patch.object(groups, '_connect_member') as connect:
            result = groups.restart(self.root, session=record['members'][1]['session'])
        self.assertFalse(result['ok'])
        connect.assert_not_called()

    def test_cancelled_group_cannot_publish_reload(self):
        record = self.record()
        groups.path(self.root, record['group']).with_name('stop').touch()
        with patch('mcpywrap_core.runtime.deployment.refresh') as deploy:
            with self.assertRaises(EngineError) as error:
                groups.reload(self.root, record['group'], 'python', 'Probe', b'VALUE=1')
        self.assertEqual(error.exception.code, 'cancelled')
        deploy.assert_not_called()

    def test_failed_reverification_invalidates_previous_success(self):
        record = self.record()
        record['connection_verified'] = True
        groups.save(record)
        with patch.object(groups, '_observe', side_effect=EngineError('lost connection', 'client_exited')):
            with self.assertRaises(EngineError):
                groups.verify(record)
        self.assertFalse(groups.read(self.root, record['group'])['connection_verified'])

    def test_interruption_stops_only_the_guest_created_by_this_invocation(self):
        record = self.record()
        guest = record['members'][1]['session']
        with patch.object(sessions, 'stop') as stop:
            groups.stop_owned(self.root, record['group'], [guest])
        stop.assert_called_once_with(self.root, guest)
        self.assertFalse(groups.path(self.root, record['group']).with_name('stop').exists())

    def test_observer_interruption_does_not_stop_any_members(self):
        record = self.record()
        from mcpywrap_core.engines.tui import watch_group
        with patch.object(groups, 'status', side_effect=KeyboardInterrupt), patch.object(sessions, 'stop') as stop:
            with self.assertRaises(KeyboardInterrupt):
                watch_group(self.root, dict(group=record['group'], owned_sessions=[]))
        stop.assert_not_called()

    def test_existing_two_members_are_reused_without_acquiring_ownership(self):
        record = self.record()
        self.backend.run.return_value = {'session': record['members'][0]['session'], 'already_running': True}
        with patch.object(groups, '_ready'), patch.object(groups, '_prepare_local'), \
                patch.object(groups.occupancy, 'live', return_value=True), patch.object(groups, '_connect_member') as connect:
            result = groups.start_local(self.root, self.backend, {})
        connect.assert_not_called()
        self.assertEqual(result['owned_sessions'], [])

    def test_manual_menu_is_normal_waiting_without_a_deadline(self):
        record = self.record()
        with patch.object(sessions, 'read', return_value={'state': 'running', 'world_ready': False}), \
                patch.object(groups, '_verify_once') as verify:
            result = groups.refresh_status(self.root, record['group'])
        self.assertTrue(result['ok'])
        self.assertEqual(result['state'], 'waiting_for_join')
        self.assertFalse(result['connection_verified'])
        verify.assert_not_called()

    def test_auto_join_progress_and_failure_are_visible_without_failing_host(self):
        record=self.record();record['recipe']['join_mode']='auto';groups.save(record)
        def current(project,sid):
            if sid==record['members'][0]['session']:
                return {'state':'running','world_ready':True}
            return {'state':'running','world_ready':False,'local_join':{'state':'finding_host'}}
        with patch.object(sessions,'read',side_effect=current):
            result=groups.status(self.root,record['group'])
        self.assertEqual(result['state'],'joining')
        self.assertEqual(result['members'][1]['connection_state'],'finding_host')
        with patch.object(sessions,'read',return_value={'state':'running','local_join':{
                'state':'failed','code':'local_join_timeout','error':'timeout'}}):
            result=groups.status(self.root,record['group'])
        self.assertFalse(result['ok']);self.assertEqual(result['code'],'local_join_timeout')
        self.assertEqual(result['members'][0]['state'],'running')

    def test_transient_probe_busy_keeps_last_verification_and_timestamp(self):
        record=self.record();record.update(connection_verified=True,connection_checked_at=123)
        groups.save(record)
        with patch.object(sessions,'read',return_value={'state':'running','world_ready':True}), \
                patch.object(groups,'_verify_once',side_effect=groups.ObservationBusy):
            result=groups.refresh_status(self.root,record['group'])
        self.assertTrue(result['connection_verified'])
        self.assertEqual(result['connection_checked_at'],123)

    def test_auto_local_handoff_does_not_read_a_null_external_target(self):
        data={'project':str(self.root),'session':'a'*32,'state':'running','game':{'pid':1},'log_path':'log',
              'mode':'network','backend':'windows','network':{'join':'auto','target':None,
              'local_host':'b'*32,'engine':{'version':'3.9.0.401155'}}}
        result=sessions.handoff(data)
        self.assertEqual(result['join'],'auto')
        self.assertEqual(result['local_host'],'b'*32)
        self.assertNotIn('host',result)

    def test_stopped_group_does_not_instruct_joining_closed_games(self):
        record=self.record()
        record['join_instruction']='join the world card'
        groups.save(record)
        result=groups.status(self.root,record['group'])
        self.assertEqual(result['state'],'exited')
        self.assertIsNone(result['join_instruction'])

    def test_manual_guest_launch_does_not_connect_to_an_address_or_wait_for_player(self):
        record = self.record()
        host = {'session':record['members'][0]['session'], 'launch': {'engine': {'version':'3.10'}}}
        self.backend.start_guest.side_effect = lambda *a, **k: {'session':k['session_id'], 'state':'running'}
        with patch.object(groups, 'get_backend', return_value=self.backend), \
                patch.object(sessions, 'read', return_value=host), patch.object(groups, '_ready') as ready:
            groups._connect_member(record, 1, local_host=host['session'])
        self.backend.connect.assert_not_called()
        self.backend.start_guest.assert_called_once()
        ready.assert_not_called()

    def test_unapplied_source_changes_do_not_block_joining_the_active_host(self):
        record=self.record()
        self.backend.run.return_value={'session':record['members'][0]['session'],
                                       'already_running':True,'source_matches':False}
        with patch.object(groups,'_ready'), patch.object(groups,'_prepare_local'), \
                patch.object(groups.occupancy,'live',return_value=False), \
                patch.object(groups,'_connect_member') as guest, \
                patch('mcpywrap_core.runtime.deployment.refresh') as deploy:
            result=groups.start_local(self.root,self.backend,{})
        self.assertTrue(result['ok'])
        guest.assert_called_once()
        self.assertEqual(guest.call_args.kwargs['local_host'],record['members'][0]['session'])
        deploy.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows engine path aliases')
    def test_equivalent_engine_directory_reuses_the_running_world(self):
        from mcpywrap_core.runtime import windows
        engine_path=str(self.root/'engine')
        current={'session':'1'*32,'state':'running','mode':'local','level_id':'world',
                 'launch':{'engine':{'download_dir':engine_path.upper()}}}
        with patch.object(windows,'read_project',return_value={'tool':{'mcpywrap':{'project_type':'map'}}}), \
                patch.object(windows.instances,'select',return_value={'level_id':'world'}), \
                patch.object(windows.occupancy,'active',return_value=[current]), \
                patch.object(windows.sessions,'read',return_value=current), \
                patch.object(windows.sessions,'handoff',return_value={'session':'1'*32}), \
                patch.object(windows,'matches_source',return_value=True), \
                patch.object(windows,'discover_engines') as discover:
            result=windows.run(self.root,detach=True,overrides={'mcs_download_path':engine_path.replace('\\','/')})
        self.assertTrue(result['already_running'])
        discover.assert_not_called()

    def test_same_names_on_another_host_do_not_verify_local_group(self):
        record = self.record()
        values = [{'player':'1','player_names':{'1':'A','2':'B'},'host_network_id':'42'},
                  {'player':'2','player_names':{'1':'A','2':'B'},'host_network_id':'99'}]
        with patch.object(groups, '_observe', side_effect=values), \
                patch('mcpywrap_core.mcstudio.runtime_debug.control_request') as request:
            self.assertFalse(groups._verify_once(record))
        self.assertEqual(record['join_state'], 'wrong_world')
        request.assert_not_called()

    def test_unsupported_backend_fails_before_starting_host(self):
        self.backend.prepare_guest.side_effect = EngineError('unavailable', 'local_join_unavailable')
        with self.assertRaises(EngineError):
            groups.start_local(self.root, self.backend, {})
        self.backend.run.assert_not_called()

    def test_manual_guest_handoff_has_no_synthetic_server_address(self):
        data = {'project':str(self.root),'session':'1'*32,'state':'running','backend':'windows',
                'mode':'network','game':{'pid':123},'log_path':'log','network':{
                    'join':'manual','target':None,'local_host':'2'*32,'engine':{'version':'3.10'}}}
        result = sessions.handoff(data)
        self.assertEqual(result['join'], 'manual')
        self.assertNotIn('host', result)
        self.assertNotIn('port', result)
        self.assertFalse(result['connection_verified'])

    def test_windows_guest_launches_menu_without_writing_cppconfig(self):
        from contextlib import nullcontext
        from dataclasses import asdict
        from mcpywrap_core.engines.windows import WindowsBackend
        from mcpywrap_core.mcstudio.discovery import Engine
        record = self.record()
        data = {'project':str(self.root),'session':record['members'][1]['session'],
                'mode':'network','group':record['group'],'role':'guest',
                'network':{'join':'manual','target':None,'local_host':record['members'][0]['session'],
                           'engine':asdict(Engine('game','3.10','engine','download','test'))}}
        with patch('mcpywrap_core.runtime.profiles.PlayerProfile') as profiles, \
                patch.object(groups, 'is_local_guest', return_value=True), \
                patch('mcpywrap_core.mcstudio.game.open_game') as open_game, \
                patch('mcpywrap_core.mcstudio.network.launch_network') as connect:
            profiles.return_value.lease.return_value = nullcontext()
            profiles.return_value.windows_environment.return_value = {'APPDATA':'private'}
            launched=WindowsBackend().launch(data, Mock(port=12345))
            self.assertIs(launched.process, open_game.return_value)
            self.assertIsNone(open_game.call_args.args[0])
            self.assertEqual(open_game.call_args.kwargs['environment'], {'APPDATA':'private'})
            launched.guard.close()
        connect.assert_not_called()
        self.assertFalse((sessions.session_path(self.root,data['session'])/'runtime.cppconfig').exists())

    def test_guest_in_menu_clears_previous_verification(self):
        record = self.record()
        record['connection_verified'] = True
        groups.save(record)
        with patch.object(sessions, 'read', return_value={'state':'running','world_ready':True}), \
                patch.object(groups, '_observe', return_value=None):
            result = groups.refresh_status(self.root, record['group'])
        self.assertEqual(result['state'], 'waiting_for_join')
        self.assertFalse(result['connection_verified'])

    def test_members_and_retries_use_the_selected_engine_version(self):
        record = groups._new(self.root, self.backend, 'network', {'overrides': {}})
        self.backend.connect.side_effect = lambda *args, **kwargs: {
            'session': kwargs['session_id'], 'state': 'running', 'engine_version': '3.10.0.420447'}
        with patch.object(groups, 'get_backend', return_value=self.backend), patch.object(groups, '_ready'):
            groups._connect_member(record, 0, ServerTarget('localhost'))
            groups._connect_member(record, 1, ServerTarget('localhost'))
        self.assertEqual(self.backend.connect.call_args.kwargs['engine_overrides']['engine_version'], '3.10.0.420447')
        self.assertEqual(groups.read(self.root, record['group'])['recipe']['overrides']['engine_version'], '3.10.0.420447')

    def test_status_recovers_slow_start_without_restarting_games(self):
        record = self.record('network')
        record.update(error='startup timeout', code='world_ready_timeout')
        groups.save(record)
        with patch.object(sessions, 'read', return_value={'state': 'running', 'world_ready': True}), \
                patch.object(groups, '_verify_once', return_value=True), \
                patch.object(sessions, 'start') as start, patch.object(sessions, 'stop') as stop:
            result = groups.refresh_status(self.root, record['group'])
        self.assertTrue(result['ok'])
        self.assertTrue(result['connection_verified'])
        self.assertEqual(result['state'], 'ready')
        start.assert_not_called(); stop.assert_not_called()

    def test_status_does_not_keep_old_connection_success_after_loss(self):
        record = self.record('network')
        record['connection_verified'] = True
        groups.save(record)
        with patch.object(sessions, 'read', return_value={'state': 'running', 'world_ready': True}), \
                patch.object(groups, '_verify_once', return_value=False):
            result = groups.refresh_status(self.root, record['group'])
        self.assertFalse(result['connection_verified'])
        self.assertEqual(result['state'], 'running')

    def test_monitor_releases_lock_during_game_probe_and_discards_stale_result(self):
        record=self.record()
        replacement='f'*32
        def probe(snapshot):
            with groups.directory_lock(groups.path(self.root,record['group']).parent/'lock'):
                latest=groups.read(self.root,record['group'])
                latest['members'][1]['session']=replacement
                groups.save(latest)
            return True
        with patch.object(sessions,'read',return_value={'state':'running','world_ready':True}), \
                patch.object(groups,'_verify_once',side_effect=probe):
            groups.refresh_status(self.root,record['group'])
        latest=groups.read(self.root,record['group'])
        self.assertEqual(latest['members'][1]['session'],replacement)
        self.assertFalse(latest['connection_verified'])

    def test_requested_member_stop_is_not_a_probe_failure(self):
        record=self.record()
        (sessions.session_path(self.root,record['members'][1]['session'])/'stop').touch()
        with patch.object(sessions,'read',return_value={'state':'running','world_ready':True}), \
                patch.object(groups,'_verify_once',side_effect=ValueError('worker exited during probe')):
            result=groups.refresh_status(self.root,record['group'])
        self.assertTrue(result['ok'])
        self.assertIsNone(result['error'])
        self.assertFalse(result['connection_verified'])

    def test_single_host_stop_requires_explicit_group_operation(self):
        record = self.record()
        with patch.object(groups.occupancy, 'live', return_value=True):
            with self.assertRaises(EngineError) as error:
                groups.guard_single_stop(self.root, record['members'][0]['session'])
        self.assertEqual(error.exception.code, 'group_required')

    def test_partial_failure_retains_group_and_successful_member(self):
        record = self.record()
        result = groups._failure(record, EngineError('guest failed', 'client_exited'))
        self.assertFalse(result['ok'])
        self.assertEqual(result['group'], record['group'])
        self.assertEqual(result['members'][0]['session'], record['members'][0]['session'])

    def test_external_reload_is_refused_before_deployment(self):
        record = self.record('network')
        with patch('mcpywrap_core.runtime.deployment.refresh') as deploy:
            with self.assertRaises(EngineError):
                groups.reload(self.root, record['group'], 'python', 'Mod.logic', b'x=1')
        deploy.assert_not_called()

    def test_local_reload_rechecks_connection_before_publishing(self):
        record = self.record()
        ready = {'state': 'running', 'world_ready': True, 'backend': 'windows'}
        with patch.object(sessions, 'read', return_value=ready), \
                patch.object(groups.occupancy, 'live', return_value=True), \
                patch.object(groups, '_verify_once', return_value=False), \
                patch('mcpywrap_core.runtime.deployment.refresh') as deploy:
            with self.assertRaises(EngineError) as error:
                groups.reload(self.root, record['group'], 'python', 'Demo.logic', b'VALUE = 2')
        self.assertEqual(error.exception.code, 'group_not_ready')
        deploy.assert_not_called()

    def test_host_session_cannot_bypass_group_reload_coordination(self):
        from mcpywrap_core.mcstudio.hot_reload import reload_session
        record=self.record()
        host=record['members'][0]['session']
        with patch.object(sessions,'read',return_value={'state':'running','mode':'local','session':host}), \
                patch('mcpywrap_core.runtime.deployment.refresh') as deploy:
            with self.assertRaises(EngineError) as error:
                reload_session(self.root,host,'python','Probe',b'VALUE=1')
        self.assertEqual(error.exception.code,'group_required')
        deploy.assert_not_called()

    def test_cli_requires_exactly_one_target(self):
        runner = CliRunner()
        for command in ('status', 'logs', 'stop', 'restart'):
            result = runner.invoke(cli, ['--local', '--project', str(self.root), command,
                                         '--session', '1'*32, '--group', '2'*32, '--json'])
            self.assertNotEqual(result.exit_code, 0, (command, result.output))

    def test_human_cli_partial_failure_keeps_group_and_member_targets(self):
        gid,host,guest='a'*32,'b'*32,'c'*32
        value={'ok':False,'group':gid,'state':'partial','error':'guest failed',
               'members':[{'role':'host','session':host,'state':'running'},
                          {'role':'guest','session':guest,'state':'failed'}]}
        with patch.object(groups,'refresh_status',return_value=value):
            result=CliRunner().invoke(cli,['--local','--project',str(self.root),'status','--group',gid])
        self.assertEqual(result.exit_code,1)
        for target in (gid,host,guest):
            self.assertIn(target,result.output)

    def test_remote_dual_client_does_not_call_or_fall_back(self):
        runner = CliRunner()
        with patch('mcpywrap_core.remote.client.Client') as remote, patch.object(groups, 'start_network') as local:
            result = runner.invoke(cli, ['--remote', 'http://127.0.0.1:18765', '--project', str(self.root),
                                         'connect', 'localhost', '--clients', '2', '--detach', '--json'])
        self.assertNotEqual(result.exit_code, 0)
        remote.assert_not_called(); local.assert_not_called()


if __name__ == '__main__':
    unittest.main()

"""Combined lifecycle failures: cancellation, late identities and concurrent edits."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
import os
import subprocess
import sys
import threading
import unittest

from test_runtime_deployment import fixture
from mcpywrap.dependencies import read_project, write_project
from mcpywrap.engines.host import EngineError
from mcpywrap.mcstudio import sessions
from mcpywrap.runtime import occupancy, storage, windows, instances
from mcpywrap.runtime.deployment import Deployment, inventory
from mcpywrap.builders.project_builder import AddonProjectBuilder
from mcpywrap.mcstudio.processes import identity
from mcpywrap.utils.locks import directory_lock, LockBusy


class LifecycleRaces(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = fixture(self.root, 'project')

    def publish(self):
        deployment = Deployment(self.project)
        with deployment.lock():
            deployment.prepare()
            deployment.commit()
        return deployment

    def test_worker_creation_failure_does_not_leave_live_starter_reservation(self):
        sid = '1'*32
        with patch.object(sessions.subprocess, 'Popen', side_effect=OSError('cannot create worker')):
            with self.assertRaises((OSError, EngineError)):
                sessions.start(self.project, level_id='world', session_id=sid)
        self.assertEqual(occupancy.active(self.project), [])
        self.assertEqual(sessions.read(self.project, sid)['state'], 'failed')

    def test_observer_timeout_does_not_cancel_another_callers_start(self):
        sid = '8'*32
        directory = sessions.session_path(self.project, sid)
        storage.write(directory/'session.json', {'session': sid, 'state': 'starting'})
        with self.assertRaises(ValueError):
            sessions.wait_started(self.project, sid, timeout=0)
        self.assertFalse((directory/'stop').exists())

    def test_macos_ignores_reused_pid_in_a_failed_old_session(self):
        from mcpywrap.engines import macos
        sid = '9'*32
        old = identity(os.getpid())
        storage.write(sessions.session_path(self.project, sid)/'session.json',
                      dict(project=str(self.project), session=sid, state='failed', backend='macos-arm64',
                           level_id='world', game=old, worker=None))
        replacement = Mock()
        replacement.create_time.return_value = old['created_at'] + 10
        with patch('mcpywrap.mcstudio.processes.psutil.Process', return_value=replacement):
            self.assertIsNone(macos.active_session(self.project, 'world'))
        replacement.terminate.assert_not_called()

    def test_macos_reuse_waits_for_pending_worker_before_handoff(self):
        from mcpywrap.engines import macos
        pending = {'session': 'a'*32, 'state': 'starting', 'game': None}
        ready = dict(pending, state='running', game={'pid': 10})
        item = {'level_id': 'world', 'state': 'ready'}
        with patch.object(macos, 'require_macos'), patch.object(macos, 'instances', return_value=[item]), \
                patch.object(macos, 'active_session', return_value=pending), \
                patch.object(sessions, 'wait_started', return_value=ready) as wait, \
                patch.object(sessions, 'handoff', return_value={'session': ready['session']}) as handoff, \
                patch('mcpywrap.runtime.deployment.matches_source', return_value=True):
            result = macos.run(self.project, instance_prefix='world', detach=True)
        self.assertTrue(result['already_running'])
        wait.assert_called_once_with(self.project, ready['session'])
        handoff.assert_called_once_with(ready)

    def test_cancellation_during_preparation_never_launches_the_game(self):
        deployment = self.publish()
        before = inventory(deployment.target)
        (self.project/'behavior_pack/main.py').write_text('VALUE=2\n')
        sid = '2'*32
        data = dict(project=str(self.project), session=sid, state='starting', mode='local',
                    level_id='world', game=None, worker=None, created_at=1,
                    config_path=str(self.project/'.runtime/world.cppconfig'),
                    launch={'engine': dict(executable='game', version='test', engine_dir='engine',
                                           download_dir='download', source='test')})
        directory = sessions.session_path(self.project, sid)
        storage.write(directory/'session.json', data)
        publish_config = Deployment.publish_config

        def cancel_after_config(owner, *args):
            publish_config(owner, *args)
            (directory/'stop').touch()

        with patch.object(instances, 'world_path', return_value=self.root/'worlds/world'), \
                patch.object(windows, 'require_resources'), \
                patch('mcpywrap.mcstudio.mcs.get_mcs_game_engine_netease_data_path', return_value=str(self.root/'engine')), \
                patch.object(Deployment, 'publish_config', cancel_after_config), \
                patch('mcpywrap.mcstudio.game.open_game', side_effect=AssertionError('cancelled request launched game')) as launch:
            with self.assertRaises(EngineError) as error:
                windows.launch(data, SimpleNamespace(port=12345))
        self.assertEqual(error.exception.code, 'cancelled')
        launch.assert_not_called()
        self.assertEqual(inventory(deployment.target), before)
        self.assertFalse(Path(data['config_path']).exists())

    def test_native_cancellation_uses_the_same_launch_boundary(self):
        from mcpywrap.runtime.native import launch_world
        sid = '7'*32
        directory = self.project/'.runtime/native'
        data = dict(project=str(self.project), session=sid, level_id='world', state='starting',
                    mode='local', game=None, worker=None, config_path=str(directory/'world.cppconfig'),
                    launch={'data': str(directory/'data'), 'engine_version': 'test',
                            'prepare_world': {'supports_config': True}})
        storage.write(sessions.session_path(self.project, sid)/'session.json', data)
        publish_config = Deployment.publish_config

        def cancel_after_config(owner, *args):
            publish_config(owner, *args)
            (sessions.session_path(self.project, sid)/'stop').touch()

        launch = Mock(side_effect=AssertionError('cancelled native request launched game'))
        with patch.object(Deployment, 'publish_config', cancel_after_config):
            with self.assertRaises(EngineError) as error:
                launch_world(data, launch)
        self.assertEqual(error.exception.code, 'cancelled')
        launch.assert_not_called()

    def test_process_exit_releases_an_actually_held_os_lock(self):
        lock = self.root/'process-lock'
        code = ('import sys,time\nfrom mcpywrap.utils.locks import directory_lock\n'
                'with directory_lock(sys.argv[1]):\n print("ready",flush=True)\n time.sleep(120)')
        process = subprocess.Popen([sys.executable, '-u', '-c', code, str(lock)],
                                   cwd=Path(__file__).resolve().parent.parent,
                                   stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'ready')
            with self.assertRaises(LockBusy):
                with directory_lock(lock):
                    self.fail('another process owns the lock')
        finally:
            process.terminate()
            process.wait(timeout=10)
            process.stdout.close()
        self.assertTrue((lock/'service.lock').exists())
        with directory_lock(lock):
            pass

    def test_two_callers_cannot_reserve_the_same_world_concurrently(self):
        from mcpywrap.mcstudio.discovery import Engine
        ready, release = threading.Event(), threading.Event()
        results, errors = [], []
        item = dict(level_id='world', name='world', creation_time=1, state='ready',
                    config_path=str(self.project/'.runtime/world.cppconfig'))

        def start(*args, **kwargs):
            ready.set()
            if not release.wait(20):
                raise AssertionError('test caller did not release launch')
            return {'session': kwargs['session_id']}

        def run():
            try:
                results.append(windows.run(self.project, detach=True))
            except Exception as error:
                errors.append(error)

        engine = Engine('game', 'test', 'engine', 'download', 'test')
        with patch.object(instances, 'select', return_value=item), \
                patch.object(windows, 'discover_engines') as discovery, \
                patch.object(windows, 'require_resources'), \
                patch.object(sessions, 'start', side_effect=start) as launch, \
                patch.object(sessions, 'handoff', side_effect=lambda data: data):
            discovery.return_value.require_engine.return_value = engine
            first = threading.Thread(target=run)
            first.start()
            try:
                self.assertTrue(ready.wait(20))
                with self.assertRaises(LockBusy):
                    windows.run(self.project, detach=True)
            finally:
                release.set()
                first.join(timeout=10)
            self.assertFalse(first.is_alive())
            self.assertEqual(launch.call_count, 1)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)

    def test_update_rejects_unselected_reader_but_allows_explicit_shared_update(self):
        deployment = self.publish()
        original_id = deployment.record['id']
        readers = ('5'*32, '6'*32)
        for sid in readers:
            storage.write(sessions.session_path(self.project, sid)/'session.json',
                          dict(project=str(self.project), session=sid, state='running', game=identity(os.getpid()),
                               deployment={'path': str(deployment.target)}))
        with deployment.lock():
            deployment.prepare()
        self.assertEqual(deployment.record['id'], original_id)
        before = inventory(deployment.target)
        (self.project/'behavior_pack/main.py').write_text('VALUE=2\n')
        with deployment.lock():
            with self.assertRaises(EngineError) as error:
                deployment.prepare(allowed_sessions=readers[:1])
            self.assertEqual(error.exception.code, 'deployment_in_use')
            self.assertEqual(inventory(deployment.target), before)
            deployment.prepare(allowed_sessions=readers)
            deployment.commit()
        self.assertEqual((deployment.target/'behavior_pack/main.py').read_text(), 'VALUE=2\n')

    def test_stop_handles_game_identity_published_while_waiting_for_worker(self):
        sid = '3'*32
        path = sessions.session_path(self.project, sid)/'session.json'
        worker_id, game_id = {'pid': 11}, {'pid': 22}
        data = dict(project=str(self.project), session=sid, state='starting', mode='local',
                    worker=worker_id, game=None, phase='prepared')
        storage.write(path, data)
        worker, game = Mock(), Mock()
        worker_exited = []

        def worker_exit(**kwargs):
            worker_exited.append(True)
            storage.write(path, dict(data, state='failed', game=game_id))

        worker.wait.side_effect = worker_exit

        def observed(record):
            if record == worker_id:
                return None if worker_exited else worker
            return game if record == game_id else None

        with patch.object(sessions, 'observed_process', side_effect=observed):
            result = sessions.stop(self.project, sid)
        self.assertEqual(result['state'], 'exited')
        game.terminate.assert_called_once()
        game.wait.assert_called_once()

    def test_stop_does_not_claim_exit_when_launch_identity_was_never_recorded(self):
        sid = '4'*32
        path = sessions.session_path(self.project, sid)/'session.json'
        storage.write(path, dict(project=str(self.project), session=sid, state='starting',
                                mode='local', worker=None, game=None, phase='prepared'))
        with self.assertRaises(EngineError) as error:
            sessions.stop(self.project, sid)
        self.assertEqual(error.exception.code, 'recovery_required')
        self.assertEqual(storage.read(path)['state'], 'starting')

    def test_incremental_rollback_preserves_a_later_external_file_edit(self):
        deployment = self.publish()
        (self.project/'behavior_pack/main.py').write_text('VALUE=2\n')
        with deployment.lock(), patch('mcpywrap.runtime.deployment.readers', return_value=[{'session': 'reader'}]):
            deployment.prepare(allowed_sessions=('reader',))
            file = deployment.target/'behavior_pack/main.py'
            file.write_text('EXTERNAL_EDIT=True\n')
            with self.assertRaises(EngineError) as error:
                deployment.rollback()
        self.assertEqual(error.exception.code, 'recovery_required')
        self.assertEqual(file.read_text(), 'EXTERNAL_EDIT=True\n')
        self.assertTrue(deployment.journal_path.exists())

    def test_incremental_rollback_preserves_an_external_empty_directory(self):
        deployment = self.publish()
        (self.project/'behavior_pack/new-empty-directory').mkdir()
        with deployment.lock(), patch('mcpywrap.runtime.deployment.readers', return_value=[{'session': 'reader'}]):
            deployment.prepare(allowed_sessions=('reader',))
            external = deployment.target/'external-empty-directory'
            external.mkdir()
            with self.assertRaises(EngineError):
                deployment.rollback()
        self.assertTrue(external.is_dir())

    def test_file_to_directory_change_requires_restart_before_any_write(self):
        source = self.project/'behavior_pack/slot'
        source.write_text('original file')
        deployment = self.publish()
        before = inventory(deployment.target)
        source.unlink()
        source.mkdir()
        (source/'nested.py').write_text('VALUE=2\n')
        with deployment.lock(), patch('mcpywrap.runtime.deployment.readers', return_value=[{'session': 'reader'}]):
            with self.assertRaises(EngineError) as error:
                deployment.prepare(allowed_sessions=('reader',))
        self.assertEqual(error.exception.code, 'restart_required')
        self.assertEqual(inventory(deployment.target), before)

    def test_external_config_is_checked_before_any_rollback_mutation(self):
        deployment = self.publish()
        config = self.project/'.runtime/world.cppconfig'
        storage.write(config, {'world_info': {'name': 'before'}})
        (self.project/'behavior_pack/main.py').write_text('VALUE=2\n')
        with deployment.lock():
            deployment.prepare()
            deployment.publish_config(config, {'world_info': {'name': 'published'}})
            published = inventory(deployment.target)
            storage.write(config, {'world_info': {'name': 'external edit'}})
            with self.assertRaises(EngineError):
                deployment.rollback()
        self.assertEqual(inventory(deployment.target), published)
        self.assertEqual(storage.read(config)['world_info']['name'], 'external edit')

    def test_source_edit_during_assembly_is_rejected_before_publication(self):
        deployment = self.publish()
        before = inventory(deployment.target)
        source = self.project/'behavior_pack/main.py'
        source.write_text('VALUE=2\n')
        build = AddonProjectBuilder.build

        def edit_after_build(builder):
            result = build(builder)
            source.write_text('VALUE=3\n')
            return result

        with deployment.lock(), patch.object(AddonProjectBuilder, 'build', edit_after_build):
            with self.assertRaises(EngineError) as error:
                deployment.prepare()
        self.assertEqual(error.exception.code, 'source_changed')
        self.assertEqual(inventory(deployment.target), before)

    def test_transitive_declaration_edit_during_assembly_is_also_rejected(self):
        common = fixture(self.root, 'common')
        fixture(self.root, 'leaf')
        config = read_project(self.project)
        config['tool']['mcpywrap']['local_dependencies'] = ['../common']
        write_project(self.project, config)
        deployment = self.publish()
        before = inventory(deployment.target)
        (self.project/'behavior_pack/main.py').write_text('VALUE=2\n')
        build = AddonProjectBuilder.build

        def edit_graph_after_build(builder):
            result = build(builder)
            config = read_project(common)
            config['tool']['mcpywrap']['local_dependencies'] = ['../leaf']
            write_project(common, config)
            return result

        with deployment.lock(), patch.object(AddonProjectBuilder, 'build', edit_graph_after_build):
            with self.assertRaises(EngineError) as error:
                deployment.prepare()
        self.assertEqual(error.exception.code, 'source_changed')
        self.assertEqual(inventory(deployment.target), before)


if __name__ == '__main__':
    unittest.main()

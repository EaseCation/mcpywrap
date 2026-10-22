"""Regression hypotheses for dependency removal, migration and interrupted startup."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json
import os
import subprocess
import sys
import unittest

from test_runtime_deployment import fixture
from mcpywrap_core.dependencies import read_project, write_project
from mcpywrap_core.engines.backend import LaunchedGame
from mcpywrap_core.engines.host import EngineError
from mcpywrap_core.mcstudio import sessions, session_worker
from mcpywrap_core.mcstudio.deployment_links import ManagedLinks
from mcpywrap_core.mcstudio.processes import identity
from mcpywrap_core.mcstudio.symlinks import _create_directory_link
from mcpywrap_core.runtime import instances, storage, windows
from mcpywrap_core.runtime.deployment import Deployment, inventory
from mcpywrap_core.utils.locks import LockBusy


class LifecycleAudit(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = fixture(self.root, 'project')

    def publish(self):
        deployment = Deployment(self.project)
        with deployment.lock():
            pack = deployment.prepare()
            deployment.commit()
        return deployment, pack

    def dependencies(self, project, paths):
        config = read_project(project)
        config['tool']['mcpywrap']['local_dependencies'] = paths
        write_project(project, config)

    def test_replacement_and_transitive_removal_leave_no_old_files(self):
        common = fixture(self.root, 'common')
        leaf = fixture(self.root, 'leaf')
        replacement = fixture(self.root, 'replacement')
        for project in (common, leaf, replacement):
            (project/'behavior_pack'/(project.name + '.json')).write_text('{}')
        self.dependencies(common, ['../leaf'])
        self.dependencies(self.project, ['../common'])
        deployment, pack = self.publish()
        target = Path(pack.behavior_pack_dir)
        self.assertTrue((target/'leaf.json').exists())
        self.dependencies(common, [])
        self.publish()
        self.assertFalse((target/'leaf.json').exists())
        self.assertTrue((target/'common.json').exists())
        self.dependencies(self.project, ['../replacement'])
        self.publish()
        self.assertFalse((target/'common.json').exists())
        self.assertTrue((target/'replacement.json').exists())

    def test_legacy_source_links_migrate_once_and_survive_last_dependency_removal(self):
        engine = self.root/'engine'
        old = engine/'behavior_packs/legacy'
        old.parent.mkdir(parents=True)
        _create_directory_link(str(self.project/'behavior_pack'), str(old))
        (self.project/'.runtime').mkdir()
        (self.project/'.runtime/000-broken.cppconfig').write_text('{interrupted config')
        storage.write(self.project/'.runtime/001-invalid.cppconfig', {'world_info': {'behavior_packs': None}})
        storage.write(self.project/'.runtime/old.cppconfig', {'world_info': {'behavior_packs': ['legacy']}})
        common = fixture(self.root, 'common')
        self.dependencies(self.project, ['../common'])
        deployment, pack = self.publish()
        links = ManagedLinks(engine, self.project)
        names, _ = links.publish([pack], deployment.record['id'])
        self.assertFalse(os.path.lexists(old))
        self.dependencies(self.project, [])
        next_deployment, next_pack = self.publish()
        next_names, _ = links.publish([next_pack], next_deployment.record['id'])
        self.assertEqual(names, next_names)
        self.assertEqual((engine/'behavior_packs'/names['behavior'][0]).resolve(), Path(pack.behavior_pack_dir))

    def test_failed_new_instance_is_not_default_and_can_be_retried_explicitly(self):
        with patch.object(instances, 'world_path', return_value=self.root/'world'):
            good = instances.select(self.project, new=True)
            instances.attempt(self.project, good, 'a'*32)
            instances.mark(dict(project=str(self.project), mode='local', session='a'*32,
                                level_id=good['level_id'], created_at=good['creation_time']), ready=True)
            failed = instances.select(self.project, new=True)
            instances.attempt(self.project, failed, 'b'*32)
            instances.mark(dict(project=str(self.project), mode='local', session='b'*32,
                                level_id=failed['level_id'], created_at=failed['creation_time']))
            self.assertEqual(instances.select(self.project)['level_id'], good['level_id'])
            self.assertEqual(instances.select(self.project, prefix=failed['level_id'])['state'], 'failed')

    def test_same_uuid_does_not_allow_another_project_to_take_ownership(self):
        import shutil
        deployment, pack = self.publish()
        links = ManagedLinks(self.root/'engine', self.project)
        links.publish([pack], deployment.record['id'])
        registry = storage.read(links.path)
        other = fixture(self.root, 'other')
        shutil.copyfile(self.project/'behavior_pack/manifest.json', other/'behavior_pack/manifest.json')
        other_deployment = Deployment(other)
        with other_deployment.lock():
            other_pack = other_deployment.prepare()
            other_deployment.commit()
        with self.assertRaises(EngineError) as error:
            ManagedLinks(links.root, other).publish([other_pack], other_deployment.record['id'])
        self.assertEqual(error.exception.code, 'pack_conflict')
        self.assertEqual(storage.read(links.path), registry)

    def test_link_name_migration_requires_existing_readers_to_exit(self):
        deployment, pack = self.publish()
        links = ManagedLinks(self.root/'engine', self.project)
        names, _ = links.publish([pack], deployment.record['id'])
        registry = storage.read(links.path)
        for key, entry in list(registry['links'].items()):
            old_key = str(Path(key).parent/'previous_name').replace('\\', '/')
            (links.root/key).rename(links.root/old_key)
            registry['links'][old_key] = registry['links'].pop(key)
        storage.write(links.path, registry)
        session = 'e'*32
        session_file = sessions.session_path(self.project, session)/'session.json'
        storage.write(session_file, dict(project=str(self.project), session=session, state='running', game=identity(os.getpid())))
        with self.assertRaises(EngineError) as error:
            links.publish([pack], deployment.record['id'])
        self.assertEqual(error.exception.code, 'deployment_in_use')
        self.assertEqual(storage.read(links.path), registry)
        storage.write(session_file, dict(project=str(self.project), session=session, state='exited', game=None))
        migrated, _ = links.publish([pack], deployment.record['id'])
        self.assertEqual(migrated, names)

    def test_dead_game_releases_world_and_os_lock_without_deleting_metadata(self):
        world = self.root/'worlds/test'
        process = subprocess.Popen([sys.executable, '-u', '-c',
                                    'import time; print("ready", flush=True); time.sleep(120)'],
                                   stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'ready')
            data = dict(project=str(self.project), session='c'*32, state='failed', worker=None,
                        game=identity(process.pid), phase='prepared')
            storage.write(sessions.session_path(self.project, data['session'])/'session.json', data)
            with instances.world_lock(world, data):
                pass
            with self.assertRaises(EngineError):
                with instances.world_lock(world):
                    self.fail('live game must retain its world')
        finally:
            process.terminate()
            process.wait(timeout=10)
            process.stdout.close()
        with instances.world_lock(world):
            pass
        self.assertTrue(list(world.parent.glob('.mcpy-world-locks/*/service.lock')))

    def test_partial_link_publication_restores_files_links_and_config(self):
        deployment, pack = self.publish()
        engine = self.root/'engine'
        links = ManagedLinks(engine, self.project)
        names, _ = links.publish([pack], deployment.record['id'])
        before = inventory(deployment.target)
        registry = storage.read(links.path)
        config = self.project/'.runtime/world.cppconfig'
        storage.write(config, {'world_info': {'name': 'original'}})
        import uuid
        for kind in ('behavior', 'resource'):
            manifest = self.project/(kind+'_pack/manifest.json')
            data = storage.read(manifest)
            data['header']['uuid'] = str(uuid.uuid4())
            storage.write(manifest, data)
        original_link = _create_directory_link

        def fail_resource(source, target):
            if Path(target).parent.name == 'resource_packs' and Path(target).name not in names['resource']:
                raise OSError('injected resource link publication failure')
            original_link(source, target)

        with deployment.lock():
            next_pack = deployment.prepare()
            deployment.publish_config(config, {'world_info': {'name': 'uncommitted'}})
            with patch('mcpywrap_core.mcstudio.deployment_links._create_directory_link', side_effect=fail_resource):
                with self.assertRaisesRegex(OSError, 'injected'):
                    deployment.publish_links(engine, [next_pack])
            deployment.rollback()
        self.assertEqual(inventory(deployment.target), before)
        self.assertEqual(storage.read(links.path), registry)
        self.assertEqual(storage.read(config), {'world_info': {'name': 'original'}})
        self.assertFalse(deployment.journal_path.exists())
        self.assertFalse(links.journal_path.exists())
        with deployment.lock():
            next_pack = deployment.prepare()
            deployment.publish_links(engine, [next_pack])
            deployment.commit()

    def test_map_removal_keeps_world_progress_and_removes_dependency_links(self):
        import shutil
        from mcpywrap_core.builders.MapPack import MapPack
        common = fixture(self.root, 'common')
        world_source = self.root/'map'
        world_source.mkdir()
        write_project(world_source, {'project': {'name': 'map'}, 'tool': {'mcpywrap': {
            'project_type': 'map', 'local_dependencies': ['../common']}}})
        shutil.copytree(self.project/'behavior_pack', world_source/'behavior_packs/main')
        (world_source/'db').mkdir()
        (world_source/'db/marker').write_text('template')
        (world_source/'level.dat').write_bytes(b'template level')
        world = self.root/'played-world'
        world.mkdir()
        MapPack('map', str(world_source)).copy_level_data_to(world)
        (world/'db/marker').write_text('player progress')
        (world/'level.dat').write_bytes(b'played level')
        deployment = Deployment(world_source)
        links = ManagedLinks(self.root/'map-engine', world_source)
        with deployment.lock():
            packs = deployment.prepare()
            initial, _ = links.publish(packs, deployment.record['id'])
            deployment.commit()
        self.dependencies(world_source, [])
        with deployment.lock():
            packs = deployment.prepare()
            remaining, _ = links.publish(packs, deployment.record['id'])
            deployment.commit()
        MapPack('map', str(world_source)).copy_level_data_to(world)
        self.assertEqual((world/'db/marker').read_text(), 'player progress')
        self.assertEqual((world/'level.dat').read_bytes(), b'played level')
        self.assertEqual(len(initial['behavior']), 2)
        self.assertEqual(len(remaining['behavior']), 1)
        self.assertEqual(remaining['resource'], [])
        self.assertEqual(len(list((links.root/'behavior_packs').iterdir())), 1)

    def test_recovery_can_resume_after_another_directory_exchange_failure(self):
        deployment, _ = self.publish()
        before = inventory(deployment.target)
        (self.project/'behavior_pack/main.py').write_text('VALUE = 2\n')
        with deployment.lock():
            deployment.prepare()
        journal = storage.read(deployment.journal_path)
        journal['owner'] = None
        storage.write(deployment.journal_path, journal)
        from mcpywrap_core.runtime.deployment import _replace_with_retry

        def interrupt_restore(source, target):
            if Path(source).name == 'previous':
                raise OSError('interrupted recovery')
            _replace_with_retry(source, target)

        recovery = Deployment(self.project)
        with recovery.lock(), patch('mcpywrap_core.runtime.deployment._replace_with_retry', side_effect=interrupt_restore):
            with self.assertRaisesRegex(OSError, 'interrupted recovery'):
                recovery.recover()
        self.assertTrue(deployment.journal_path.exists())
        with recovery.lock():
            recovery.recover()
        self.assertEqual(inventory(deployment.target), before)
        self.assertFalse(deployment.journal_path.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing semantics')
    def test_windows_directory_handle_failure_can_retry_without_stale_lock(self):
        import ctypes
        from ctypes import wintypes
        deployment, _ = self.publish()
        before = inventory(deployment.target)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        # Read/write sharing, deliberately without FILE_SHARE_DELETE.
        handle = kernel.CreateFileW(str(deployment.target), 0x80000000, 3, None, 3, 0x02000000, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            (self.project/'behavior_pack/main.py').write_text('VALUE = 2\n')
            with deployment.lock(), self.assertRaises(OSError):
                deployment.prepare()
            self.assertEqual(inventory(deployment.target), before)
        finally:
            kernel.CloseHandle(handle)
        with deployment.lock():
            deployment.prepare()
            deployment.commit()
        self.assertEqual((deployment.target/'behavior_pack/main.py').read_text(), 'VALUE = 2\n')

    def test_dependency_refresh_and_editor_preparation_do_not_write_runtime(self):
        from mcpywrap_core.runtime.preparation import prepare_editor, resolve_packs
        deployment, _ = self.publish()
        before = inventory(deployment.target)
        common = fixture(self.root, 'common')
        (common/'behavior_pack/dependency.json').write_text('{}')
        self.dependencies(self.project, ['../common'])
        resolve_packs(self.project)
        packs = prepare_editor(self.project)
        self.assertEqual(inventory(deployment.target), before)
        self.assertNotEqual(Path(packs[0].path), deployment.target)
        self.assertTrue((Path(packs[0].behavior_pack_dir)/'dependency.json').is_file())

    def test_rejected_recovery_never_rolls_back_an_unclaimed_launch(self):
        deployment, _ = self.publish()
        (self.project/'behavior_pack/main.py').write_text('VALUE = 2\n')
        with deployment.lock():
            deployment.prepare()
            deployment.spawning()
        # Reproduce a worker lost between spawning and persisting the game PID.
        journal = storage.read(deployment.journal_path)
        journal['owner'] = None
        storage.write(deployment.journal_path, journal)
        before = inventory(deployment.target)
        session = 'a'*32
        data = dict(project=str(self.project), session=session, level_id='world',
                    config_path=str(self.project/'.runtime/world.cppconfig'),
                    launch={'engine': dict(executable='game', version='test', engine_dir='engine',
                                           download_dir='download', source='test')})
        with patch.object(instances, 'world_path', return_value=self.root/'worlds/world'), \
                patch('mcpywrap_core.runtime.deployment_service.global_root', return_value=self.root/'engine'), \
                patch.object(windows, 'require_resources'):
            with self.assertRaises(EngineError) as error:
                windows.launch(data, SimpleNamespace(port=12345))
        self.assertEqual(error.exception.code, 'recovery_required')
        self.assertEqual(inventory(deployment.target), before)
        self.assertEqual(storage.read(deployment.journal_path), journal)

    def test_world_ready_lock_contention_does_not_terminate_game(self):
        session = 'a'*32
        directory = sessions.session_path(self.project, session)
        sessions.save(directory/'session.json', dict(state='starting', mode='local', game=None,
                      backend='windows', level_id='world', created_at=1,
                      log_path=str(directory/'game.log')))
        process = Mock(pid=os.getpid())
        # Startup check, two observation loops, natural exit, final cleanup.
        process.poll.side_effect = [None, None, None, 0, 0]
        process.wait.return_value = 0
        deployment = Mock()
        locks = []

        @contextmanager
        def lock():
            locks.append(True)
            if len(locks) == 1:
                raise LockBusy('another reader is checking the deployment')
            yield

        deployment.lock.side_effect = lock
        backend = Mock()
        backend.launch.return_value = LaunchedGame(process, capture_output=False, deployment=deployment)
        backend.debug_channel.return_value = SimpleNamespace(start=Mock(), close=Mock())

        def refresh(data, channel):
            changed = not data.get('world_ready')
            data['world_ready'] = True
            return changed

        backend.refresh.side_effect = refresh
        with patch('mcpywrap_core.engines.backend.get_backend', return_value=backend), \
                patch.object(session_worker, 'FileLogServer'), \
                patch('mcpywrap_core.mcstudio.runtime_debug.RuntimeControlServer') as server, \
                patch.object(session_worker.time, 'sleep'):
            server.return_value.server_address = ('localhost', 12345)
            session_worker.run(str(self.project), session)
        process.terminate.assert_not_called()
        deployment.commit.assert_called_once()
        self.assertEqual(storage.read(directory/'session.json')['state'], 'exited')
        self.assertEqual(storage.read(instances.record_path(self.project, 'world'))['state'], 'ready')

    def test_orphan_game_is_not_reported_as_a_healthy_reusable_session(self):
        data = dict(project=str(self.project), session='d'*32, state='running', mode='local',
                    level_id='world', worker=None, game=identity(os.getpid()), backend='windows')
        storage.write(sessions.session_path(self.project, data['session'])/'session.json', data)
        with patch.object(instances, 'select', return_value={'level_id': 'world'}), \
                patch.object(sessions, 'handoff', return_value={'state': 'running'}) as handoff:
            with self.assertRaises(EngineError) as error:
                windows.run(self.project, detach=True)
        self.assertEqual(error.exception.code, 'recovery_required')
        handoff.assert_not_called()


if __name__ == '__main__':
    unittest.main()

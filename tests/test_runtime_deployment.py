"""Real filesystem transitions and process ownership, without a game or global packs."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import os
import unittest
import uuid

from mcpywrap.dependencies import write_project, read_project
from mcpywrap.runtime.deployment import Deployment, inventory
from mcpywrap.mcstudio.deployment_links import ManagedLinks
from mcpywrap.engines.host import EngineError
from mcpywrap.mcstudio.processes import identity


def fixture(root, name):
    root = Path(root)/name
    root.mkdir()
    for kind, module in (('behavior', 'data'), ('resource', 'resources')):
        pack = root/(kind + '_pack')
        pack.mkdir()
        (pack/'manifest.json').write_text(json.dumps({'format_version': 1,
            'header': {'name': name, 'description': name, 'uuid': str(uuid.uuid4()), 'version': [1, 0, 0]},
            'modules': [{'type': module, 'uuid': str(uuid.uuid4()), 'version': [1, 0, 0]}]}), encoding='utf-8')
    (root/'behavior_pack/main.py').write_bytes(b'VALUE = 1\r\n')
    write_project(root, {'project': {'name': name, 'version': '1.0', 'dependencies': []},
                        'tool': {'mcpywrap': {'project_type': 'addon', 'local_dependencies': []}}})
    return root


def directory_link(source, target):
    # Force the non-admin fallback even when CI has symlink privileges.
    if os.name == 'nt':
        import _winapi
        _winapi.CreateJunction(str(source), str(target))
    else:
        os.symlink(source, target, target_is_directory=True)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = fixture(self.root, 'main.git-copy')

    def publish(self):
        deployment = Deployment(self.project)
        with deployment.lock():
            pack = deployment.prepare()
            deployment.commit()
        return deployment, pack

    def test_zero_one_zero_dependencies_use_one_path_without_stale_files(self):
        dep = fixture(self.root, 'common')
        (dep/'behavior_pack/only_dependency.json').write_text('{}')
        first, pack = self.publish()
        path = pack.behavior_pack_dir
        config = read_project(self.project)
        config['tool']['mcpywrap']['local_dependencies'] = ['../common']
        write_project(self.project, config)
        second, pack = self.publish()
        self.assertEqual(path, pack.behavior_pack_dir)
        self.assertTrue((Path(path)/'only_dependency.json').exists())
        config['tool']['mcpywrap']['local_dependencies'] = []
        write_project(self.project, config)
        third, pack = self.publish()
        self.assertEqual(path, pack.behavior_pack_dir)
        self.assertFalse((Path(path)/'only_dependency.json').exists())

    def test_no_change_does_not_replace_runtime(self):
        first, _ = self.publish()
        inode = first.target.stat().st_ino
        with patch('mcpywrap.runtime.deployment._replace_with_retry', side_effect=AssertionError('unexpected write')):
            second, _ = self.publish()
        self.assertEqual(first.record['id'], second.record['id'])
        self.assertEqual(inode, second.target.stat().st_ino)

    def test_copy_semantics_and_stable_pack_names(self):
        bp = self.project/'behavior_pack'
        (bp/'entities').mkdir()
        (bp/'terrain.soil.json').write_bytes(b'{}')
        _, pack = self.publish()
        target = Path(pack.behavior_pack_dir)
        self.assertTrue((target/'entities').is_dir())
        self.assertEqual((target/'main.py').read_bytes(), b'VALUE = 1\r\n')
        self.assertEqual((target/'terrain.soil.json').read_bytes(), b'{}')
        bp.rename(self.project/'BehaviorPack_changed')
        _, next_pack = self.publish()
        self.assertEqual(pack.behavior_pack_dir, next_pack.behavior_pack_dir)

    @unittest.skipUnless(os.name == 'nt', 'Windows extended path spelling')
    def test_pack_filter_accepts_mixed_extended_path_forms(self):
        from mcpywrap.builders.AddonsPack import AddonsPack
        from mcpywrap.source_files import long_path
        ordinary = str(self.project.resolve())
        extended = str(long_path(ordinary))
        pack = AddonsPack('fixture', ordinary, is_origin=True)
        for root, source in ((extended, ordinary), (ordinary, extended)):
            with self.subTest(root=root, source=source):
                pack.path = root
                self.assertFalse(pack.should_exclude(os.path.join(source, 'behavior_pack', 'terrain.soil.json')))
                self.assertTrue(pack.should_exclude(os.path.join(source, 'behavior_pack', '__pycache__', 'main.pyc')))

    def test_active_reader_prevents_ordinary_replacement_before_writes(self):
        deployment, _ = self.publish()
        old = inventory(deployment.target)
        (self.project/'behavior_pack/main.py').write_text('VALUE = 2\n')
        reader = {'session': 'a'*32}
        with patch('mcpywrap.runtime.deployment.readers', return_value=[reader]):
            with deployment.lock(), self.assertRaisesRegex(EngineError, '运行包正在使用'):
                deployment.prepare()
        self.assertEqual(inventory(deployment.target), old)

    def test_failed_publication_restores_previous_files(self):
        deployment, _ = self.publish()
        old = inventory(deployment.target)
        (self.project/'behavior_pack/main.py').write_text('VALUE = 2\n')
        from mcpywrap.runtime.deployment import _replace_with_retry
        def failing(source, target):
            if Path(source).name == 'output' and Path(target) == deployment.target:
                raise OSError('fixture publish failure')
            return _replace_with_retry(source, target)
        with patch('mcpywrap.runtime.deployment._replace_with_retry', side_effect=failing):
            with deployment.lock(), self.assertRaises(OSError):
                deployment.prepare()
        self.assertEqual(inventory(deployment.target), old)

    def test_external_runtime_write_is_preserved_and_reported(self):
        deployment, _ = self.publish()
        extra = deployment.target/'player-data.json'
        extra.write_text('{}')
        with deployment.lock(), self.assertRaises(EngineError) as error:
            deployment.prepare()
        self.assertEqual(error.exception.code, 'deployment_modified')
        self.assertTrue(extra.is_file())

    def test_owned_links_are_reused_and_unknown_copy_is_preserved(self):
        deployment, pack = self.publish()
        links = ManagedLinks(self.root/'engine', self.project)
        first, _ = links.publish([pack], deployment.record['id'])
        second, _ = links.publish([pack], deployment.record['id'])
        self.assertEqual(first, second)
        import shutil
        unknown = self.root/'engine/behavior_packs/manual'
        shutil.copytree(pack.behavior_pack_dir, unknown)
        with self.assertRaises(EngineError) as error:
            links.publish([pack], deployment.record['id'])
        self.assertEqual(error.exception.code, 'pack_conflict')
        self.assertTrue((unknown/'manifest.json').is_file())

    def test_build_cannot_write_runtime_directly(self):
        from mcpywrap.builders.project_builder import AddonProjectBuilder
        success, error = AddonProjectBuilder(self.project, self.project/'.mcpy/runtime/assembled').build()
        self.assertFalse(success)
        self.assertIn('run', error)

    def test_runtime_replaced_with_junction_never_writes_its_destination(self):
        outside = self.root/'outside'
        outside.mkdir()
        marker = outside/'keep.txt'
        marker.write_text('external data', encoding='utf-8')
        runtime = self.project/'.mcpy/runtime'
        runtime.parent.mkdir(parents=True)
        directory_link(outside, runtime)
        with self.assertRaises(EngineError) as error:
            Deployment(self.project)
        self.assertEqual(error.exception.code, 'deployment_modified')
        self.assertEqual(list(outside.iterdir()), [marker])

    def test_build_rejects_link_target_before_resolving_it(self):
        from mcpywrap.builders.project_builder import AddonProjectBuilder
        outside = self.root/'outside'
        outside.mkdir()
        marker = outside/'keep.txt'
        marker.write_text('external data', encoding='utf-8')
        alias = self.project/'build-link'
        directory_link(outside, alias)
        success, _ = AddonProjectBuilder(self.project, alias).build()
        self.assertFalse(success)
        self.assertEqual(list(outside.iterdir()), [marker])

    def test_map_build_rejects_link_before_clearing_destination(self):
        from mcpywrap.builders.project_builder import MapProjectBuilder
        outside = self.root/'outside-map'
        outside.mkdir()
        marker = outside/'level.dat'
        marker.write_bytes(b'world to preserve')
        alias = self.project/'map-output'
        directory_link(outside, alias)
        success, _ = MapProjectBuilder(self.project, alias).build()
        self.assertFalse(success)
        self.assertEqual(marker.read_bytes(), b'world to preserve')

    def test_inventory_rejects_nested_directory_link(self):
        deployment, _ = self.publish()
        outside = self.root/'outside-nested'
        outside.mkdir()
        (outside/'keep').write_bytes(b'owned elsewhere')
        directory_link(outside, deployment.target/'behavior_pack/external')
        with self.assertRaises(EngineError):
            inventory(deployment.target)
        self.assertEqual((outside/'keep').read_bytes(), b'owned elsewhere')

    def test_world_delete_rejects_link_and_preserves_external_world(self):
        from mcpywrap.runtime import instances
        outside = self.root/'external-world'
        outside.mkdir()
        (outside/'level.dat').write_bytes(b'world to preserve')
        alias = self.project/'linked-world'
        directory_link(outside, alias)
        with patch.object(instances, 'world_path', return_value=alias):
            with self.assertRaises(EngineError):
                instances.delete(self.project, [{'level_id': 'world'}])
        self.assertEqual((outside/'level.dat').read_bytes(), b'world to preserve')

    def test_link_rollback_preserves_later_registration(self):
        from mcpywrap.runtime import storage
        deployment, pack = self.publish()
        links = ManagedLinks(self.root/'engine', self.project)
        links.publish([pack], deployment.record['id'])
        _, journal = links.publish([pack], 'new-deployment')
        changed = storage.read(links.path)
        key = next(iter(changed['links']))
        changed['links'][key]['deployment'] = 'external-deployment'
        storage.write(links.path, changed)
        with self.assertRaises(EngineError) as error:
            links.restore(journal)
        self.assertEqual(error.exception.code, 'recovery_required')
        self.assertEqual(storage.read(links.path), changed)
        self.assertTrue((links.root/key).is_dir())

    def test_link_rollback_restores_metadata_without_changing_reused_links(self):
        from mcpywrap.runtime import storage
        deployment, pack = self.publish()
        links = ManagedLinks(self.root/'engine', self.project)
        links.publish([pack], deployment.record['id'])
        before = storage.read(links.path)
        _, journal = links.publish([pack], 'new-deployment')
        self.assertNotEqual(storage.read(links.path), before)
        links.restore(journal)
        self.assertEqual(storage.read(links.path), before)
        links.restore(journal)
        self.assertEqual(storage.read(links.path), before)

    def test_world_lease_survives_worker_exit_and_blocks_other_projects(self):
        from mcpywrap.runtime import instances, storage
        from mcpywrap.mcstudio.sessions import session_path
        other = fixture(self.root, 'other')
        world = self.root/'shared-worlds'/'one-world'
        record = {'project': str(self.project), 'session': 'a'*32, 'state': 'failed',
                  'worker': None, 'game': identity(os.getpid())}
        session_file = session_path(self.project, record['session'])/'session.json'
        storage.write(session_file, record)
        with instances.world_lock(world, record):
            pass
        other_record = {'project': str(other), 'session': 'b'*32}
        with self.assertRaises(EngineError) as error:
            with instances.world_lock(world, other_record):
                self.fail('a live game must retain its world')
        self.assertEqual(error.exception.code, 'world_in_use')
        record.update(game=None, state='exited')
        storage.write(session_file, record)
        with instances.world_lock(world):
            pass

    def test_world_launch_identity_gap_requires_recovery(self):
        from mcpywrap.runtime import instances, storage
        from mcpywrap.mcstudio.sessions import session_path
        world = self.root/'shared-worlds'/'one-world'
        record = {'project': str(self.project), 'session': 'a'*32, 'state': 'starting',
                  'phase': 'prepared', 'worker': None, 'game': None}
        storage.write(session_path(self.project, record['session'])/'session.json', record)
        with instances.world_lock(world, record):
            pass
        with self.assertRaises(EngineError) as error:
            with instances.world_lock(world):
                self.fail('unrecorded game identity cannot be treated as exit')
        self.assertEqual(error.exception.code, 'recovery_required')


if __name__ == '__main__':
    unittest.main()

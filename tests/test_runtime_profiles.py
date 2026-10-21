"""Player profiles preserve identity without borrowing another player's files."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import os
import shutil
import unittest

from mcpywrap.runtime import groups, storage
from mcpywrap.runtime.profiles import PlayerProfile
from mcpywrap.mcstudio.sessions import session_path
from mcpywrap.mcstudio.processes import identity
from mcpywrap.engines.host import EngineError


class ProfileTests(unittest.TestCase):
    def windows_profile(self, profile):
        root = profile.windows_directory()
        def cleanup():
            if root.exists():
                self.assertEqual(storage.read(root/'.mcpy-owner.json'), profile.owner)
                shutil.rmtree(root)
        self.addCleanup(cleanup)
        return root

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.group = groups._new(self.root, Mock(id='windows'), 'network', {})

    def data(self, index):
        member = self.group['members'][index]
        data = {'project': str(self.root), 'group': self.group['group'], 'role': member['role'],
                'session': member['session'], 'state': 'exited', 'game': None, 'worker': None, 'network': {}}
        storage.write(session_path(self.root, data['session'])/'session.json', data)
        return data

    def test_roles_are_isolated_and_restart_preserves_existing_identity(self):
        first, second = PlayerProfile(self.data(0)), PlayerProfile(self.data(1))
        with first.lease():
            first.prepare()
            identity_file = first.root/'client-identity'
            identity_file.write_bytes(b'persisted role identity')
        second.prepare()
        self.assertNotEqual(first.root, second.root)
        self.assertFalse((second.root/identity_file.name).exists())
        repeated = PlayerProfile(self.data(0))
        with repeated.lease():
            repeated.prepare()
        self.assertEqual(identity_file.read_bytes(), b'persisted role identity')

    def test_unknown_profile_is_not_adopted_or_deleted(self):
        profile = PlayerProfile(self.data(0))
        profile.root.mkdir(parents=True)
        marker = profile.root/'user-file'
        marker.write_bytes(b'keep')
        with self.assertRaises(EngineError) as error:
            profile.prepare()
        self.assertEqual(error.exception.code, 'profile_conflict')
        self.assertEqual(marker.read_bytes(), b'keep')

    def test_host_version_invalidates_received_packs_but_preserves_identity_and_world(self):
        profile=PlayerProfile(self.data(0));profile.prepare()
        game=profile.root/'game'
        profile.prepare_pack_cache(game,'a'*64)
        cached=game/'packcache/pack/old-dependency.py'
        cached.parent.mkdir(parents=True);cached.write_text('OLD=True')
        identity_file=game/'minecraftpe/clientId.txt'
        identity_file.parent.mkdir();identity_file.write_text('same-player')
        world=game/'minecraftWorlds/world/db/player'
        world.parent.mkdir(parents=True);world.write_text('world-progress')
        profile.prepare_pack_cache(game,'a'*64)
        self.assertTrue(cached.exists())
        profile.prepare_pack_cache(game,'b'*64)
        self.assertFalse(cached.exists())
        self.assertEqual(identity_file.read_text(),'same-player')
        self.assertEqual(world.read_text(),'world-progress')

    def test_cache_invalidation_cannot_escape_profile(self):
        profile=PlayerProfile(self.data(0));profile.prepare()
        marker=self.root/'outside/packcache/keep'
        marker.parent.mkdir(parents=True);marker.write_text('keep')
        with self.assertRaises(EngineError):
            profile.prepare_pack_cache(self.root/'outside','a'*64)
        self.assertEqual(marker.read_text(),'keep')

    def test_running_game_keeps_profile_reserved_after_worker_exit(self):
        data = self.data(0)
        profile = PlayerProfile(data)
        with profile.lease():
            profile.prepare()
            data.update(state='failed', game=identity(os.getpid()))
            storage.write(session_path(self.root, data['session'])/'session.json', data)
        with self.assertRaises(EngineError) as error:
            with profile.lease():
                self.fail('live profile must stay reserved')
        self.assertEqual(error.exception.code, 'profile_in_use')

    def test_reused_pid_does_not_reserve_or_terminate_an_unrelated_process(self):
        data = self.data(0)
        profile = PlayerProfile(data)
        with profile.lease():
            profile.prepare()
            data.update(state='failed', game=identity(os.getpid()))
            storage.write(session_path(self.root, data['session'])/'session.json', data)
        replacement = Mock()
        replacement.create_time.return_value = data['game']['created_at'] + 100
        with patch('mcpywrap.mcstudio.processes.psutil.Process', return_value=replacement):
            with profile.lease():
                pass
        replacement.terminate.assert_not_called()

    def test_unreadable_process_identity_keeps_its_reservation(self):
        import psutil
        data = self.data(0)
        profile = PlayerProfile(data)
        with profile.lease():
            profile.prepare()
            data.update(state='failed', game=identity(os.getpid()))
            storage.write(session_path(self.root, data['session'])/'session.json', data)
        with patch('mcpywrap.mcstudio.processes.psutil.Process', side_effect=psutil.AccessDenied), \
                self.assertRaises(EngineError) as error:
            with profile.lease():
                self.fail('unreadable identity is not proof of exit')
        self.assertEqual(error.exception.code, 'recovery_required')

    @unittest.skipUnless(os.name == 'nt', 'Windows known-folder API')
    def test_child_known_folders_are_private_and_parent_environment_is_unchanged(self):
        profile = PlayerProfile(self.data(0))
        profile.prepare()
        windows = self.windows_profile(profile)
        source = self.root/'source-appdata'
        options = source/'MinecraftPE_Netease/minecraftpe/options.txt'
        options.parent.mkdir(parents=True)
        options.write_text('gfx_viewdistance:128\nkeyboard_type_0_key.forward:87\nlast_xuid:private\n', encoding='utf-8')
        with patch.dict(os.environ, APPDATA=str(source)):
            before = dict(os.environ)
            environment = profile.windows_environment()
            self.assertEqual(dict(os.environ), before)
        self.assertEqual(environment['USERPROFILE'], str(windows))
        self.assertEqual(len(windows.parts), 3)
        target = Path(environment['APPDATA'])/'MinecraftPE_Netease/minecraftpe/options.txt'
        self.assertEqual(target.read_text(encoding='utf-8'), 'gfx_viewdistance:128\nkeyboard_type_0_key.forward:87\n')
        self.assertIn('private', options.read_text(encoding='utf-8'))
        self.assertFalse((target.parent/'clientId.txt').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows profile layout')
    def test_migration_preserves_identity_and_does_not_recopy_stale_data(self):
        profile = PlayerProfile(self.data(0)); profile.prepare()
        old = profile.root/'AppData/Roaming/MinecraftPE_Netease/minecraftpe/clientId.txt'
        old.parent.mkdir(parents=True); old.write_bytes(b'original-player')
        windows = self.windows_profile(profile)
        new = windows/old.relative_to(profile.root)
        self.assertEqual(new.read_bytes(), b'original-player')
        self.assertEqual(old.read_bytes(), b'original-player')
        new.write_bytes(b'updated-player')
        self.assertEqual(profile.windows_directory(), windows)
        self.assertEqual(new.read_bytes(), b'updated-player')
        second = PlayerProfile(self.data(1)); second.prepare()
        self.assertNotEqual(self.windows_profile(second), windows)
        game = windows/'AppData/Roaming/MinecraftPE_Netease'
        profile.prepare_pack_cache(game, 'a'*64)
        cache = game/'packcache/old.py'; cache.parent.mkdir(); cache.write_text('old')
        profile.prepare_pack_cache(game, 'b'*64)
        self.assertFalse(cache.exists())
        self.assertEqual(new.read_bytes(), b'updated-player')

    @unittest.skipUnless(os.name == 'nt', 'Windows profile layout')
    def test_migrated_profile_missing_or_replaced_never_resets_identity(self):
        profile = PlayerProfile(self.data(0)); profile.prepare()
        windows = self.windows_profile(profile)
        backup = windows.with_name(windows.name+'.test-backup')
        windows.rename(backup)
        try:
            with self.assertRaises(EngineError) as error:
                profile.windows_directory()
            self.assertEqual(error.exception.code, 'recovery_required')
            self.assertFalse(windows.exists())
        finally:
            backup.rename(windows)
        marker = windows/'.mcpy-owner.json'
        storage.write(marker, {'owner': 'someone-else'})
        try:
            with self.assertRaises(EngineError) as error:
                profile.windows_directory()
            self.assertEqual(error.exception.code, 'profile_conflict')
            self.assertEqual(storage.read(marker), {'owner': 'someone-else'})
        finally:
            storage.write(marker, profile.owner)


if __name__ == '__main__':
    unittest.main()

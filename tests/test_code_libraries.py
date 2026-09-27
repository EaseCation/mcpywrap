"""用真实本地 Git 仓库验证代码库恢复、隔离与产物保护。"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from mcpywrap.code_libraries import sync_libraries, resolve_libraries, LOCK_FILE
from mcpywrap.dependencies import DependencyError, read_project, write_project
from mcpywrap.builders.project_builder import AddonProjectBuilder
from mcpywrap.builders.watcher import ProjectWatcher
from test_local_dependencies import addon


class CodeLibraries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mcpy-library-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'upstream'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        (self.repo / 'Scripts/Library').mkdir(parents=True)
        (self.repo / 'Scripts/Library/__init__.py').write_text('VERSION = 1\n')
        (self.repo / 'Scripts/Library/old.py').write_text('OLD = True\n')
        (self.repo / 'LICENSE').write_text('Test license\n')
        self.commit()
        self.main = addon(self.root, 'main', configured=True)
        config = read_project(self.main)
        self.entry = dict(name='library', git=self.repo.as_uri(), rev=self.git('rev-parse', 'HEAD'),
                          subdir='Scripts/Library', target='MyMod/Library')
        config['tool']['mcpywrap']['code_libraries'] = [self.entry]
        write_project(self.main, config)
        self.out = self.main / 'build'

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], stderr=subprocess.STDOUT).decode().strip()

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')

    def build(self):
        ok, error = AddonProjectBuilder(self.main, self.out).build()
        self.assertTrue(ok, error)

    def test_missing_cache_sync_repeated_restore_and_license(self):
        self.assertFalse(AddonProjectBuilder(self.main, self.out).build()[0])
        sync_libraries(self.main)
        lock = (self.main / LOCK_FILE).read_bytes()
        sync_libraries(self.main)
        self.assertEqual(lock, (self.main / LOCK_FILE).read_bytes())
        shutil.rmtree(self.main / '.mcpy')
        sync_libraries(self.main)
        self.assertEqual(lock, (self.main / LOCK_FILE).read_bytes())
        self.build()
        target = self.out / 'behavior_pack/MyMod/Library'
        self.assertTrue((target / 'old.py').is_file())
        self.assertEqual((target / 'MCPY_UPSTREAM_LICENSE').read_text(), 'Test license\n')
        self.assertFalse((self.main / 'behavior_pack/MyMod/Library').exists())

    def test_upgrade_rollback_and_removal_do_not_mix_versions(self):
        sync_libraries(self.main)
        self.build()
        (self.repo / 'Scripts/Library/old.py').unlink()
        (self.repo / 'Scripts/Library/new.py').write_text('NEW = True\n')
        self.commit()
        config = read_project(self.main)
        config['tool']['mcpywrap']['code_libraries'][0]['rev'] = self.git('rev-parse', 'HEAD')
        write_project(self.main, config)
        self.assertFalse(AddonProjectBuilder(self.main, self.out).build()[0])
        self.assertTrue((self.out / 'behavior_pack/MyMod/Library/old.py').exists())
        sync_libraries(self.main)
        self.build()
        self.assertFalse((self.out / 'behavior_pack/MyMod/Library/old.py').exists())
        config['tool']['mcpywrap']['code_libraries'] = [self.entry]
        write_project(self.main, config)
        sync_libraries(self.main)
        self.build()
        self.assertFalse((self.out / 'behavior_pack/MyMod/Library/new.py').exists())
        config['tool']['mcpywrap']['code_libraries'] = []
        write_project(self.main, config)
        sync_libraries(self.main)
        self.build()
        self.assertFalse((self.out / 'behavior_pack/MyMod/Library').exists())

    def test_tamper_failed_fetch_and_handwritten_conflicts_preserve_output(self):
        sync_libraries(self.main)
        self.build()
        before = (self.out / 'behavior_pack/MyMod/Library/old.py').read_bytes()
        cache = resolve_libraries(self.main)[0]['source']
        (cache / 'old.py').write_text('tampered')
        with self.assertRaises(DependencyError):
            resolve_libraries(self.main)
        self.assertFalse(AddonProjectBuilder(self.main, self.out).build()[0])
        self.assertEqual(before, (self.out / 'behavior_pack/MyMod/Library/old.py').read_bytes())
        shutil.rmtree(cache)
        sync_libraries(self.main)
        own = self.main / 'behavior_pack/MyMod/Library'
        own.mkdir(parents=True)
        self.assertFalse(AddonProjectBuilder(self.main, self.out).build()[0])
        own.rmdir()
        config = read_project(self.main)
        config['tool']['mcpywrap']['code_libraries'][0]['rev'] = 'f' * 40
        write_project(self.main, config)
        lock = (self.main / LOCK_FILE).read_bytes()
        with self.assertRaises(DependencyError):
            sync_libraries(self.main)
        self.assertEqual(lock, (self.main / LOCK_FILE).read_bytes())
        self.assertEqual(before, (self.out / 'behavior_pack/MyMod/Library/old.py').read_bytes())

    def test_bad_merge_preserves_existing_build(self):
        # 既有bug：目标在JSON合并失败前被清空；现在先完整组装再发布。
        sync_libraries(self.main)
        self.build()
        before = (self.out / 'behavior_pack/MyMod/Library/old.py').read_bytes()
        dependency = addon(self.root, 'dep')
        for project, value in [(dependency, '{"texture_data": {}}'), (self.main, '{invalid')]:
            (project / 'resource_pack/terrain_texture.json').write_text(value)
        config = read_project(self.main)
        config['tool']['mcpywrap']['local_dependencies'] = ['../dep']
        write_project(self.main, config)
        self.assertFalse(AddonProjectBuilder(self.main, self.out).build()[0])
        self.assertEqual(before, (self.out / 'behavior_pack/MyMod/Library/old.py').read_bytes())

    def test_paths_overlap_and_two_mod_scopes(self):
        config = read_project(self.main)
        for target in ['../outside', '/absolute', 'C:/outside', 'MyMod/../Library', 'MyMod/Library.', 'MyMod/NUL']:
            config['tool']['mcpywrap']['code_libraries'][0]['target'] = target
            write_project(self.main, config)
            with self.assertRaises(DependencyError):
                sync_libraries(self.main)
        first = dict(self.entry)
        second = dict(first, name='other', target='OtherMod/Library')
        config['tool']['mcpywrap']['code_libraries'] = [first, second]
        write_project(self.main, config)
        sync_libraries(self.main)
        self.build()
        self.assertTrue((self.out / 'behavior_pack/OtherMod/Library/old.py').exists())
        second['target'] = 'MyMod/Library/Nested'
        write_project(self.main, config)
        with self.assertRaises(DependencyError):
            sync_libraries(self.main)

    def test_run_and_dev_share_assembly(self):
        from mcpywrap.commands.run_cmd import _setup_dependencies
        sync_libraries(self.main)
        self.build()
        expected = (self.out / 'behavior_pack/MyMod/Library/old.py').read_bytes()
        packs = _setup_dependencies('main', str(self.main), raise_errors=True)
        self.assertEqual(len(packs), 1)
        self.assertEqual(expected, (Path(packs[0].behavior_pack_dir) / 'MyMod/Library/old.py').read_bytes())
        watcher = ProjectWatcher(self.main, self.out)
        watcher.setup_from_config('main')
        (self.main / 'behavior_pack/new.py').write_text('new = True\n')
        watcher.rebuild('behavior', 'new.py')
        self.assertTrue((self.out / 'behavior_pack/new.py').exists())
        self.assertEqual(expected, (self.out / 'behavior_pack/MyMod/Library/old.py').read_bytes())

    def test_map_runtime_does_not_reinclude_transitive_addons(self):
        from mcpywrap.commands.run_cmd import _setup_dependencies
        child = addon(self.root, 'child', configured=True)
        config = read_project(self.main)
        config['tool']['mcpywrap']['local_dependencies'] = ['../child']
        write_project(self.main, config)
        sync_libraries(self.main)
        world = self.root / 'world'
        world.mkdir()
        write_project(world, {'project': {'name': 'world'}, 'tool': {'mcpywrap': {
            'project_type': 'map', 'local_dependencies': ['../main']}}})
        packs = _setup_dependencies('world', str(world), raise_errors=True)
        self.assertEqual(len(packs), 2)
        # main独立组装，不把child的资源也再次注入运行时。
        (child / 'behavior_pack/child-only.py').write_text('child = True')
        packs = _setup_dependencies('world', str(world), raise_errors=True)
        # Windows CI 的 TEMP 可使用 RUNNER~1 短路径，解析器返回长路径。
        # 按目录身份选择，避免把 child 自己当作待验证的 main。
        main_pack = next(p for p in packs if not Path(p.path).samefile(child))
        child_pack = next(p for p in packs if Path(p.path).samefile(child))
        self.assertTrue((Path(child_pack.behavior_pack_dir) / 'child-only.py').exists())
        self.assertTrue((Path(main_pack.behavior_pack_dir) / 'MyMod/Library/old.py').exists())
        self.assertFalse((Path(main_pack.behavior_pack_dir) / 'child-only.py').exists())

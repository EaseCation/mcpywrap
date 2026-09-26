"""验证真实构建后的分发内容及打包失败时的产物保护。"""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from mcpywrap.cli import cli
from mcpywrap.dependencies import read_project, write_project
from test_local_dependencies import addon, cwd, FakeDist


class Packaging(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mcpy-package-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.main = addon(self.root, 'demo', configured=True)
        self.dep = addon(self.root, 'shared')
        (self.dep / 'behavior_pack/dependency.txt').write_text('dependency')
        self.runner = CliRunner()

    def invoke(self, source=None, args=()):
        source = source or self.main
        with cwd(source):
            result = self.runner.invoke(cli, ['package', *args])
            self.assertEqual(Path.cwd(), source)
        if (source / 'dist').exists():
            self.assertFalse(list((source / 'dist').glob('_temp_package_*')))
        return result

    def contents(self, source=None, filename='demo-0.1.0.zip'):
        with zipfile.ZipFile((source or self.main) / 'dist' / filename) as archive:
            self.assertIsNone(archive.testzip())
            names = archive.namelist()
            self.assertTrue(all(not n.startswith('/') and '\\' not in n for n in names))
            return {name: archive.read(name) for name in names}

    def test_addon_custom_directories_and_mixed_dependencies(self):
        (self.main / 'behavior_pack').rename(self.main / 'BehaviorPack_demo')
        (self.main / 'resource_pack').rename(self.main / 'resource_pack_demo')
        config = read_project(self.main)
        config['project']['dependencies'] = ['shared>=1']
        config['tool']['mcpywrap'] = {'local_dependencies': ['../shared']}
        write_project(self.main, config)
        with patch('mcpywrap.builders.dependency_manager.metadata.distribution', return_value=FakeDist(self.dep)):
            result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        files = self.contents()
        self.assertIn(b"'demo'", files['demo_bp/marker.py'])
        self.assertEqual(files['demo_bp/dependency.txt'], b'dependency')
        self.assertEqual(files['demo_bp/manifest.json'], (self.main / 'BehaviorPack_demo/manifest.json').read_bytes())
        self.assertIn('demo_rp/manifest.json', files)
        self.assertFalse((self.main / 'build').exists())

    def test_single_pack(self):
        import shutil
        shutil.rmtree(self.main / 'behavior_pack')
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual({name.split('/')[0] for name in self.contents()}, {'demo_rp'})

    def test_map_layout_dependencies_and_merge(self):
        world = self.root / 'world'
        world.mkdir()
        (world / 'level.dat').write_bytes(b'world-data')
        (world / 'levelname.txt').write_text('world')
        (world / 'db/empty/nested').mkdir(parents=True)
        (world / 'db/data').write_bytes(b'database')
        own = addon(world / 'staging', 'own')
        (world / 'behavior_packs').mkdir()
        (world / 'resource_packs').mkdir()
        (own / 'behavior_pack').rename(world / 'behavior_packs/own')
        (own / 'resource_pack').rename(world / 'resource_packs/own')
        write_project(world, {'project': {'name': 'world', 'version': '2.3.4'},
                             'tool': {'mcpywrap': {'project_type': 'map', 'local_dependencies': ['../shared']}}})
        for args in ((), ('--merge',), ('-m',)):
            with self.subTest(args=args):
                result = self.invoke(world, args)
                self.assertEqual(result.exit_code, 0, result.output)
                files = self.contents(world, 'world-2.3.4.zip')
                self.assertEqual(files['level.dat'], b'world-data')
                self.assertEqual(files['db/data'], b'database')
                self.assertIn('db/empty/nested/', files)
                self.assertNotIn('/', files)
                self.assertTrue(any(n.endswith('/dependency.txt') for n in files))
                self.assertIn(b"'own'", files['behavior_packs/own/marker.py'])
                for kind in ('behavior', 'resource'):
                    packs = json.loads(files[f'world_{kind}_packs.json'])
                    self.assertEqual(len(packs), 1 if args else 2)

    def test_repeat_build_replaces_without_stale_files(self):
        extra = self.main / 'resource_pack/removed.txt'
        extra.write_text('old')
        self.assertEqual(self.invoke().exit_code, 0)
        self.assertIn('demo_rp/removed.txt', self.contents())
        extra.unlink()
        self.assertEqual(self.invoke().exit_code, 0)
        self.assertNotIn('demo_rp/removed.txt', self.contents())

    def test_failed_dependency_preserves_previous_zip(self):
        self.assertEqual(self.invoke().exit_code, 0)
        archive = self.main / 'dist/demo-0.1.0.zip'
        previous = archive.read_bytes()
        config = read_project(self.main)
        config['tool']['mcpywrap']['local_dependencies'] = ['../missing']
        write_project(self.main, config)
        result = self.invoke()
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('构建失败', result.output)
        self.assertEqual(archive.read_bytes(), previous)

    def test_zip_failure_preserves_previous_zip(self):
        self.assertEqual(self.invoke().exit_code, 0)
        archive = self.main / 'dist/demo-0.1.0.zip'
        previous = archive.read_bytes()
        with patch('zipfile.ZipFile.write', side_effect=OSError('disk full')):
            result = self.invoke()
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('disk full', result.output)
        self.assertEqual(archive.read_bytes(), previous)

    def test_no_config_invalid_config_and_unsupported_type(self):
        config_path = self.main / 'pyproject.toml'
        for content in (None, '[broken', 'project = "invalid"',
                        '[tool.mcpywrap]\nproject_type = "apollo"'):
            with self.subTest(content=content):
                if content is None:
                    config_path.unlink()
                else:
                    config_path.write_text(content)
                result = self.invoke()
                self.assertNotEqual(result.exit_code, 0)
                self.assertFalse((self.main / 'dist').exists())

    def test_filename_cannot_escape_dist(self):
        config = read_project(self.main)
        for field in ('name', 'version'):
            with self.subTest(field=field):
                modified = dict(config, project=dict(config['project'], **{field: '../../outside'}))
                write_project(self.main, modified)
                self.assertNotEqual(self.invoke().exit_code, 0)
                self.assertFalse((self.main / 'dist').exists())

    def test_two_projects_in_same_process_and_version_default(self):
        self.assertEqual(self.invoke().exit_code, 0)
        other = addon(self.root, 'other', configured=True)
        config = read_project(other)
        del config['project']['version']
        write_project(other, config)
        result = self.invoke(other)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('other_bp/manifest.json', self.contents(other, 'other-0.1.0.zip'))


if __name__ == '__main__':
    unittest.main()

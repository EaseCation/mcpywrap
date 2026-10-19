"""通过公开 CLI、真实临时源码与子进程验证依赖消费者准备。"""
import datetime
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from click.testing import CliRunner

from mcpywrap.cli import cli
from mcpywrap.consumer_prepare import PreparationPlan, source_digest
from mcpywrap.dependencies import read_project, write_project
from mcpywrap.prepare_environment import interpreter_path
from mcpywrap.project_scripts import before, project_lock, startup_hooks, startup_options, ScriptError
from mcpywrap.runtime.deployment import Deployment
from test_runtime_deployment import fixture


class ConsumerPrepareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = fixture(self.root, '玩法 project')
        self.cache = patch.dict(os.environ, {'MCPY_CACHE_DIR': str(self.root / 'cache')})
        self.cache.start()
        self.addCleanup(self.cache.stop)
        config = read_project(self.project)
        config['tool']['mcpywrap'].update(target_dir='build', prepare={'python': sys.executable})
        config['tool']['sample'] = {'message': 'hello'}
        write_project(self.project, config)

    def invoke(self, *args):
        options = {'mix_stderr': False} if 'mix_stderr' in inspect.signature(CliRunner).parameters else {}
        result = CliRunner(**options).invoke(cli, ['--local', '--project', str(self.project), *args])
        self.assertTrue(result.stdout.strip(), result.output)
        return result, json.loads(result.stdout)

    def success(self, *args):
        result, data = self.invoke(*args, '--json')
        self.assertEqual(result.exit_code, 0, result.output)
        return data

    def provider(self, name='framework', *, script=None, **spec):
        path = fixture(self.root, name)
        tools = path / 'build_tools'
        tools.mkdir()
        source = """import json, os, sys
from pathlib import Path
from helper import VALUE
root = Path(os.environ['MCPY_PROJECT_ROOT'])
config = json.loads(Path(os.environ['MCPY_CONSUMER_CONFIG']).read_text(encoding='utf-8'))
record = dict(config=config, helper=VALUE, cwd=str(Path.cwd()), dependency=os.environ['MCPY_DEPENDENCY_ROOT'],
              python=sys.executable, event=os.environ['MCPY_EVENT'], operation=os.environ['MCPY_OPERATION'])
(root/'behavior_pack'/'generated-NAME.json').write_text(json.dumps(record), encoding='utf-8')
with (root/'calls').open('a', encoding='utf-8') as stream: stream.write('NAME\\n')
""".replace('NAME', name)
        (tools / 'prepare.py').write_text(script if script is not None else source, encoding='utf-8')
        (tools / 'helper.py').write_text('VALUE = 42\n', encoding='utf-8')
        config = read_project(path)
        config['tool']['mcpywrap']['consumer_prepare'] = dict(
            format=1, python='build_tools/prepare.py', requires_python='>=3.9', **spec)
        write_project(path, config)
        return path

    def depend(self, *paths, project=None):
        project = project or self.project
        config = read_project(project)
        config['tool']['mcpywrap']['local_dependencies'] = [os.path.relpath(path, project) for path in paths]
        write_project(project, config)

    def configure(self, **settings):
        config = read_project(self.project)
        config['tool']['mcpywrap'].update(settings)
        write_project(self.project, config)

    def schema(self, provider):
        path = provider / 'build_tools/schema.json'
        path.write_text(json.dumps({'$schema': 'https://json-schema.org/draft/2020-12/schema',
            'type': 'object', 'required': ['message'], 'properties': {'message': {'type': 'string', 'enum': ['hello', 'new']}},
            'additionalProperties': False}), encoding='utf-8')
        config = read_project(provider)
        config['tool']['mcpywrap']['consumer_prepare'].update(config_key='tool.sample', config_schema='build_tools/schema.json')
        write_project(provider, config)
        return path

    def calls(self):
        path = self.project / 'calls'
        return path.read_text(encoding='utf-8').splitlines() if path.exists() else []

    def git_provider(self, **spec):
        path = self.provider(**spec)
        (path / 'runtime').mkdir()
        (path / 'runtime/__init__.py').write_text('VALUE = 1\n')
        config = read_project(path)
        config['tool']['mcpywrap']['export'] = {'kind': 'code', 'path': 'runtime', 'target': 'Shared/Library'}
        write_project(path, config)
        for args in (['init', '-q'], ['add', '.'],
                     ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', '-c', 'core.hooksPath=', 'commit', '-qm', 'fixture']):
            subprocess.run(['git', '-C', str(path), *args], check=True, capture_output=True)
        rev = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
        self.success('add', '--git', path.as_uri(), '--ref', rev, '--dep-name', 'framework')
        return path, rev

    def test_root_without_hooks_build_and_package_prepare_once(self):
        provider = self.provider(config_key='tool.sample')
        self.depend(provider)
        original = source_digest(provider)
        build = self.success('build')
        self.assertEqual(self.calls(), ['framework'])
        self.assertEqual(build['scripts'][0]['kind'], 'consumer_prepare')
        generated = json.loads((self.project/'build/behavior_pack/generated-framework.json').read_text())
        self.assertEqual(generated['config'], {'message': 'hello'})
        self.assertEqual(Path(generated['dependency']), provider)
        self.assertEqual(Path(generated['cwd']), self.project)
        archive = self.success('package')
        self.assertEqual(self.calls(), ['framework', 'framework'])
        with zipfile.ZipFile(archive['artifact']) as package:
            names = package.namelist()
            self.assertTrue(any(name.endswith('/generated-framework.json') for name in names))
            self.assertFalse(any('build_tools/' in name or '.venv/' in name for name in names))
        self.assertEqual(source_digest(provider), original)
        self.assertFalse(list(provider.rglob('__pycache__')))

    def test_root_hooks_run_before_provider_but_dependency_hooks_never_run(self):
        provider = self.provider(script="from pathlib import Path\nassert Path('input.txt').read_text() == 'fresh'\nPath('calls').write_text('provider\\n')\n")
        config = read_project(provider)
        config['tool']['mcpywrap'].update(scripts={'forbidden': {'cmd': [sys.executable, '-c', 'raise SystemExit(99)']}},
                                         hooks={'before_build': ['forbidden']})
        write_project(provider, config)
        self.depend(provider)
        self.configure(scripts={'input': {'cmd': [sys.executable, '-c', "from pathlib import Path;Path('input.txt').write_text('fresh')"]}},
                       hooks={'before_build': ['input']})
        result = self.success('build')
        self.assertEqual([item['kind'] for item in result['scripts']], ['root', 'consumer_prepare'])
        self.assertEqual(self.calls(), ['provider'])

    def test_diamond_transitive_and_direct_reference_override(self):
        shared = self.provider('shared', transitive=True)
        left, right = self.provider('left'), self.provider('right')
        self.depend(shared, project=left)
        self.depend(shared, project=right)
        self.depend(left, right)
        self.success('build')
        self.assertEqual(self.calls()[0], 'shared')
        self.assertEqual(sorted(self.calls()), ['left', 'right', 'shared'])
        config = read_project(shared)
        config['tool']['mcpywrap']['consumer_prepare']['transitive'] = False
        write_project(shared, config)
        (self.project/'calls').unlink()
        plan = self.success('script', 'list', '--effective')
        self.assertEqual(next(p['state'] for p in plan['consumer_prepare'] if p['name'] == 'shared'), 'not_transitive')
        self.success('build')
        self.assertEqual(sorted(self.calls()), ['left', 'right'])
        self.depend(left, right, shared)
        (self.project/'calls').unlink()
        self.success('build')
        self.assertEqual(self.calls()[0], 'shared')

    def test_disabled_provider_requires_no_environment_and_keeps_runtime(self):
        provider = self.provider()
        self.depend(provider)
        self.configure(prepare={'disabled': [{'path': '../framework'}]})
        plan = self.success('script', 'list', '--effective')
        self.assertEqual(plan['consumer_prepare'][0]['state'], 'disabled')
        self.assertEqual(plan['environment']['state'], 'not_required')
        self.success('build')
        self.assertEqual(self.calls(), [])
        self.assertTrue((self.project/'build/behavior_pack/main.py').exists())
        self.assertFalse((self.project/'.venv').exists())

    def test_root_provider_is_not_its_own_consumer(self):
        self.configure(consumer_prepare={'format': 1, 'python': 'missing.py', 'requires_python': '>=3.99'})
        self.success('build')
        self.assertEqual(self.calls(), [])

    def test_schema_and_json_conversion_fail_before_consumption(self):
        provider = self.provider()
        self.schema(provider)
        self.depend(provider)
        for value in ({}, {'message': 1}, {'message': 'hello', 'extra': True},
                      {'message': datetime.date(2025, 1, 1)}, {'message': float('nan')}):
            with self.subTest(value=value):
                config = read_project(self.project)
                config['tool']['sample'] = value
                write_project(self.project, config)
                result, data = self.invoke('build', '--json')
                self.assertNotEqual(result.exit_code, 0, data)
                self.assertIn('tool.sample', data['error'])
                self.assertEqual(self.calls(), [])
                self.assertFalse((self.project/'build').exists())

    def test_schema_internal_refs_arrays_and_external_refs(self):
        provider = self.provider(config_key='tool.sample', config_schema='build_tools/schema.json')
        self.depend(provider)
        path = provider/'build_tools/schema.json'
        schema = {'type': 'object', '$defs': {'values': {'type': 'array', 'minItems': 1, 'items': {'enum': ['x']}}},
                  'properties': {'message': {'$ref': '#/$defs/values'}}, 'required': ['message']}
        path.write_text(json.dumps(schema))
        for value, success in [([], False), (['bad'], False), (['x'], True)]:
            config = read_project(self.project); config['tool']['sample']['message'] = value
            write_project(self.project, config)
            result, data = self.invoke('build', '--json')
            self.assertEqual(result.exit_code == 0, success, data)
        schema['properties']['message'] = {'$ref': 'https://example.invalid/schema'}
        path.write_text(json.dumps(schema))
        result, data = self.invoke('build', '--json')
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('内部引用', data['error'])
        path.write_text('{"type": "made-up"}')
        result, data = self.invoke('build', '--json')
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('config_schema', data['error'])

    def test_duplicate_config_key_fails_before_scripts(self):
        self.depend(self.provider('a', config_key='tool.sample'), self.provider('b', config_key='tool.sample'))
        result, data = self.invoke('build', '--json')
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('多个来源', data['error'])
        self.assertEqual(self.calls(), [])

    def test_read_only_list_and_partial_missing_dependencies(self):
        provider = self.provider()
        self.depend(provider, self.root/'not-restored')
        before_files = {str(p): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        plan = self.success('script', 'list', '--effective')
        self.assertFalse(plan['complete'])
        self.assertEqual(plan['consumer_prepare'][0]['name'], 'framework')
        self.assertEqual(before_files, {str(p): p.read_bytes() for p in self.project.rglob('*') if p.is_file()})
        self.assertFalse((self.project/'.mcpy').exists())
        legacy = self.success('script', 'list')
        self.assertEqual(legacy['scripts'], [])
        self.assertNotIn('consumer_prepare', legacy)

    def test_git_tools_outside_export_and_aliases_execute_once(self):
        repo, rev = self.git_provider(config_key='tool.sample')
        self.success('add', '--git', repo.as_uri(), '--ref', rev, '--dep-name', 'alias', '--target', 'Other/Library')
        from mcpywrap.git_cache import read_snapshot
        from mcpywrap.source_files import digest
        raw = read_snapshot(repo.as_uri(), rev)
        original = digest(raw)
        self.success('package')
        self.assertEqual(self.calls(), ['framework'])
        result = json.loads((self.project/'behavior_pack/generated-framework.json').read_text())
        self.assertEqual(Path(result['dependency']), raw)
        self.assertEqual(digest(raw), original)
        self.assertEqual(len(self.success('script', 'list', '--effective')['consumer_prepare']), 1)

    def test_git_missing_source_requires_sync_without_fetch(self):
        repo, rev = self.git_provider()
        from mcpywrap.git_cache import read_snapshot
        raw = read_snapshot(repo.as_uri(), rev)
        shutil.rmtree(raw)
        with patch('mcpywrap.git_cache.fetch_snapshot', side_effect=AssertionError('must not fetch')):
            plan = self.success('script', 'list', '--effective')
            self.assertFalse(plan['complete'])
            result, data = self.invoke('build', '--json')
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn('sync', data['error'])
        self.assertEqual(self.calls(), [])

    def test_git_provider_cannot_add_cache_files_to_immutable_source(self):
        self.git_provider(script="import os\nfrom pathlib import Path\np=Path(os.environ['MCPY_DEPENDENCY_ROOT'])/'.mcpy'\np.mkdir()\n(p/'cache').write_text('unexpected')\n")
        result, data = self.invoke('build', '--json')
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(data['code'], 'script_config_changed')
        self.assertFalse((self.project/'build').exists())

    def test_two_consumers_leave_source_unchanged(self):
        provider = self.provider()
        self.depend(provider)
        original = source_digest(provider)
        self.success('build')
        other = fixture(self.root, 'other')
        self.depend(provider, project=other)
        self.project = other
        self.configure(target_dir='build', prepare={'python': sys.executable})
        self.success('build')
        self.assertEqual(self.calls(), ['framework'])
        self.assertEqual(source_digest(provider), original)

    def test_sync_creates_environment_without_executing_provider(self):
        self.depend(self.provider())
        self.configure(prepare={})
        result, data = self.invoke('build', '--json')
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(data['code'], 'prepare_environment_unavailable')
        with patch('mcpywrap.prepare_environment.candidates', return_value=[(sys.executable, '.'.join(map(str, sys.version_info[:3])))]):
            synced = self.success('sync')
        self.assertTrue(synced['sources_synced'])
        self.assertTrue(synced['environment']['created'])
        self.assertEqual(self.calls(), [])
        self.assertTrue(interpreter_path(self.project).is_file())
        self.success('build')
        record = json.loads((self.project/'behavior_pack/generated-framework.json').read_text())
        self.assertEqual(Path(record['python']), interpreter_path(self.project))
        self.assertFalse(self.success('sync')['environment']['created'])

    def test_environment_error_does_not_overwrite_existing_venv(self):
        self.depend(self.provider())
        self.configure(prepare={})
        folder = self.project/'.venv'; folder.mkdir()
        (folder/'owned').write_text('keep')
        result, data = self.invoke('sync', '--json')
        self.assertNotEqual(result.exit_code, 0)
        self.assertTrue(data['sources_synced'])
        self.assertFalse(data['environment_ready'])
        self.assertEqual((folder/'owned').read_text(), 'keep')
        self.assertEqual(self.calls(), [])

    def test_unavailable_python_reports_all_requirements(self):
        dep = self.provider()
        config = read_project(dep); config['tool']['mcpywrap']['consumer_prepare']['requires_python'] = '>=3.99'
        write_project(dep, config); self.depend(dep); self.configure(prepare={})
        with patch('mcpywrap.prepare_environment.candidates', return_value=[]):
            result, data = self.invoke('sync', '--json')
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(data['code'], 'prepare_python_unavailable')
        self.assertIn('3.99', str(data['environment']['requirements']))
        self.assertFalse((self.project/'.venv').exists())

    def test_hook_configuration_change_stops_provider(self):
        self.depend(self.provider())
        self.configure(scripts={'change': {'cmd': [sys.executable, '-c', "from pathlib import Path;p=Path('pyproject.toml');p.write_text(p.read_text()+'\\n# changed')"]}},
                       hooks={'before_build': ['change']})
        result, data = self.invoke('build', '--json')
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(data['code'], 'script_config_changed')
        self.assertEqual(self.calls(), [])

    def test_auxiliary_tool_change_stops_consumption(self):
        provider = self.provider()
        self.depend(provider)
        self.configure(scripts={'change': {'cmd': [sys.executable, '-c',
                       'from pathlib import Path;Path(%r).write_text("VALUE=43")' % str(provider/'build_tools/helper.py')]}},
                       hooks={'before_build': ['change']})
        result, data = self.invoke('build', '--json')
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(data['code'], 'script_config_changed')
        self.assertEqual(self.calls(), [])

    def test_failure_and_timeout_stop_next_provider_and_preserve_package(self):
        first = self.provider('first')
        later = self.provider('later')
        self.depend(first, project=later); self.depend(later, first)
        archive = Path(self.success('package')['artifact']); original = archive.read_bytes()
        (self.project/'calls').unlink()
        (first/'build_tools/prepare.py').write_text('raise SystemExit(7)\n')
        result, data = self.invoke('package', '--json')
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(data['script_exit_code'], 7)
        self.assertEqual(archive.read_bytes(), original)
        self.assertEqual(self.calls(), [])
        (first/'build_tools/prepare.py').write_text('import time;time.sleep(60)\n')
        config = read_project(first); config['tool']['mcpywrap']['consumer_prepare']['timeout'] = .2
        write_project(first, config)
        result, data = self.invoke('build', '--json')
        self.assertEqual(data['code'], 'script_timeout')
        self.assertEqual(self.calls(), [])

    def test_cancelled_consumer_never_reaches_consumption(self):
        self.depend(self.provider(script='import time;time.sleep(60)\n'))
        deadline = time.monotonic() + .5
        with self.assertRaises(ScriptError) as caught:
            with before(self.project, 'before_build', cancel=lambda: time.monotonic() > deadline):
                self.fail('cancelled preparation was consumed')
        self.assertEqual(caught.exception.code, 'script_cancelled')

    def test_startup_plan_is_pinned_and_reused_by_deployment(self):
        provider = self.provider(); self.depend(provider)
        sid = 'c' * 32
        data = dict(project=str(self.project), session=sid, config_path=str(self.project/'.runtime/world.json'),
                    **startup_options(self.project))
        self.assertGreater(data['script_budget'], 120)
        deployment = Deployment(self.project)
        with project_lock(self.project), deployment.lock():
            startup_hooks(data, deployment)
            with patch('mcpywrap.runtime.deployment.DependencyService.resolve', side_effect=AssertionError('resolved twice')):
                deployment.prepare(session=sid)
                deployment.commit()
        self.assertEqual(self.calls(), ['framework'])
        self.assertTrue((deployment.target/'behavior_pack/generated-framework.json').is_file())
        (provider/'build_tools/helper.py').write_text('VALUE = 99\n')
        with self.assertRaises(ScriptError) as caught:
            startup_hooks(data, Deployment(self.project))
        self.assertEqual(caught.exception.code, 'script_config_changed')
        self.assertEqual(self.calls(), ['framework'])

    def test_no_provider_sync_does_not_create_environment(self):
        self.configure(prepare={})
        self.assertEqual(self.success('sync')['environment']['state'], 'not_required')
        self.assertFalse((self.project/'.venv').exists())

    def test_entry_escape_and_missing_are_not_silently_ignored(self):
        provider = self.provider(); self.depend(provider)
        for entry in ('../escape.py', 'missing.py'):
            config = read_project(provider); config['tool']['mcpywrap']['consumer_prepare']['python'] = entry
            write_project(provider, config)
            result, data = self.invoke('build', '--json')
            self.assertNotEqual(result.exit_code, 0, data)
            self.assertEqual(self.calls(), [])

    def test_standalone_skill_example_local_and_git(self):
        skill = self.root / 'standalone-skill'
        shutil.copytree(Path(__file__).resolve().parents[1] / 'skills/mcpywrap', skill,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        originals = {str(p.relative_to(skill)): p.read_bytes() for p in skill.rglob('*') if p.is_file()}
        examples = skill / 'assets/consumer-prepare'
        copied = self.root / 'example'
        shutil.copytree(examples, copied)
        self.project = copied/'game'
        plan = self.success('script', 'list', '--effective')
        self.assertTrue(plan['complete'])
        self.assertFalse(plan['ready'])
        self.assertEqual(plan['environment']['state'], 'missing')
        self.assertFalse((self.project/'.mcpy').exists())
        self.configure(prepare={'python': sys.executable})
        config = read_project(self.project)
        del config['tool']['catalog']
        write_project(self.project, config)
        synced = self.success('sync')
        self.assertEqual(synced['environment']['state'], 'ready')
        self.assertFalse(synced['preparation']['ready'])
        import tomli
        example = synced['preparation']['consumer_prepare'][0]['example']
        config = read_project(self.project)
        config['tool'].update(tomli.loads(example)['tool'])
        write_project(self.project, config)
        self.success('sync')
        first = self.success('package')
        with zipfile.ZipFile(first['artifact']) as archive:
            self.assertEqual(json.loads(archive.read('catalog-game_bp/generated/catalog.json')), {'apple': 5, 'carrot': 3})
            self.assertIn('catalog-game_bp/CatalogRuntime/__init__.py', archive.namelist())
            self.assertFalse(any('build_tools' in path or 'data/items.json' in path for path in archive.namelist()))
        (self.project/'data/items.json').write_text('{"new_item": 9}')
        self.success('build')
        self.assertEqual(json.loads((self.project/'build/behavior_pack/generated/catalog.json').read_text()), {'new_item': 9})
        generated = self.project/'behavior_pack/generated/catalog.json'
        generated.write_text('{"manual": 1}')
        result, data = self.invoke('build', '--json')
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('手动编辑', Path(data['script_log']).read_text(encoding='utf-8'))
        self.assertEqual(json.loads(generated.read_text()), {'manual': 1})
        # 同一个可移植模板也验证 Git Addon 发布者，不依赖仓库外层示例。
        repo = copied/'framework'
        for arguments in (['init', '-q'], ['add', '.'],
                          ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                           '-c', 'core.hooksPath=', 'commit', '-qm', 'skill template']):
            subprocess.run(['git', '-C', str(repo), *arguments], check=True, capture_output=True)
        rev = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
        self.project = copied/'git-game'
        shutil.copytree(examples/'game', self.project)
        self.configure(local_dependencies=[], prepare={'python': sys.executable})
        self.success('add', '--git', repo.as_uri(), '--ref', rev, '--dep-name', 'catalog')
        self.success('sync')
        artifact = self.success('package')['artifact']
        with zipfile.ZipFile(artifact) as archive:
            self.assertEqual(json.loads(archive.read('catalog-game_bp/generated/catalog.json')), {'apple': 5, 'carrot': 3})
            self.assertIn('catalog-game_bp/CatalogRuntime/__init__.py', archive.namelist())
        self.assertEqual(originals, {str(p.relative_to(skill)): p.read_bytes() for p in skill.rglob('*') if p.is_file()})

    def test_git_disabled_selector_matches_all_aliases(self):
        repo, rev = self.git_provider()
        self.success('add', '--git', repo.as_uri(), '--ref', rev, '--dep-name', 'alias', '--target', 'Other/Library')
        self.configure(prepare={'disabled': [{'git': repo.as_uri()}]})
        result = self.success('script', 'list', '--effective')
        self.assertEqual(len(result['consumer_prepare']), 1)
        self.assertEqual(result['consumer_prepare'][0]['state'], 'disabled')
        self.success('package')
        self.assertEqual(self.calls(), [])

    def test_git_transitive_source_uses_original_child_descriptor(self):
        repo, rev = self.git_provider()
        child = self.provider('child', transitive=True)
        shutil.move(str(child), str(repo/'child'))
        config = read_project(repo)
        config['tool']['mcpywrap']['local_dependencies'] = ['child']
        write_project(repo, config)
        subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                        '-c', 'core.hooksPath=', 'commit', '-qm', 'child'], check=True, capture_output=True)
        rev = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
        self.success('add', '--git', repo.as_uri(), '--ref', rev, '--dep-name', 'framework')
        self.success('build')
        self.assertEqual(self.calls(), ['child', 'framework'])
        generated = json.loads((self.project/'behavior_pack/generated-child.json').read_text())
        from mcpywrap.git_cache import read_snapshot
        self.assertEqual(Path(generated['dependency']), read_snapshot(repo.as_uri(), rev)/'child')

    def test_low_level_builder_does_not_execute_consumers(self):
        self.depend(self.provider())
        from mcpywrap.builders.project_builder import AddonProjectBuilder
        success, error = AddonProjectBuilder(self.project, self.project/'build').build()
        self.assertTrue(success, error)
        self.assertEqual(self.calls(), [])

    def test_later_provider_stops_after_identity_mutation(self):
        first = self.provider('first', script="from pathlib import Path\np=Path('behavior_pack/manifest.json');p.write_text(p.read_text()+'\\n')\n")
        later = self.provider('later')
        self.depend(first, project=later); self.depend(first, later)
        result, data = self.invoke('build', '--json')
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(data['code'], 'script_config_changed')
        self.assertEqual(self.calls(), [])

    def test_version_mismatch_does_not_run_root_hooks(self):
        provider = self.provider()
        config = read_project(provider); config['tool']['mcpywrap']['consumer_prepare']['requires_python'] = '>=3.99'
        write_project(provider, config); self.depend(provider)
        self.configure(scripts={'root': {'cmd': [sys.executable, '-c', "from pathlib import Path;Path('calls').touch()"]}},
                       hooks={'before_build': ['root']})
        result, data = self.invoke('build', '--json')
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(data['code'], 'prepare_environment_unavailable')
        self.assertFalse((self.project/'calls').exists())


if __name__ == '__main__':
    unittest.main()

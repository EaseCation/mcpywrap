"""Bundled/unbundled graphs use real Addons, Git snapshots, ZIPs and the shared Qt service."""
import concurrent.futures
import json
import inspect
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch, Mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from click.testing import CliRunner
from mcpywrap_core.cli import cli
from mcpywrap_core.api import Core
from mcpywrap_core.dependencies import DependencyService, DependencyError, declarations, read_project, write_project
from mcpywrap_core.builders.project_builder import AddonProjectBuilder
from mcpywrap_core.builders.output_lock import output_lease
from mcpywrap_core.builders.watcher import ProjectWatcher
from mcpywrap_core.consumer_prepare import PreparationPlan
from mcpywrap_core.git_projects import resolve_projects, LOCK_FILE
from mcpywrap_core.project_dependencies import GitDependencyService
from mcpywrap_core.runtime.deployment import runtime_builder
from test_local_dependencies import addon


def cli_runner():
    options = {'mix_stderr': False} if 'mix_stderr' in inspect.signature(CliRunner).parameters else {}
    return CliRunner(**options)


class UnbundledDependencies(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mcpy-unbundled-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.env = patch.dict(os.environ, {'MCPY_CACHE_DIR': str(self.root/'cache')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.main = addon(self.root, 'game', configured=True)
        self.service = DependencyService(self.main)

    def helper(self, name, **kwargs):
        path = addon(self.root, name, configured=True, **kwargs)
        (path/'behavior_pack/marker.py').unlink()
        (path/'behavior_pack'/ (name + '.py')).write_text('VALUE = 1\n')
        return path

    def config(self, directory=None, **settings):
        directory = directory or self.main
        config = read_project(directory)
        config['tool']['mcpywrap'].update(settings)
        write_project(directory, config)

    def invoke(self, *args):
        return cli_runner().invoke(cli, ['--local', '--project', str(self.main), '--non-interactive', *args])

    def commit(self, repo):
        for args in [('init', '-q'), ('config', 'user.name', 'Scopes'), ('config', 'user.email', 'test@example.invalid'), ('add', '.'), ('commit', '-qm', 'fixture')]:
            subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)
        return subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD']).decode().strip()

    def git_helper(self, name):
        repo = self.root/name
        (repo/'src').mkdir(parents=True)
        (repo/'src/__init__.py').write_text('VALUE = 1\n')
        write_project(repo, {'project': {'name': name}, 'tool': {'mcpywrap': {
            'export': {'kind': 'code', 'path': 'src', 'target': 'Script/'+name}}}})
        return repo

    def test_add_reports_a_shared_node_still_published_via_another_path(self):
        self.helper('helper')
        normal = self.helper('normal')
        self.config(normal, local_dependencies=['../helper'])
        self.service.add_local('../normal')
        result = self.invoke('add', '--path', '../helper', '--unbundled', '--json')
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.stdout)
        self.assertIs(data['unbundled'], True)
        self.assertIs(data['included_in_release'], True)
        human = self.invoke('add', '--path', '../helper')
        self.assertEqual(human.exit_code, 0, human.output)
        self.assertIn('共享节点仍通过其他打包引用', human.output)
        api = Core().execute('add', self.main, local_path='../helper', unbundled=True)
        self.assertIs(api['included_in_release'], True)

    def test_default_false_and_explicit_flags_preserve_one_declaration(self):
        self.helper('helper')
        def add(*flags):
            result = self.invoke('add', '--path', '../helper', *flags, '--json')
            self.assertEqual(result.exit_code, 0, result.output)
            return json.loads(result.stdout)
        initial = add()
        self.assertIs(initial['unbundled'], False)
        packaged = self.invoke('package', '--json')
        self.assertEqual(packaged.exit_code, 0, packaged.output)
        with zipfile.ZipFile(json.loads(packaged.stdout)['artifact']) as archive:
            self.assertTrue(any(name.endswith('/helper.py') for name in archive.namelist()))
        updated = add('--unbundled')
        self.assertIs(updated['previous_unbundled'], False)
        self.assertIs(updated['unbundled'], True)
        self.assertIs(add()['unbundled'], True)
        restored = add('--bundled')
        self.assertIs(restored['previous_unbundled'], True)
        self.assertIs(restored['unbundled'], False)
        self.assertEqual(len(self.service.list()), 1)
        self.assertIs(self.service.list()[0].unbundled, False)

    def test_unbundled_accepts_only_real_booleans(self):
        from mcpywrap_core.git_projects import declarations as git_declarations
        for invalid in ('true', 'false', '', 0, 1, None, [], {}):
            with self.subTest(value=invalid):
                with self.assertRaises(DependencyError):
                    declarations({'tool':{'mcpywrap':{'local_dependencies':[{'path':'../helper','unbundled':invalid}]}}})
                with self.assertRaises(DependencyError):
                    git_declarations(self.main, {'tool':{'mcpywrap':{'git_dependencies':[{'name':'helper','git':'https://example.invalid/helper.git','rev':'f'*40,'unbundled':invalid}]}}})

    def test_command_selection_and_clean_replacement(self):
        self.helper('helper')
        added = self.invoke('add', '--path', '../helper', '--unbundled', '--json')
        self.assertEqual(added.exit_code, 0, added.output)
        self.assertEqual(json.loads(added.stdout)['unbundled'], True)
        self.assertFalse(json.loads(added.stdout)['included_in_release'])
        output = self.main/'build'
        ok, error = runtime_builder(self.main, output).build()
        self.assertTrue(ok, error)
        self.assertTrue((output/'behavior_pack/helper.py').exists())
        built = self.invoke('build', '--json')
        self.assertEqual(built.exit_code, 0, built.output)
        self.assertEqual(json.loads(built.stdout)['dependency_selection']['purpose'], 'release')
        self.assertFalse((output/'behavior_pack/helper.py').exists())
        packaged = self.invoke('package', '--json')
        self.assertEqual(packaged.exit_code, 0, packaged.output)
        with zipfile.ZipFile(json.loads(packaged.stdout)['artifact']) as archive:
            self.assertFalse(any(name.endswith('/helper.py') for name in archive.namelist()))
        self.assertTrue(runtime_builder(self.main, output).build()[0])
        self.assertTrue((output/'behavior_pack/helper.py').exists())

    def test_dev_command_and_full_watcher_rebuild_keep_dev(self):
        self.helper('helper')
        self.service.add_local('../helper', unbundled=True)
        with patch('mcpywrap_core.commands.dev_cmd.ProjectWatcher') as watcher, patch('mcpywrap_core.commands.dev_cmd.time.sleep', side_effect=KeyboardInterrupt):
            watcher.return_value.setup_from_config.return_value = 1
            result = self.invoke('dev')
        self.assertIn('本地运行', result.output)
        self.assertTrue((self.main/'build/behavior_pack/helper.py').exists())
        watcher.return_value.stop.assert_called_once()
        actual = ProjectWatcher(self.main, self.main/'build')
        actual.setup_from_config('game')
        actual._build_libraries()
        self.assertTrue((self.main/'build/behavior_pack/helper.py').exists())

    def test_missing_dev_does_not_block_release_or_run_consumer_hooks(self):
        self.config(local_dependencies=[{'path': '../missing', 'unbundled': True}])
        for command in ('build', 'package'):
            result = self.invoke(command, '--json')
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(json.loads(result.stdout)['dependency_selection']['excluded'][0]['reason'], 'unbundled')
        with self.assertRaises(DependencyError):
            self.service.resolve()

    def test_root_only_dev_transitivity_and_shared_main_reachability(self):
        common = self.helper('common')
        main_dep = self.helper('normal')
        dev_dep = self.helper('helper')
        self.config(main_dep, local_dependencies=['../common', {'path': '../normal-test-missing', 'unbundled': True}])
        self.config(dev_dep, local_dependencies=['../common', {'path': '../helper-test-missing', 'unbundled': True}])
        self.config(local_dependencies=['../normal', {'path': '../helper', 'unbundled': True}])
        manager = self.service.resolve()
        selection = {item['name']: item for item in manager.selection()['dependencies']}
        self.assertEqual(selection['common']['unbundled'], False)
        self.assertEqual(selection['helper']['unbundled'], True)
        self.assertIn(['game', 'normal', 'common'], selection['common']['via'])
        self.assertEqual({p.path for p in self.service.resolve(purpose='release').get_all_dependencies().values()}, {str(main_dep), str(common)})
        self.assertEqual(len(manager.excluded), 2)

    def test_packaging_changes_and_remove_match_canonical_path(self):
        helper = self.helper('helper')
        self.service.add_local('../helper', unbundled=True)
        self.assertFalse(self.service.add_local(str(helper))[0])
        self.assertEqual(self.service.list()[0].unbundled, True)
        self.assertTrue(self.service.add_local(str(helper), unbundled=False)[0])
        self.assertEqual(self.service.list()[0].unbundled, False)
        self.service.set_unbundled(self.service.list()[0], True)
        self.service.remove(self.service.list()[0])
        self.assertEqual(self.service.list(), [])
        self.assertTrue(helper.exists())

    def test_local_path_aliases_with_the_same_packaging_policy_are_deduplicated(self):
        helper = self.helper('helper')
        for unbundled in (False, True):
            with self.subTest(unbundled=unbundled):
                self.config(local_dependencies=[{'path':'../helper','unbundled':unbundled}, {'path':str(helper),'unbundled':unbundled}])
                manager = self.service.resolve()
                self.assertEqual(len(manager.get_all_dependencies()), 1)
                self.assertIs(manager.selection()['dependencies'][0]['unbundled'], unbundled)
                self.assertEqual(len(manager.root_node.children), 1)

    def test_local_aliases_with_conflicting_packaging_policies_are_rejected(self):
        helper = self.helper('helper')
        self.config(local_dependencies=['../helper', {'path':str(helper),'unbundled':True}])
        with self.assertRaisesRegex(DependencyError, 'unbundled 设置冲突'):
            self.service.resolve()

    def test_strict_configuration_and_mismatched_resolution(self):
        for item in ({'path':'../x','unbundled':'true'}, {'path':'../x','optional':True}, {'path':42}, {'path':'../x','unbundled':[]}):
            with self.subTest(item=item), self.assertRaises(DependencyError):
                declarations({'tool':{'mcpywrap':{'local_dependencies':[item]}}})
        manager = self.service.resolve()
        success, message = AddonProjectBuilder(self.main, self.main/'build', resolved=manager).build()
        self.assertFalse(success)
        self.assertIn('用途不匹配', message)

    def test_dev_must_not_override_main_python(self):
        helper = self.helper('helper')
        (helper/'behavior_pack/marker.py').write_text('DEV = True\n')
        self.service.add_local('../helper', unbundled=True)
        success, error = runtime_builder(self.main, self.main/'out').build()
        self.assertFalse(success)
        self.assertIn('不能覆盖', error)
        self.assertTrue(AddonProjectBuilder(self.main, self.main/'out').build()[0])

    def test_unbundled_prepare_is_diagnosed_and_not_executed(self):
        helper = self.helper('helper')
        self.config(helper, consumer_prepare={'python':'prepare.py'})
        self.service.add_local('../helper', unbundled=True)
        with self.assertRaisesRegex(ValueError, 'unbundled 依赖暂不支持'):
            PreparationPlan(self.main)
        plan = PreparationPlan(self.main, purpose='release')
        self.assertEqual(plan.providers, [])
        self.assertEqual(self.invoke('package', '--json').exit_code, 0)

    def test_active_dev_output_lease_rejects_other_thread_and_releases(self):
        output = self.main/'build'
        with output_lease(output) as lease:
            self.assertTrue(AddonProjectBuilder(self.main, output, purpose='runtime', output_lease=lease).build()[0])
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                success, error = executor.submit(AddonProjectBuilder(self.main, output).build).result()
            self.assertFalse(success)
            self.assertIn('资源正在使用', error)
        self.assertTrue(AddonProjectBuilder(self.main, output).build()[0])

    def test_git_unbundled_prune_upstream_dev_and_ignore_missing_registration_for_release(self):
        repo = self.git_helper('helper')
        self.config(repo, local_dependencies=[{'path':'../outside-missing','unbundled':True}])
        rev = self.commit(repo)
        added = GitDependencyService(self.main).add(repo.as_uri(), ref=rev, unbundled=True)
        self.assertEqual(added['unbundled'], True)
        path = self.main/LOCK_FILE
        lock = json.loads(path.read_text())
        self.assertEqual(lock['version'], 3)
        self.assertEqual(len(lock['nodes']), 1)
        self.assertEqual(len(self.service.resolve().get_all_dependencies()), 1)
        registered = resolve_projects(self.main)[0][1]
        self.assertEqual(read_project(registered)['tool']['mcpywrap']['local_dependencies'], [])
        shutil.rmtree(registered)
        self.assertEqual(self.invoke('package', '--json').exit_code, 0)
        with self.assertRaises(DependencyError):
            self.service.resolve()
        self.assertEqual(path.read_bytes(), json.dumps(lock, ensure_ascii=False, indent=2).encode()+b'\n')

    def test_git_packaging_changes_preserve_identity_and_lock_without_network(self):
        repo = self.git_helper('helper')
        rev = self.commit(repo)
        self.service.add_git(repo.as_uri(), ref=rev, unbundled=True)
        before = json.loads((self.main/LOCK_FILE).read_text())
        with patch('mcpywrap_core.git_projects.fetch_source', side_effect=AssertionError('no network')):
            self.service.set_unbundled(next(item for item in self.service.list() if item.kind=='git'), False)
        after = json.loads((self.main/LOCK_FILE).read_text())
        self.assertEqual(before['roots'], after['roots'])
        self.assertEqual(before['nodes'], after['nodes'])
        self.assertEqual(self.service.resolve(purpose='release').selection()['dependencies'][0]['unbundled'], False)

    def test_git_main_shared_with_dev_still_published_and_node_deduplicated(self):
        repo = self.git_helper('shared')
        rev = self.commit(repo)
        self.service.add_git(repo.as_uri(), ref=rev, name='normal', unbundled=False)
        shared = self.service.add_git(repo.as_uri(), ref=rev, name='development', unbundled=True)
        self.assertTrue(shared['unbundled'])
        self.assertTrue(shared['included_in_release'])
        lock = json.loads((self.main/LOCK_FILE).read_text())
        self.assertEqual(lock['roots'][0], lock['roots'][1])
        self.assertEqual(len(lock['nodes']), 1)
        selection = self.service.resolve().selection()
        self.assertEqual(len(selection['dependencies']), 1)
        self.assertEqual(selection['dependencies'][0]['unbundled'], False)
        self.assertEqual(len(self.service.resolve(purpose='release').get_all_dependencies()), 1)

    def test_main_only_sync_preserves_uninstalled_dev_lock(self):
        normal, helper = self.git_helper('normal'), self.git_helper('helper')
        self.service.add_git(normal.as_uri(), ref=self.commit(normal))
        self.service.add_git(helper.as_uri(), ref=self.commit(helper), unbundled=True)
        before = json.loads((self.main/LOCK_FILE).read_text())
        dev_key = before['roots'][1]
        shutil.rmtree(self.main/'.mcpy/git-projects'/dev_key)
        result = self.invoke('sync', '--bundled-only', '--json')
        self.assertEqual(result.exit_code, 0, result.output)
        after = json.loads((self.main/LOCK_FILE).read_text())
        self.assertEqual(next(n for n in before['nodes'] if n['id']==dev_key), next(n for n in after['nodes'] if n['id']==dev_key))
        self.assertFalse((self.main/'.mcpy/git-projects'/dev_key).exists())
        self.assertEqual(json.loads(result.stdout)['dependency_selection']['purpose'], 'release')

    def test_cli_human_and_json_feedback_and_readonly_preview(self):
        self.helper('helper')
        added = self.invoke('add', '--path', '../helper', '--unbundled')
        self.assertEqual(added.exit_code, 0, added.output)
        self.assertIn('build/package 不包含', added.output)
        before = (self.main/'pyproject.toml').read_bytes()
        preview = self.invoke('deps', '--bundled-only', '--json')
        self.assertEqual(preview.exit_code, 0, preview.output)
        self.assertEqual(json.loads(preview.stdout)['purpose'], 'release')
        self.assertEqual(json.loads(preview.stdout)['dependencies'], [])
        self.assertEqual(before, (self.main/'pyproject.toml').read_bytes())
        bad = self.invoke('add', 'click', '--unbundled', '--json')
        self.assertNotEqual(bad.exit_code, 0)
        self.assertIn('只用于游戏依赖', json.loads(bad.stdout)['error'])
        self.assertIn('unbundled-dependencies', Core().describe()['capabilities'])

    def test_same_target_is_locked_across_cli_processes(self):
        with output_lease(self.main/'build'):
            result = subprocess.run([sys.executable, '-m', 'mcpywrap_core', '--local', '--project', str(self.main), '--non-interactive', 'build', '--json'], capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data['code'], 'busy')
        self.assertFalse((self.main/'build').exists())

    def test_core_unbundled_options_and_main_resolution(self):
        self.helper('helper')
        added = Core().execute('add', self.main, local_path='../helper', unbundled=True)
        self.assertEqual(added['unbundled'], True)
        self.assertEqual(Core().execute('resolve', self.main, bundled_only=True)['dependency_selection']['dependencies'], [])
        self.assertEqual(Core().execute('resolve', self.main)['dependency_selection']['dependencies'][0]['unbundled'], True)
        with self.assertRaises(DependencyError):
            self.service.add_local('../helper', unbundled='')
        with patch('mcpywrap_core.git_projects.fetch_source', side_effect=AssertionError('must validate before fetch')):
            with self.assertRaises(DependencyError):
                self.service.add_git('https://example.invalid/a.git', unbundled='unknown')

    def test_incremental_dev_addition_cannot_shadow_release_module(self):
        helper = self.helper('helper')
        self.service.add_local('../helper', unbundled=True)
        output = self.main/'build'
        self.assertTrue(runtime_builder(self.main, output).build()[0])
        watcher = ProjectWatcher(self.main, output)
        watcher.setup_from_config('game')
        (helper/'behavior_pack/marker.py').write_text('DEV = True\n')
        before = (output/'behavior_pack/marker.py').read_bytes()
        with self.assertRaisesRegex(DependencyError, '不能覆盖'):
            watcher.rebuild('behavior', 'marker.py')
        self.assertEqual((output/'behavior_pack/marker.py').read_bytes(), before)

    def test_remove_dev_through_public_cli(self):
        helper = self.helper('helper')
        self.service.add_local('../helper', unbundled=True)
        result = self.invoke('remove', '--path', str(helper), '--json')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.stdout)['unbundled'], True)
        self.assertEqual(self.service.list(), [])

    def test_main_only_sync_restores_shared_node_when_dev_root_is_first(self):
        repo = self.git_helper('shared')
        rev = self.commit(repo)
        self.service.add_git(repo.as_uri(), ref=rev, name='development', unbundled=True)
        self.service.add_git(repo.as_uri(), ref=rev, name='normal')
        registered = resolve_projects(self.main)[0][1]
        shutil.rmtree(registered)
        result = self.invoke('sync', '--bundled-only', '--json')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(registered.is_dir())
        self.assertEqual(json.loads(result.stdout)['git_projects'], 1)

    def test_release_ignores_dev_pin_changes_but_checks_main_pin(self):
        normal, helper = self.git_helper('normal'), self.git_helper('helper')
        self.service.add_git(normal.as_uri(), ref=self.commit(normal))
        self.service.add_git(helper.as_uri(), ref=self.commit(helper), unbundled=True)
        config = read_project(self.main)
        config['tool']['mcpywrap']['git_dependencies'][1]['rev'] = 'f'*40
        write_project(self.main, config)
        self.assertEqual(len(self.service.resolve(purpose='release').get_all_dependencies()), 1)
        with self.assertRaises(DependencyError):
            self.service.resolve()
        config['tool']['mcpywrap']['git_dependencies'][0]['rev'] = 'f'*40
        write_project(self.main, config)
        with self.assertRaises(DependencyError):
            self.service.resolve(purpose='release')

    def test_consumed_local_projects_do_not_sync_their_own_dev_git(self):
        helper = self.helper('helper')
        self.config(helper, git_dependencies=[{'name':'private-test-tool','git':'https://example.invalid/private.git', 'rev':'f'*40, 'unbundled':True}])
        self.service.add_local('../helper')
        with patch('mcpywrap_core.git_projects.fetch_source', side_effect=AssertionError('must not fetch upstream dev')):
            result = self.invoke('sync', '--json')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.invoke('package', '--json').exit_code, 0)

    def test_main_map_build_and_package_exclude_missing_dev(self):
        world = self.root/'world'
        (world/'db').mkdir(parents=True)
        (world/'level.dat').write_bytes(b'world')
        write_project(world, {'project':{'name':'world'},'tool':{'mcpywrap':{'project_type':'map','target_dir':'build','local_dependencies':[{'path':'../missing','unbundled':True}]}}})
        for command in ('build','package'):
            result = cli_runner().invoke(cli, ['--local','--project',str(world),'--non-interactive',command,'--json'])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(json.loads(result.stdout)['dependency_selection']['purpose'], 'release')

    def test_framework_shortcut_promotes_its_runtime_to_main(self):
        from mcpywrap_core.frameworks import add_framework
        from mcpywrap_core.framework_presets import FRAMEWORK_PRESETS
        repo = self.git_helper('tiny')
        rev = self.commit(repo)
        preset = {'title':'Tiny', 'version':'fixture', 'rev':rev, 'sources':{'local':repo.as_uri()}, 'default_source':'local', 'kind':'code', 'subdir':'src', 'folder':'tiny', 'files':{'modMain.py':'from .tiny import VALUE\n'}}
        with patch.dict(FRAMEWORK_PRESETS, {'tiny':preset}):
            self.service.add_git(repo.as_uri(), ref=rev, name='tiny-script', subdir='src', kind='code', target='Script/tiny', unbundled=True)
            result = add_framework(self.main, 'tiny', 'Script')
        self.assertEqual(result['unbundled'], False)
        self.assertEqual(result['previous_unbundled'], True)
        self.assertEqual(self.service.list()[0].unbundled, False)
        self.assertTrue(self.invoke('package', '--json').exit_code == 0)

    def test_removing_from_consumed_partial_lock_keeps_unresolved_dev_root(self):
        from mcpywrap_core.git_projects import sync_projects
        normal, helper = self.git_helper('normal'), self.git_helper('helper')
        normal_rev, helper_rev = self.commit(normal), self.commit(helper)
        self.config(git_dependencies=[{'name':'normal','git':normal.as_uri(),'rev':normal_rev}, {'name':'helper','git':helper.as_uri(),'rev':helper_rev,'unbundled':True}])
        sync_projects(self.main, purpose='release', consumer=True)
        GitDependencyService(self.main).remove('normal')
        lock = json.loads((self.main/LOCK_FILE).read_text())
        self.assertEqual(lock['roots'], [None])
        self.assertEqual(lock['nodes'], [])

    def test_qt_unbundled_selection_editing_and_host_package_boundary(self):
        from PySide6.QtWidgets import QApplication
        from mcpywrap_core.ui import project_ui as ui
        app = QApplication.instance() or QApplication([])
        self.helper('helper')
        with patch.object(ui, 'find_all_mcpywrap_packages', return_value=[]), patch('mcpywrap_core.engines.macos.MacOSBackend.instances', return_value=[]):
            window = ui.GameInstanceManager(str(self.main))
        try:
            window.dependency_kind.setCurrentIndex(window.dependency_kind.findData('local'))
            window.dependency_unbundled.setChecked(True)
            window.local_path_input.setText('../helper')
            window.add_dependency()
            self.assertEqual(self.service.list()[0].unbundled, True)
            item = window.dependency_list.item(0)
            self.assertIn('不随构建打包', item.text())
            window.dependency_list.setCurrentItem(item)
            window.on_dependency_selected(item)
            self.assertTrue(window.change_packaging_btn.isEnabled())
            with patch.object(ui.QInputDialog, 'getItem', return_value=('随构建打包（默认，unbundled=false）', True)):
                window.change_dependency_packaging()
            self.assertEqual(self.service.list()[0].unbundled, False)
            self.assertIn('随构建打包', window.dependency_list.item(0).text())
            window.dependency_kind.setCurrentIndex(window.dependency_kind.findData('package'))
            self.assertTrue(window.dependency_unbundled.isHidden())
            window.set_dependency_busy(True)
            self.assertFalse(window.change_packaging_btn.isEnabled())
        finally:
            window.close()
            app.processEvents()

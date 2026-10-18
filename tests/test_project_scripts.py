"""Real command execution and lifecycle boundaries in isolated projects."""
import json
import inspect
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from click.testing import CliRunner
from mcpywrap.cli import cli
from mcpywrap.dependencies import read_project, write_project
from mcpywrap.project_scripts import ScriptError, before, configuration, operation
from test_runtime_deployment import fixture


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = fixture(Path(self.tmp.name), '中文 project').resolve()
        (self.project/'tools').mkdir()
        self.configure("from pathlib import Path\nPath('behavior_pack/result.json').write_text('{\"ok\":true}')\n")

    def configure(self, code, **options):
        (self.project/'tools/generate.py').write_text(code, encoding='utf-8')
        config = read_project(self.project)
        config['tool']['mcpywrap'].update(target_dir='build', scripts={'assets': {'python': 'tools/generate.py', **options}},
            hooks={event:['assets'] for event in ('before_build','before_package','before_run')})
        write_project(self.project, config)

    def invoke(self, *args):
        # Click 8.1 (Python 3.9) otherwise merges stderr into result.stdout.
        options = {'mix_stderr': False} if 'mix_stderr' in inspect.signature(CliRunner).parameters else {}
        return CliRunner(**options).invoke(cli, ['--project', str(self.project), *args])

    def test_manual_project_cwd_arguments_and_remote_are_local(self):
        self.configure("import sys,json,os\nfrom pathlib import Path\nPath('args.json').write_text(json.dumps([os.getcwd(),sys.argv[1:]]))\n")
        result = self.invoke('--remote', 'http://127.0.0.1:1', 'script', 'run', '--json', 'assets', '--', '--json', '--help', 'a b', '$(literal)')
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.stdout)
        self.assertTrue(data['ok'])
        cwd, args = json.loads((self.project/'args.json').read_text())
        self.assertEqual(Path(cwd), self.project.resolve())
        self.assertEqual(args, ['--json','--help','a b','$(literal)'])

    def test_child_json_flag_does_not_enable_parent_json(self):
        result = self.invoke('script','run','assets','--','--json')
        self.assertEqual(result.exit_code,0,result.output)
        self.assertFalse(result.stdout.startswith('{'))

    def test_list_is_read_only(self):
        result=self.invoke('script','list','--json')
        self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual(json.loads(result.stdout)['scripts'][0]['name'],'assets')
        self.assertFalse((self.project/'.mcpy').exists())

    def test_logs_and_large_output_do_not_corrupt_json(self):
        self.configure("import sys\nprint('中文'*50000)\nprint('error-channel',file=sys.stderr)\n")
        result=self.invoke('script','run','assets','--json')
        self.assertEqual(result.exit_code,0,result.output[-1000:])
        data=json.loads(result.stdout)
        log=Path(data['scripts'][0]['script_log']).read_text()
        self.assertIn('中文'*100,log)
        self.assertIn('error-channel',log)

    def test_package_runs_only_its_hook_once_and_consumes_result(self):
        self.configure("from pathlib import Path\np=Path('count');p.write_text(p.read_text()+'x' if p.exists() else 'x')\nPath('behavior_pack/generated.json').write_text('{\"fresh\":true}')\n")
        result=self.invoke('package','--json')
        self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual((self.project/'count').read_text(),'x')
        import zipfile
        with zipfile.ZipFile(json.loads(result.stdout)['artifact']) as z:
            self.assertEqual(z.read('中文 project_bp/generated.json'),b'{"fresh":true}')
            self.assertFalse(any('tools/' in n for n in z.namelist()))

    def test_failure_preserves_previous_zip_and_structured_error(self):
        first=self.invoke('package','--json')
        self.assertEqual(first.exit_code,0,first.output)
        artifact=Path(json.loads(first.stdout)['artifact']);old=artifact.read_bytes()
        self.configure("raise SystemExit(7)\n")
        result=self.invoke('package','--json');data=json.loads(result.stdout)
        self.assertEqual(result.exit_code,1)
        self.assertEqual(data['code'],'script_failed')
        self.assertEqual(data['script_exit_code'],7)
        self.assertEqual(old,artifact.read_bytes())

    def test_build_hook_precedes_builder(self):
        result=self.invoke('build','--json')
        self.assertEqual(result.exit_code,0,result.output)
        self.assertTrue((self.project/'build/behavior_pack/result.json').exists())

    def test_invalid_target_does_not_execute_script(self):
        config=read_project(self.project);config['tool']['mcpywrap']['target_dir']='.mcpy/runtime/assembled';write_project(self.project,config)
        result=self.invoke('build','--json')
        self.assertNotEqual(result.exit_code,0)
        self.assertFalse((self.project/'behavior_pack/result.json').exists())

    def test_configuration_change_blocks_consumption(self):
        self.configure("from pathlib import Path\np=Path('pyproject.toml');p.write_text(p.read_text()+'\\n# changed\\n')\n")
        result=self.invoke('build','--json')
        self.assertEqual(json.loads(result.stdout)['code'],'script_config_changed')
        self.assertFalse((self.project/'build').exists())

    def test_timeout_and_cancellation(self):
        self.configure('import time\ntime.sleep(60)\n',timeout=.2)
        with self.assertRaises(ScriptError) as caught:
            with operation(self.project,task='assets'): pass
        self.assertEqual(caught.exception.code,'script_timeout')
        self.configure('import time\ntime.sleep(60)\n')
        deadline=time.monotonic()+.3
        with self.assertRaises(ScriptError) as caught:
            with operation(self.project,task='assets',cancel=lambda:time.monotonic()>deadline): pass
        self.assertEqual(caught.exception.code,'script_cancelled')

    def test_recursive_write_command_is_rejected(self):
        root=str(Path(__file__).resolve().parents[1])
        self.configure("import sys\nsys.path.insert(0,%r)\nfrom mcpywrap.cli import cli\ncli.main(['build','--json'])\n" % root)
        result=self.invoke('script','run','assets','--json')
        self.assertNotEqual(result.exit_code,0)
        log=Path(json.loads(result.stdout)['script_log']).read_text()
        self.assertIn('script_recursion',log)

    def test_nonzero_stops_remaining_hooks(self):
        self.configure('raise SystemExit(7)\n')
        config=read_project(self.project);settings=config['tool']['mcpywrap']
        settings['scripts']['later']={'cmd':[sys.executable,'-c',"from pathlib import Path;Path('later').touch()"]}
        settings['hooks']['before_build']=['assets','later'];write_project(self.project,config)
        result=self.invoke('build','--json')
        self.assertNotEqual(result.exit_code,0)
        self.assertFalse((self.project/'later').exists())

    def test_low_level_builder_and_refresh_do_not_execute_hooks(self):
        from mcpywrap.runtime.deployment import Deployment
        d=Deployment(self.project)
        with d.lock(): d.prepare();d.commit()
        self.assertFalse((self.project/'behavior_pack/result.json').exists())

    def test_lock_covers_consumption_and_no_change_can_reuse_deployment(self):
        from mcpywrap.runtime.deployment import Deployment
        ids=[]
        for _ in range(2):
            with before(self.project,'before_run'):
                d=Deployment(self.project)
                with d.lock(): d.prepare();d.commit()
                ids.append(d.record['id'])
                with self.assertRaises(ValueError):
                    with operation(self.project,task='assets'): pass
        self.assertEqual(ids[0],ids[1])

    def test_invalid_schema_does_not_execute(self):
        for changes in ({'timeout':True},{'cmd':['echo']},{'env':{'MCPY_EVENT':'bad'}},{'python':'../escape.py'}):
            self.configure('raise AssertionError("ran")\n')
            config=read_project(self.project);config['tool']['mcpywrap']['scripts']['assets'].update(changes);write_project(self.project,config)
            with self.assertRaises(ScriptError): configuration(self.project)

    def test_dev_only_runs_initial_hook(self):
        self.configure("from pathlib import Path\np=Path('count');p.write_text(p.read_text()+'x' if p.exists() else 'x')\n")
        from types import SimpleNamespace
        from unittest.mock import Mock
        with patch('mcpywrap.commands.dev_cmd.ProjectWatcher') as watcher, patch('mcpywrap.commands.dev_cmd.time', SimpleNamespace(sleep=Mock(side_effect=KeyboardInterrupt))):
            watcher.return_value.setup_from_config.return_value = 0
            result = self.invoke('dev')
        self.assertEqual(result.exit_code, 130, result.output)
        from mcpywrap.builders.project_builder import AddonProjectBuilder
        self.assertTrue(AddonProjectBuilder(self.project, self.project/'build').build()[0])
        self.assertEqual((self.project/'count').read_text(), 'x')

    def test_native_startup_generates_before_deployment_and_failure_never_launches(self):
        from mcpywrap.runtime.native import launch_world
        from mcpywrap.runtime.storage import write
        from mcpywrap.mcstudio.sessions import session_path
        sid = 'a'*32
        directory = self.project/'.runtime/native'
        data = dict(project=str(self.project), session=sid, level_id='world', state='starting',
                    mode='local', game=None, worker=None, config_path=str(directory/'world.cppconfig'),
                    launch={'data': str(directory/'data'), 'engine_version': 'test',
                            'prepare_world': {'supports_config': True}})
        write(session_path(self.project,sid)/'session.json',data)
        def launcher(plan):
            self.assertTrue((directory/'assembled/behavior_pack/result.json').is_file())
            raise RuntimeError('mock launch reached')
        with self.assertRaisesRegex(RuntimeError,'mock launch reached'):
            launch_world(data, launcher)
        data.update(state='failed', phase='preparing')
        write(session_path(self.project,sid)/'session.json',data)
        self.configure('raise SystemExit(7)\n')
        with patch('mcpywrap.runtime.native.Deployment.prepare') as prepare:
            with self.assertRaises(ScriptError):
                launch_world(data, lambda _: self.fail('failure launched game'))
        prepare.assert_not_called()

    def test_windows_startup_uses_same_script_service(self):
        from types import SimpleNamespace
        from mcpywrap.runtime.windows import launch
        from mcpywrap.runtime.storage import write
        from mcpywrap.mcstudio.sessions import session_path
        sid='b'*32
        data=dict(project=str(self.project),session=sid,state='starting',mode='local',
                  level_id='world',game=None,worker=None,config_path=str(self.project/'.runtime/world.cppconfig'),
                  launch={'engine':dict(executable='game',version='test',engine_dir='engine',download_dir='download',source='test')})
        write(session_path(self.project,sid)/'session.json',data)
        def open_game(*args,**kwargs):
            self.assertTrue((self.project/'.mcpy/runtime/assembled/behavior_pack/result.json').is_file())
            raise RuntimeError('mock launch reached')
        with patch('mcpywrap.runtime.windows.instances.world_path',return_value=self.project/'.test-world'), \
             patch('mcpywrap.runtime.windows.require_resources'), \
             patch('mcpywrap.mcstudio.mcs.get_mcs_game_engine_netease_data_path',return_value=str(self.project/'.test-global')), \
             patch('mcpywrap.mcstudio.game.open_game',side_effect=open_game):
            with self.assertRaisesRegex(RuntimeError,'mock launch reached'):
                launch(data,SimpleNamespace(port=12345))

    def test_timeout_reclaims_descendant(self):
        self.configure("import subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\nPath('child.pid').write_text(str(p.pid))\ntime.sleep(60)\n",timeout=.7)
        with self.assertRaises(ScriptError) as caught:
            with operation(self.project,task='assets'): pass
        self.assertEqual(caught.exception.code,'script_timeout')
        self.assert_process_ended(int((self.project/'child.pid').read_text()))

    def assert_process_ended(self,pid):
        import psutil
        try:
            self.assertEqual(psutil.Process(pid).status(),psutil.STATUS_ZOMBIE)
        except psutil.NoSuchProcess:
            pass

    def test_calling_process_killed_supervisor_reclaims_child(self):
        self.configure("import os,time\nfrom pathlib import Path\nPath('child.pid').write_text(str(os.getpid()))\ntime.sleep(60)\n")
        code="import sys\nfrom mcpywrap.project_scripts import operation\nwith operation(sys.argv[1],task='assets'): pass\n"
        env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]),PYTHONDONTWRITEBYTECODE='1')
        p=subprocess.Popen([sys.executable,'-c',code,str(self.project)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: p.kill() if p.poll() is None else None)
        deadline=time.monotonic()+8
        while not (self.project/'child.pid').exists() and time.monotonic()<deadline:
            time.sleep(.05)
        self.assertTrue((self.project/'child.pid').exists())
        p.kill();p.wait(timeout=5)
        active=json.loads((self.project/'.mcpy/scripts/active.json').read_text())
        deadline=time.monotonic()+8
        state={}
        while time.monotonic()<deadline:
            state=json.loads(Path(active['state_path']).read_text())
            if state.get('finished_at'): break
            time.sleep(.05)
        self.assertEqual(state['state'],'cancelled',state)
        self.assert_process_ended(int((self.project/'child.pid').read_text()))

    def test_real_cli_has_exactly_one_json_object(self):
        self.configure("import sys\nprint('child stdout');print('child stderr',file=sys.stderr)\n")
        env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]),PYTHONDONTWRITEBYTECODE='1')
        result=subprocess.run([sys.executable,'-m','mcpywrap','--project',str(self.project),'script','run','--json','assets','--','--help'],
                              env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['ok'])
        self.assertIn('child stdout',result.stderr)
        self.assertIn('child stderr',result.stderr)


if __name__=='__main__':unittest.main()

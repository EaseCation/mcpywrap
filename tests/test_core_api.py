import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from click.testing import CliRunner
from mcpywrap_core.api import Core
from mcpywrap_core.cli import cli
from mcpywrap_core.host import HostServices
from mcpywrap_core.dependencies import read_project, write_project
from core_fixture import projects


class CoreApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = projects(self.root)
        self.core = Core(HostServices(python_executable=None, allow_processes=False,
                                     lock_directory=self.root/'locks'))

    def test_api_cli_and_host_without_processes_have_identical_outputs(self):
        self.assertEqual(len(self.core.execute('resolve', self.project)['dependencies']), 1)
        output = Path(self.core.execute('build', self.project)['output'])
        expected = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob('*') if p.is_file()}
        self.assertEqual((output/'behavior_pack/shared.py').read_text(), "OWNER = 'main'\n")
        self.assertEqual(set(json.loads((output/'resource_pack/textures/terrain_texture.json').read_text())['texture_data']), {'main', 'dependency'})
        artifact = self.core.execute('package', self.project)['artifact']
        with zipfile.ZipFile(artifact) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        for command in ('build', 'package'):
            result = CliRunner().invoke(cli, ['--project', str(self.project), '--non-interactive', command, '--json'])
            self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(expected, {str(p.relative_to(output)): p.read_bytes() for p in output.rglob('*') if p.is_file()})
        with zipfile.ZipFile(artifact) as archive:
            self.assertEqual(entries, {name: archive.read(name) for name in archive.namelist()})

    def test_initialization_preserves_host_declared_metadata_only(self):
        root=self.root/'host-project';root.mkdir()
        metadata=root/'.host-project.json';metadata.write_text('{"id":"stable"}')
        host=Core(HostServices(python_executable=None,allow_processes=False,project_metadata_files=('.host-project.json',)))
        host.execute('init',root,name='host-project',project_type='addon')
        self.assertEqual(metadata.read_text(),'{"id":"stable"}')
        unrelated=self.root/'unrelated';unrelated.mkdir();(unrelated/'business.txt').write_text('keep')
        with self.assertRaisesRegex(ValueError,'非空目录'):host.execute('init',unrelated,name='unrelated',project_type='addon')

    def test_local_sync_works_without_a_python_executable(self):
        result = self.core.execute('sync', self.project)
        self.assertTrue(result['sources_synced'])
        self.assertEqual(result['environment']['state'], 'not_required')

    def test_project_hook_fails_explicitly_without_fallback(self):
        config = read_project(self.project)
        config['tool']['mcpywrap'].update(scripts={'generate': {'python': 'generate.py'}}, hooks={'before_build': ['generate']})
        write_project(self.project, config)
        (self.project/'generate.py').write_text("raise AssertionError('must not execute')")
        result = self.core.request({'core_api': 1, 'operation': 'build', 'project': str(self.project)})
        self.assertFalse(result['ok'])
        self.assertEqual(result['code'], 'host_capability_unavailable')
        self.assertFalse((self.project/'build').exists())

    def test_bad_protocol_and_options_rejected_before_writes(self):
        for request in ({'core_api': 2}, {'core_api': 1, 'operation': 'build', 'project': str(self.project),
                                        'options': {'merge': 'yes'}}):
            self.assertFalse(self.core.request(request)['ok'])
        self.assertFalse((self.project/'build').exists())

    def test_project_operation_validation_keeps_the_structured_error_envelope(self):
        for operation,options in [('mod',{}),('mod',{'name':['invalid']}),('script.run',{}),
                                  ('script.run',{'name':'build','args':'not-a-list'}),('script.list',{'effective':'yes'})]:
            with self.subTest(operation=operation,options=options):
                result=self.core.request({'core_api':1,'operation':operation,'project':str(self.project),'options':options})
                self.assertFalse(result['ok']);self.assertIn('error',result);self.assertIn('code',result)
        self.assertFalse((self.project/'build').exists())

    def test_offline_operations_do_not_import_desktop_extras(self):
        code = '''
import importlib.abc, sys, tempfile
from pathlib import Path
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'psutil','watchdog','rich','PySide6','jsonschema','pip','twine','build','setuptools'}:
            raise AssertionError('Unexpected dependency: '+fullname)
sys.meta_path.insert(0, Guard())
from mcpywrap_core.api import Core
from mcpywrap_core.host import HostServices
from core_fixture import projects
with tempfile.TemporaryDirectory() as temp:
    project = projects(Path(temp))
    core = Core(HostServices(python_executable=None, allow_processes=False))
    for method in ('resolve','build','package','sync'):
        core.execute(method, project)
'''
        code = 'import sys; sys.path.insert(0, ' + repr(str(Path(__file__).resolve().parent)) + ')\n' + code
        subprocess.run([sys.executable, '-c', code], check=True)

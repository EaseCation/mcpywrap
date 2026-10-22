import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from mcpywrap_host import CoreStore, UpdateError


class CoreUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = CoreStore(self.root/'store')

    def wheel(self, version='1.0', *, core_api=1, requires_python='>=3.9', dependency=None, extra=None, broken=False):
        path = self.root/(version+'.whl')
        metadata = f'Metadata-Version: 2.1\nName: mcpywrap-core\nVersion: {version}\nRequires-Python: {requires_python}\n'
        if dependency:
            metadata += 'Requires-Dist: '+dependency+'\n'
        contract = {'format': 1, 'core_api': core_api, 'requires_host_api': 1, 'entrypoint': 'mcpywrap_core.api:Core'}
        code = 'raise RuntimeError("bad release")' if broken else f'''class Core:
    def describe(self):
        return {{'version': {version!r}, 'core_api': 1, 'host_api': 1}}
'''
        with zipfile.ZipFile(path, 'w') as archive:
            for name, value in {'mcpywrap_core/__init__.py': '', 'mcpywrap_core/api.py': code,
                'mcpywrap_core/core-contract.json': json.dumps(contract),
                f'mcpywrap_core-{version}.dist-info/METADATA': metadata,
                f'mcpywrap_core-{version}.dist-info/WHEEL': 'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
                'mcpywrap_host/never_replace.py': 'raise AssertionError()'}.items():
                archive.writestr(name, value)
            if extra:
                archive.writestr(*extra)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def stage(self, version, **kwargs):
        path, digest = self.wheel(version, **kwargs)
        self.store.stage(path, expected_sha256=digest, expected_version=version)
        return digest

    def child(self, action, identity=''):
        code = '''
import json,sys
from mcpywrap_host import CoreStore
store=CoreStore(sys.argv[1])
try:
    core=store.activate(sys.argv[3]) if sys.argv[2]=='activate' else store.load_selected()
    print(json.dumps(core.describe() if core else {'bundled':True}))
except Exception as error:
    print(json.dumps({'code':getattr(error,'code',None),'error':str(error)}));sys.exit(3)
'''
        return subprocess.run([sys.executable, '-c', code, str(self.store.root), action, identity], capture_output=True, text=True)

    def test_upgrade_load_and_rollback_in_fresh_processes(self):
        first, second = self.stage('1.0'), self.stage('1.1')
        self.assertIsNone(self.store.selection()['current'])
        self.assertFalse((self.store._slot(first)/'mcpywrap_host').exists())
        for identity, version in ((first, '1.0'), (second, '1.1')):
            result = self.child('activate', identity)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual(json.loads(result.stdout)['version'], version)
            self.assertEqual(json.loads(self.child('load').stdout)['version'], version)
        self.assertEqual(self.store.selection()['previous'], first)
        self.store.rollback()
        self.assertEqual(json.loads(self.child('load').stdout)['version'], '1.0')

    def test_failed_health_check_preserves_selected_release(self):
        first = self.stage('1.0')
        self.assertEqual(self.child('activate', first).returncode, 0)
        broken = self.stage('1.1', broken=True)
        result = self.child('activate', broken)
        self.assertEqual(json.loads(result.stdout)['code'], 'health_check_failed')
        self.assertEqual(self.store.selection()['current'], first)

    def test_tampering_schedules_rollback_without_loading_two_versions(self):
        first, second = self.stage('1.0'), self.stage('1.1')
        self.assertEqual(self.child('activate', first).returncode, 0)
        self.assertEqual(self.child('activate', second).returncode, 0)
        (self.store._slot(second)/'mcpywrap_core/api.py').write_text('raise AssertionError()')
        result = self.child('load')
        self.assertEqual(result.returncode, 3)
        self.assertEqual(self.store.selection()['current'], first)
        self.assertEqual(json.loads(self.child('load').stdout)['version'], '1.0')

    def test_incompatible_and_unsafe_wheels_never_select_or_import(self):
        cases = [({'core_api': 2}, 'host_incompatible'),
                 ({'requires_python': '>=99'}, 'python_incompatible'),
                 ({'dependency': 'mcpy-does-not-exist>=1'}, 'dependency_incompatible'),
                 ({'extra': ('../../escape.py', '')}, 'unsafe_wheel'),
                 ({'extra': ('mcpywrap_core/native.so', '')}, 'native_payload'),
                 ({'extra': ('bootstrap.pth', 'import evil')}, 'native_payload')]
        for options, code in cases:
            with self.subTest(code=code):
                path, digest = self.wheel(**options)
                with self.assertRaises(UpdateError) as error:
                    self.store.stage(path, expected_sha256=digest, expected_version='1.0')
                self.assertEqual(error.exception.code, code)
                self.assertIsNone(self.store.selection()['current'])

    def test_digest_mismatch_and_imported_core_require_restart(self):
        path, digest = self.wheel()
        with self.assertRaises(UpdateError) as error:
            self.store.stage(path, expected_sha256='0'*64, expected_version='1.0')
        self.assertEqual(error.exception.code, 'digest_mismatch')
        self.store.stage(path, expected_sha256=digest, expected_version='1.0')
        code = '''
import mcpywrap_core, sys
from mcpywrap_host import CoreStore, UpdateError
try: CoreStore(sys.argv[1]).activate(sys.argv[2])
except UpdateError as error: assert error.code=='restart_required'
else: raise AssertionError('hot swap accepted')
'''
        subprocess.run([sys.executable, '-c', code, str(self.store.root), digest], check=True)

    def test_injected_module_rejected(self):
        identity = self.stage('1.0')
        (self.store._slot(identity)/'mcpywrap_core/injected.py').write_text('pass')
        with self.assertRaises(UpdateError) as error:
            self.store.verify(identity)
        self.assertEqual(error.exception.code, 'release_modified')

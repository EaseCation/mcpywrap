"""Explicit SDK targets, Python 2 completion wheels and environment drift."""
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import venv
import zipfile
from unittest.mock import patch

from click.testing import CliRunner
from mcpywrap.cli import cli
from mcpywrap.minecraft import modsdk_environment as sdk

VERSION = '3.9.0.79920'
DIST = 'mc_netease_sdk-' + VERSION + '.dist-info'


def wheel(extra=None):
    files = {'mod/__init__.py': b'', 'mod/client/__init__.py': b'',
             'mod/client/extraClientApi.py': b'def GetEngineVersion():\n    return "test"\n',
             'mod_log.py': b'print "Python 2 completion data"\n',
             DIST + '/METADATA': ('Metadata-Version: 2.1\nName: mc-netease-sdk\nVersion: ' + VERSION + '\n').encode(),
             DIST + '/WHEEL': b'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py2-none-any\n',
             DIST + '/RECORD': b''}
    files.update(extra or {})
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        for name, body in files.items():
            entry = zipfile.ZipInfo(name)
            # Preserve invalid archive bytes even on Windows, whose ZipInfo
            # constructor normally normalizes backslashes on write/read.
            entry.filename = name
            z.writestr(entry, body)
    return out.getvalue()


class ModsdkEnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='mcpy-sdk-test-')
        cls.root = Path(cls.temp.name)
        cls.pythons = []
        for name in ('环境 A', 'environment B'):
            path = cls.root / name
            venv.create(path, with_pip=False)
            cls.pythons.append(str(path / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def fake_download(self, version, directory):
        return sdk.adapt_completion_wheel(wheel(), version, directory)

    def test_install_uses_venv_not_symlink_base_and_needs_no_target_pip(self):
        first, other = self.pythons
        before = sdk.inspect_environment(first)
        self.assertNotEqual(before['environment']['prefix'], before['environment']['base_prefix'])
        self.assertEqual(before['environment']['invocation'], first)
        with patch.object(sdk, 'prepare_completion_wheel', side_effect=self.fake_download):
            result = sdk.install_environment(VERSION, first, before['environment']['identity'])
        self.assertEqual(result['environment']['identity'], before['environment']['identity'])
        self.assertEqual(result['installed']['version'], VERSION)
        self.assertTrue(result['installed']['in_environment'])
        self.assertIsNone(sdk.inspect_environment(other)['installed'])
        self.assertTrue(Path(result['installed']['location']).is_relative_to(Path(before['environment']['prefix'])))
        # Python 2-only syntax was installed as data; no compile/import required.
        self.assertTrue((Path(result['installed']['location']) / 'mod_log.py').is_file())
        # A second install exercises pip ownership/RECORD uninstall handling.
        with patch.object(sdk, 'prepare_completion_wheel', side_effect=self.fake_download):
            self.assertTrue(sdk.install_environment(VERSION, first)['installed']['in_environment'])

    def test_inspect_is_offline_and_does_not_import_sdk(self):
        with patch.object(sdk.urllib.request, 'urlopen', side_effect=AssertionError('offline')):
            result = sdk.inspect_environment(self.pythons[0])
        self.assertEqual(result['environment']['invocation'], self.pythons[0])

    def test_same_environment_has_a_cross_process_install_lock(self):
        data = sdk.inspect_environment(self.pythons[0])
        with sdk.installation_lock(data['environment']), patch.object(sdk, 'prepare_completion_wheel') as download:
            with self.assertRaisesRegex(ValueError, '资源正在使用'):
                sdk.install_environment(VERSION, self.pythons[0])
            download.assert_not_called()

    def test_wrong_identity_never_downloads_or_installs(self):
        with patch.object(sdk, 'prepare_completion_wheel') as download:
            with self.assertRaisesRegex(ValueError, '身份已改变'):
                sdk.install_environment(VERSION, self.pythons[0], 'stale')
            download.assert_not_called()

    def test_drift_during_download_stops_before_pip(self):
        data = sdk.inspect_environment(self.pythons[0])
        changed = dict(data, environment=dict(data['environment'], identity='changed'))
        with patch.object(sdk, 'inspect_environment', side_effect=[data, changed]), \
                patch.object(sdk, 'prepare_completion_wheel', side_effect=self.fake_download), \
                patch.object(sdk.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, '身份已改变'):
                sdk.install_environment(VERSION, self.pythons[0])
            run.assert_not_called()

    def test_failure_never_falls_back_to_tool_or_global_python(self):
        data = sdk.inspect_environment(self.pythons[0])
        failed = subprocess.CompletedProcess([], 1, b'', b'externally-managed-environment')
        with patch.object(sdk, 'inspect_environment', return_value=data), \
                patch.object(sdk, 'prepare_completion_wheel', side_effect=self.fake_download), \
                patch.object(sdk.subprocess, 'run', return_value=failed) as run:
            with self.assertRaisesRegex(ValueError, '未回退'):
                sdk.install_environment(VERSION, self.pythons[0])
            self.assertEqual(run.call_count, 1)
            args = run.call_args.args[0]
            self.assertEqual(args[args.index('--python') + 1], self.pythons[0])

    def test_inherited_package_is_not_claimed_ready(self):
        data = sdk.inspect_environment(self.pythons[0])
        inherited = dict(data, installed={'version': VERSION, 'location': '/base/site-packages', 'in_environment': False})
        with patch.object(sdk, 'inspect_environment', side_effect=[data, data, inherited]), \
                patch.object(sdk, 'prepare_completion_wheel', side_effect=self.fake_download), \
                patch.object(sdk.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaisesRegex(ValueError, '未通过核验'):
                sdk.install_environment(VERSION, self.pythons[0])

    def test_requires_explicit_absolute_executable(self):
        for path in ('python', str(self.root), str(self.root / 'missing')):
            with self.subTest(path=path), self.assertRaises(ValueError):
                sdk.inspect_environment(path)

    def test_retag_rebuilds_record_and_preserves_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            target = sdk.adapt_completion_wheel(wheel(), VERSION, directory)
            with zipfile.ZipFile(target) as z:
                self.assertIn(b'Tag: py3-none-any', z.read(DIST + '/WHEEL'))
                self.assertEqual(z.read('mod_log.py'), b'print "Python 2 completion data"\n')
                for name, digest, size in csv.reader(io.StringIO(z.read(DIST + '/RECORD').decode())):
                    if name.endswith('/RECORD'):
                        continue
                    body = z.read(name)
                    self.assertEqual(int(size), len(body))
                    self.assertEqual(digest, 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b'=').decode())

    def test_rejects_unsafe_or_active_wheel_contents(self):
        for name in ('../escape.py', '/absolute.py', 'C:/evil.py', 'x\\evil.py', 'evil.pth',
                     'bad.data/scripts/evil.py', 'sitecustomize.py', 'extra.dist-info/METADATA'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    sdk.adapt_completion_wheel(wheel({name: b'pass'}), VERSION, directory)

    def test_download_digest_is_required(self):
        metadata = {'urls': [{'packagetype': 'bdist_wheel', 'filename': 'x-py2-none-any.whl',
                             'url': 'https://files.pythonhosted.org/test.whl', 'digests': {'sha256': 'bad'}}]}
        response = io.BytesIO(wheel())
        with tempfile.TemporaryDirectory() as directory, patch.object(sdk, '_json_url', return_value=metadata), \
                patch.object(sdk.urllib.request, 'urlopen', return_value=response):
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                sdk.prepare_completion_wheel(VERSION, directory)

    def test_pip_configuration_cannot_redirect_target(self):
        with patch.dict(os.environ, {'PIP_TARGET': '/wrong', 'PIP_PREFIX': '/wrong', 'PIP_USER': '1', 'PYTHONPATH': '/wrong'}):
            env = sdk._clean_env()
        self.assertNotIn('PIP_TARGET', env)
        self.assertNotIn('PYTHONPATH', env)
        self.assertEqual(env['PIP_CONFIG_FILE'], os.devnull)

    def test_public_cli_inspect_and_invalid_combinations(self):
        runner = CliRunner()
        result = runner.invoke(cli, ['--local', '--non-interactive', 'modsdk', '--inspect', '--python', self.pythons[0], '--json'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.stdout)['environment']['invocation'], self.pythons[0])
        for args in (['--inspect', '--latest'], ['--latest', '--expected-environment', 'x'], ['--list', '--python', self.pythons[0]]):
            result = runner.invoke(cli, ['--local', '--non-interactive', 'modsdk', *args, '--json'])
            self.assertNotEqual(result.exit_code, 0, result.output)
            self.assertFalse(json.loads(result.stdout)['ok'])

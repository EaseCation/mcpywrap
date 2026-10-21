import importlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts.pypi_release import missing
from scripts.verify_core_release import upgrade_fixture


class DistributionLayoutTests(unittest.TestCase):
    def test_upgrade_probe_changes_metadata_for_windows_and_unix_newlines(self):
        from email.parser import BytesParser
        with tempfile.TemporaryDirectory() as temp:
            for newline in (b'\r\n', b'\n'):
                wheel = Path(temp)/'source.whl'
                with zipfile.ZipFile(wheel, 'w') as archive:
                    archive.writestr('mcpywrap_core-0.6.0.dist-info/METADATA', newline.join(
                        [b'Metadata-Version: 2.4', b'Name: mcpywrap-core', b'Version: 0.6.0', b'', b'Version: body text']))
                    archive.writestr('mcpywrap_core/_version.py', "__version__ = '0.6.0'\n")
                fixture, version = upgrade_fixture(wheel, temp)
                with zipfile.ZipFile(fixture) as archive:
                    metadata = archive.read('mcpywrap_core-'+version+'.dist-info/METADATA')
                    self.assertEqual(BytesParser().parsebytes(metadata)['Version'], version)
                    self.assertIn(b'Version: body text', metadata)
                    self.assertIn(version.encode(), archive.read('mcpywrap_core/_version.py'))

    def test_native_release_checks_runtime_files_not_compiler_intermediates(self):
        # 真实 MSVC 构建会留下 Loader.obj，不应让正确的发行包验收失败。
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
        self.addCleanup(sys.path.pop, 0)
        import check_release
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = root/'desktop/mcpywrap_assets/window_capture'
            payload.mkdir(parents=True)
            expected = {'manifest.json': b'{}', 'mcpy-window-capture.exe': b'PE'}
            for name, content in {**expected, 'capture.obj': b'intermediate'}.items():
                (payload/name).write_bytes(content)
            for missing in (False, True):
                with zipfile.ZipFile(io.BytesIO(), 'w') as archive:
                    for name, content in expected.items():
                        if missing and name.endswith('.exe'):
                            continue
                        archive.writestr('mcpywrap_assets/window_capture/'+name, content)
                    with patch.object(check_release, 'ROOT', root):
                        if missing:
                            with self.assertRaises(AssertionError):
                                check_release.check_native_payload(archive, 'window_capture')
                        else:
                            check_release.check_native_payload(archive, 'window_capture')

    def test_old_and_new_imports_share_module_class_and_state(self):
        for name in ('api', 'dependencies', 'command_context', 'runtime.deployment', 'builders.project_builder'):
            legacy = importlib.import_module('mcpywrap.'+name)
            core = importlib.import_module('mcpywrap_core.'+name)
            self.assertIs(legacy, core)
        from mcpywrap.api import Core as old
        from mcpywrap_core.api import Core as new
        self.assertIs(old, new)

    def test_partial_release_only_retries_identical_missing_files(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            wheel, sdist = Path(temp)/'core.whl', Path(temp)/'core.tar.gz'
            wheel.write_bytes(b'wheel'); sdist.write_bytes(b'sdist')
            remote = {'urls': [{'filename': wheel.name, 'digests': {'sha256': hashlib.sha256(b'wheel').hexdigest()}}]}
            self.assertEqual(missing([wheel, sdist], remote), [sdist])
            wheel.write_bytes(b'different build')
            with self.assertRaisesRegex(ValueError, 'use a new version'):
                missing([wheel, sdist], remote)

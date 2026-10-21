import importlib
from pathlib import Path
import sys
import tempfile
import unittest

from scripts.pypi_release import missing


class DistributionLayoutTests(unittest.TestCase):
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

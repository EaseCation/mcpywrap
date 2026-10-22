from pathlib import Path
import tempfile
import unittest

from mcpywrap_core.host import HostServices, host_scope
from mcpywrap_core.prepare_environment import inspect_environment, ensure_environment, PrepareError
from mcpywrap_core.git_cache import _source_lock, cache_root
from mcpywrap_core.dependencies import canonical_path


class HostServicesTests(unittest.TestCase):
    def test_git_cache_uses_host_lock_storage_without_moving_source_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            public, private = root/'public-cache', root/'private-locks'
            with host_scope(HostServices(cache_directory=public, lock_directory=private)):
                self.assertEqual(canonical_path(cache_root()), canonical_path(public))
                with _source_lock(public/'origin.lock'):
                    self.assertFalse((public/'origin.lock').exists())
                    self.assertEqual(len(list(private.rglob('service.lock'))), 1)

    def test_custom_environment_still_obeys_shared_version_constraints(self):
        class Provider:
            version = '3.12.0'
            def inspect(self, project, requirements, override):
                return {'state': 'ready', 'python': 'host:project-tools', 'version': self.version}
            ensure = inspect
            def identity(self, record): return {'version': self.version}
        provider = Provider()
        requirements = [{'name': 'generator', 'requires_python': '>=3.11'}]
        with host_scope(HostServices(allow_processes=False, python_executable=None, environment_provider=provider)):
            self.assertEqual(inspect_environment('.', requirements)['state'], 'ready')
            self.assertEqual(ensure_environment('.', requirements)['python'], 'host:project-tools')
            provider.version = '3.9.0'
            with self.assertRaises(PrepareError):
                inspect_environment('.', requirements)

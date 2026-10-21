"""Embedded assembly must not require the desktop file-watching backend."""
import subprocess
import sys
import unittest


class BuilderImportBoundary(unittest.TestCase):
    def test_assembly_imports_without_watchdog_and_preserves_public_exports(self):
        code = '''
import importlib.abc
import sys
class RejectWatcher(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "watchdog" or fullname.startswith("watchdog."):
            raise AssertionError("Assembly imported watchdog")
guard = RejectWatcher()
sys.meta_path.insert(0, guard)
from mcpywrap.builders import AddonProjectBuilder, DependencyManager
from mcpywrap.builders.assembly import assemble_addon
assert "watchdog" not in sys.modules
sys.meta_path.remove(guard)
from mcpywrap.builders import ProjectWatcher, FileWatcher
from mcpywrap.builders.watcher import ProjectWatcher as Original
assert ProjectWatcher is Original
'''
        subprocess.run([sys.executable, '-c', code], check=True)

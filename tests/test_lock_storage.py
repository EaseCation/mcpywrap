import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mcpywrap.utils.locks import directory_lock, lock_storage


class LockStorageTests(unittest.TestCase):
    def test_private_storage_preserves_cross_process_exclusion_and_default(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            public, private = base/'public/resource', base/'private'
            child = '''
import sys
from mcpywrap.utils.locks import directory_lock, lock_storage, LockBusy
try:
    with lock_storage(sys.argv[2]), directory_lock(sys.argv[1]):
        pass
except LockBusy:
    sys.exit(7)
'''
            argv = [sys.executable, '-c', child, str(public.parent/'alias/../resource'), str(private)]
            with lock_storage(private), directory_lock(public):
                self.assertEqual(subprocess.run(argv).returncode, 7)
                self.assertFalse(public.exists())
                self.assertEqual(len(list(private.rglob('service.lock'))), 1)
            self.assertEqual(subprocess.run(argv).returncode, 0)
            with directory_lock(public):
                self.assertTrue((public/'service.lock').exists())

    def test_context_is_restored_after_error(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            with self.assertRaises(RuntimeError):
                with lock_storage(base/'private'):
                    raise RuntimeError('stop')
            with directory_lock(base/'public'):
                self.assertTrue((base/'public/service.lock').is_file())
            self.assertFalse((base/'private').exists())

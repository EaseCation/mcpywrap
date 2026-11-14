"""实例数据目录的共享文件预置：APFS 克隆、已有目标不覆盖、不支持克隆时保持原状。"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from mcpywrap_core.engines import shared_assets


@unittest.skipUnless(sys.platform == 'darwin', 'clonefile is macOS-only')
class Seed(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.game, self.data = root/'game', root/'data'
        (self.game/'assets/assets').mkdir(parents=True)
        self.source = self.game/'assets/assets/vanilla.mcp'
        self.source.write_bytes(b'mcp' * 1000)
        self.installed = self.data/'games/com.netease'

    def test_missing_files_are_cloned_and_stay_independent(self):
        self.assertEqual(shared_assets.seed(self.game, self.data), ['games/com.netease/vanilla.mcp'])
        target = self.installed/'vanilla.mcp'
        self.assertEqual(target.read_bytes(), b'mcp' * 1000)
        self.assertEqual(target.stat().st_nlink, 1)
        target.write_bytes(b'changed')
        self.assertEqual(self.source.read_bytes(), b'mcp' * 1000)
        self.assertEqual([p.name for p in self.installed.iterdir()], ['vanilla.mcp'])

    def test_existing_targets_are_preserved(self):
        self.installed.mkdir(parents=True)
        (self.installed/'vanilla.mcp').write_bytes(b'edited')
        self.assertEqual(shared_assets.seed(self.game, self.data), [])
        self.assertEqual((self.installed/'vanilla.mcp').read_bytes(), b'edited')

    def test_unsupported_volume_or_clone_error_leaves_the_launcher_to_copy(self):
        for outcome in (lambda source, target: False, OSError(5, 'io')):
            with self.subTest(outcome=outcome), patch.object(shared_assets, 'clone', side_effect=outcome):
                self.assertEqual(shared_assets.seed(self.game, self.data), [])
                self.assertEqual(list(self.installed.iterdir()), [])

    def test_missing_engine_source_is_skipped(self):
        self.assertEqual(shared_assets.seed(self.game/'absent', self.data), [])
        self.assertFalse(self.data.exists())


if __name__ == '__main__':
    unittest.main()

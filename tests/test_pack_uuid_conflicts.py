import json
import shutil
import tempfile
from pathlib import Path
import unittest
from mcpywrap.builders.AddonsPack import AddonsPack
from mcpywrap.mcstudio.symlinks import create_symlinks, pack_uuid_conflict
from test_local_dependencies import addon


class PackUUIDConflicts(unittest.TestCase):
    def test_old_global_copy_rejected_without_removing_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = addon(root, 'source')
            old = root / 'engine/behavior_packs/old'
            shutil.copytree(source / 'behavior_pack', old)
            packs = [AddonsPack('source', source)]
            self.assertIn('UUID', pack_uuid_conflict(root / 'engine', packs))
            self.assertFalse(create_symlinks(root / 'engine', packs)[0])
            self.assertTrue((old / 'manifest.json').exists())
            self.assertEqual(list(old.parent.iterdir()), [old])

    def test_two_selected_copies_rejected_but_same_source_reusable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = addon(root, 'source')
            copy = root / 'copy'
            shutil.copytree(source, copy)
            packs = [AddonsPack('a', source), AddonsPack('b', copy)]
            self.assertIn('UUID', pack_uuid_conflict(root / 'engine', packs))
            self.assertIsNone(pack_uuid_conflict(root / 'engine', packs[:1]))

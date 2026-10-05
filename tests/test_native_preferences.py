"""Preferences are user-scoped; native instance files retain unrelated fields."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from mcpywrap.engines.preferences import NativePreferences, read_properties, write_properties


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = self.root/'project'
        self.shared = self.root/'user/preferences/macos'

    def instance(self, name, project=None):
        project = project or self.project
        data = project/'.runtime/macos/instances'/name/'data'
        return NativePreferences(project, data, self.shared)

    def write_game(self, prefs, values):
        write_properties(prefs.files[0].local, values, ':')

    def test_new_instance_and_other_project_inherit_only_preferences(self):
        first = self.instance('one')
        self.write_game(first, {'audio_main':'0.25','gfx_guiscale_offset':'-1','game_difficulty_new':'3',
                                'last_xuid':'private','script_debugger_passcode':'private','game_language':'zh_CN'})
        write_properties(first.files[1].local, {'enable_fps_hud':'1','vsync':'false'}, '=')
        first.prepare();first.sync(force=True)
        second = self.instance('two', self.root/'another-project')
        self.write_game(second, {'game_difficulty_new':'0','last_xuid':'other'})
        second.prepare()
        self.assertEqual(read_properties(second.files[0].local, ':'), {
            'audio_main':'0.25','gfx_guiscale_offset':'-1','game_difficulty_new':'0',
            'last_xuid':'other','game_language':'zh_CN'})
        self.assertEqual(read_properties(second.files[1].local, '=')['enable_fps_hud'],'1')
        shared = (self.shared/'options.txt').read_text()
        self.assertNotIn('private',shared);self.assertNotIn('difficulty',shared)

    def test_concurrent_sessions_merge_changed_keys_not_stale_whole_files(self):
        first = self.instance('one');self.write_game(first, {'audio_main':'1','gfx_guiscale_offset':'0'})
        first.prepare()
        second = self.instance('two').prepare()
        self.write_game(second, {'audio_main':'.2','gfx_guiscale_offset':'0'})
        second.sync(force=True)
        self.write_game(first, {'audio_main':'1','gfx_guiscale_offset':'-1'})
        first.sync(force=True)
        self.assertEqual(read_properties(self.shared/'options.txt',':'), {'audio_main':'.2','gfx_guiscale_offset':'-1'})
        # An engine save that replaces options.txt must not break future imports.
        third = self.instance('three').prepare()
        self.assertEqual(read_properties(third.files[0].local,':')['audio_main'],'.2')

    def test_same_instance_restart_uses_shared_changes_without_losing_private_fields(self):
        first=self.instance('one');self.write_game(first, {'audio_main':'1','mp_username':'one'})
        first.prepare()
        other=self.instance('two').prepare();self.write_game(other, {'audio_main':'.3'})
        other.sync(force=True)
        first=self.instance('one').prepare()
        self.assertEqual(read_properties(first.files[0].local,':'),{'audio_main':'.3','mp_username':'one'})

    def test_first_adoption_migrates_existing_project_files(self):
        old=self.instance('old')
        self.write_game(old, {'audio_main':'.4','game_difficulty_new':'3'})
        new=self.instance('new').prepare()
        self.assertEqual(read_properties(new.files[0].local,':'),{'audio_main':'.4'})

    def test_partial_native_write_does_not_delete_or_export_truncated_value(self):
        first=self.instance('one');self.write_game(first, {'audio_main':'0.5'})
        first.prepare()
        first.files[0].local.write_text('audio_main:0.')
        first.sync(force=True)
        self.assertEqual(read_properties(self.shared/'options.txt',':')['audio_main'],'0.5')
        self.write_game(first, {'audio_main':'0.2'})
        first.sync(force=True)
        self.assertEqual(read_properties(self.shared/'options.txt',':')['audio_main'],'0.2')

    def test_exit_flushes_without_waiting_for_poll_interval(self):
        first=self.instance('one').prepare();first.sync(force=True)
        self.write_game(first, {'audio_main':'.6'})
        first.sync()
        self.assertFalse((self.shared/'options.txt').exists())
        first.sync(force=True)
        self.assertEqual(read_properties(self.shared/'options.txt',':')['audio_main'],'.6')


if __name__=='__main__':unittest.main()

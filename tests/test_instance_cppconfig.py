"""Instance recipes retain settings while saves retain the current game state."""
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from click.testing import CliRunner
from mcpywrap.cli import cli
from mcpywrap.mcstudio import runtime_cppconfig as cfg
from mcpywrap.engines.windows import WindowsBackend
from mcpywrap.engines.macos import MacOSBackend
from mcpywrap.minecraft.level_dat import BedrockNBT


class ConfigTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root/'world.cppconfig'

    def prepare(self, **kwargs):
        return cfg.prepare_cppconfig(self.path, '3.10', 'project', 'world', '/studio', 'addon',
                                     ['/new-behavior'], ['/new-resource'], **kwargs)

    def test_settings_survive_refresh_but_generated_paths_do_not(self):
        first = self.prepare(settings={'world_info': {'name': 'Survival', 'difficulty': 3,
            'game_type': 0, 'seed': '987', 'cheat_info': {'keep_inventory': False}}})
        first['world_info']['behavior_packs'] = ['/stale']
        cfg.write_cppconfig(self.path, first)
        second = self.prepare()
        self.assertEqual(second['world_info']['name'], 'Survival')
        self.assertEqual(second['world_info']['difficulty'], 3)
        self.assertFalse(second['world_info']['cheat_info']['keep_inventory'])
        self.assertEqual(second['world_info']['behavior_packs'], ['/new-behavior'])
        with self.assertRaises(ValueError):self.prepare(settings={'world_info': {'difficulty': 0}})

    def test_import_never_reuses_identity_packs_or_auth(self):
        source = cfg.gen_runtime_config('3.9', 'template', 'other', '/other', 'other', ['stale'], [])
        source['skin_info']['token'] = 'private'
        result = self.prepare(settings=source)
        self.assertEqual(result['world_info']['level_id'], 'world')
        self.assertEqual(result['world_info']['behavior_packs'], ['/new-behavior'])
        self.assertNotIn('token', result['skin_info'])
        self.assertEqual(result['version'], '3.10')

    def test_save_overrides_transient_launch_only_and_is_never_written(self):
        recipe = self.prepare(settings={'world_info': {'difficulty': 3, 'game_type': 0}})
        before = self.path.read_bytes()
        saved = self.root/'level.dat'
        nbt = BedrockNBT.create_new('In game', game_type=1, generator=2)
        nbt.set_value('Difficulty', 1)
        nbt.set_value('RandomSeed', 123)
        nbt.set_value('bonusChestEnabled', True)
        nbt.set_value('playerPermissionsLevel', 2)
        nbt.save_file(str(saved))
        save_bytes = saved.read_bytes()
        launch = cfg.for_saved_world(recipe, saved)
        self.assertEqual(launch['world_info']['difficulty'], 1)
        self.assertEqual(launch['world_info']['world_type'], 2)
        self.assertEqual(launch['world_info']['seed'], '123')
        self.assertTrue(launch['world_info']['bonus_items'])
        self.assertEqual(launch['world_info']['permission_level'], 2)
        self.assertEqual(recipe['world_info']['difficulty'], 3)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(saved.read_bytes(), save_bytes)
        saved.write_bytes(b'broken')
        with self.assertRaises(ValueError):cfg.for_saved_world(recipe, saved)

    def test_invalid_values_and_identity_fail_without_replacing_file(self):
        for info in ({'name': ''}, {'difficulty': True}, {'world_type': 10}, {'seed': 123},
                     {'cheat_info': {'mob_spawn': 'false'}}, {'cheat_info': {'typo': True}}):
            with self.assertRaises(ValueError):self.prepare(settings={'world_info': info})
            self.assertFalse(self.path.exists())
        first = self.prepare();first['world_info']['level_id'] = 'different'
        cfg.write_cppconfig(self.path, first);before = self.path.read_bytes()
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(self.path.read_bytes(), before)

    def test_cli_uses_same_instance_options_contract_on_both_platforms(self):
        (self.root/'pyproject.toml').write_text('[project]\nname="test"\nversion="0.0.0"\n')
        source = self.root/'template.cppconfig';source.write_text('{"world_info":{"difficulty":3,"world_type":2}}')
        args = ['--local', '--non-interactive', '--project', str(self.root), 'run', '--new', '--detach',
                '--cppconfig', str(source), '--json']
        for backend in (WindowsBackend(), MacOSBackend()):
            with patch('mcpywrap.engines.backend.get_backend', return_value=backend), \
                    patch.object(backend, 'run', return_value={'session':'test'}) as run:
                result = CliRunner().invoke(cli, args)
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(run.call_args.kwargs['world_config']['world_info'], {'difficulty':3,'world_type':2})
                result = CliRunner().invoke(cli, [arg for arg in args if arg != '--new'])
                self.assertNotEqual(result.exit_code, 0)
                self.assertEqual(run.call_count, 1)

    def test_direct_cli_values_override_template_without_becoming_engine_options(self):
        from mcpywrap.commands.run_cmd import run_cmd, WORLD_CHOICES
        (self.root/'pyproject.toml').write_text('[project]\nname="test"\nversion="0.0.0"\n')
        template = self.root/'template.cppconfig'
        template.write_text('{"world_info":{"difficulty":0,"seed":"template","cheat_info":{"keep_inventory":true,"mob_spawn":false}}}')
        backend = WindowsBackend()
        with patch('mcpywrap.engines.backend.get_backend', return_value=backend), \
                patch.object(backend, 'run', return_value={'session':'test'}) as run:
            result = CliRunner().invoke(cli, ['--local','--non-interactive','--project',str(self.root),
                'run','--new','--detach','--cppconfig',str(template),'--world-type','flat',
                '--game-type','survival','--difficulty','hard','--permission-level','operator',
                '--world-name','test world','--seed','0','--no-cheats','--bonus-items','--start-with-map',
                '--no-keep-inventory','--random-tick-speed','0','--json'])
        self.assertEqual(result.exit_code, 0, result.output)
        info = run.call_args.kwargs['world_config']['world_info']
        self.assertEqual(info['difficulty'],3)
        self.assertEqual(info['seed'],'0')
        self.assertFalse(info['cheat'])
        self.assertFalse(info['cheat_info']['keep_inventory'])
        self.assertFalse(info['cheat_info']['mob_spawn'])
        self.assertEqual(info['cheat_info']['random_tick_speed'],0)
        self.assertFalse(any(key.startswith('world_') for key in run.call_args.kwargs['overrides']))
        destinations = {param.name for param in run_cmd.params}
        for key in cfg.RULE_LABELS:
            self.assertIn('world_rule_'+key,destinations)

    def test_macos_rejects_unverified_options_before_installation(self):
        with patch('mcpywrap.engines.macos.run') as launch:
            with self.assertRaises(ValueError):
                MacOSBackend().run(self.root, new=True, world_config={
                    'world_info': {'cheat_info': {'experimental_holiday': True}}})
        launch.assert_not_called()

    def test_macos_uses_cppconfig_instead_of_duplicate_world_and_pack_arguments(self):
        from mcpywrap.engines import macos
        app = self.root/'app';helper = app/'Contents/Resources/launcher/run_netease_dev.py'
        helper.parent.mkdir(parents=True);helper.touch()
        data = {'launch': {'runtime':str(app),'game':'/game','data':'/data','cache':'/cache',
                          'cppconfig':str(self.path)}, 'engine_log_path':'/log'}
        process = Mock(pid=999);process.poll.return_value = None
        with patch.object(macos.install, 'read_json', return_value={'addon_link_protocol':1}), \
                patch.object(macos.subprocess, 'Popen', return_value=process) as popen, \
                patch('mcpywrap.mcstudio.processes.identity', return_value={'executable':'/bin/mcpelauncher-client'}):
            self.assertIs(macos.launch_session(data), process)
        command = popen.call_args.args[0]
        self.assertIn('--cppconfig', command)
        for flag in ('--world-id','--world-name','--source-addon'):self.assertNotIn(flag, command)


if __name__ == '__main__':unittest.main()

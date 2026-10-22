"""Window policy survives CLI routing/lifecycle and never falls back to activation."""
import contextlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from click.testing import CliRunner
from mcpywrap_core.cli import cli
from mcpywrap_core.engines.host import EngineError
from mcpywrap_core.runtime import window_policy as policy
from mcpywrap_core.mcstudio import sessions, screenshot


class WindowPolicyTests(unittest.TestCase):
    def test_auto_policy_and_explicit_overrides(self):
        with patch('mcpywrap_core.command_context.non_interactive', return_value=False), \
                patch('mcpywrap_core.command_context.json_output', return_value=False):
            self.assertFalse(policy.resolve_background())
            self.assertTrue(policy.resolve_background(no_gui=True))
            self.assertTrue(policy.resolve_background(detach=True))
            self.assertFalse(policy.resolve_background(False, no_gui=True, detach=True))
            self.assertTrue(policy.resolve_background(True))
        with patch('mcpywrap_core.command_context.non_interactive', return_value=True):
            self.assertTrue(policy.resolve_background())
        with patch('mcpywrap_core.command_context.non_interactive', return_value=False), \
                patch('mcpywrap_core.command_context.json_output', return_value=True):
            self.assertTrue(policy.resolve_background())

    def test_cli_resolves_user_flags_before_internal_ui_detach(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'pyproject.toml').write_text('[project]\nname="window-test"\n', encoding='utf8')
            backend = Mock(capabilities=('project-ui',), managed_install=False)
            backend.run.return_value = {'session': 'a'*32, 'state': 'running'}
            runner = CliRunner()
            with patch('mcpywrap_core.engines.backend.get_backend', return_value=backend), \
                    patch('mcpywrap_core.command_context.non_interactive', return_value=False), \
                    patch('mcpywrap_core.ui.run_session.show_session_window'):
                for flags, expected in (([], False), (['--background'], True),
                                        (['--no-gui'], True), (['--detach'], True),
                                        (['--no-gui', '--foreground'], False)):
                    with self.subTest(flags=flags):
                        result = runner.invoke(cli, ['--local', '--project', str(root), 'run', *flags])
                        self.assertEqual(result.exit_code, 0, result.output)
                        self.assertIs(backend.run.call_args.kwargs['background'], expected)
            with patch('mcpywrap_core.engines.backend.get_backend', return_value=backend):
                result = runner.invoke(cli, ['--local', '--project', str(root), '--non-interactive',
                                             'run', '--detach', '--json'])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertTrue(backend.run.call_args.kwargs['background'])

    def test_connect_default_and_override(self):
        backend = Mock(managed_install=False)
        backend.connect.return_value = {'state': 'running'}
        with patch('mcpywrap_core.engines.backend.get_backend', return_value=backend):
            for flags, expected in (([], True), (['--foreground'], False)):
                result = CliRunner().invoke(cli, ['--local', 'connect', 'localhost', '--detach', '--json', *flags])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertIs(backend.connect.call_args.kwargs['background'], expected)

    def test_session_persists_policy_before_worker_start(self):
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(sessions, '_notify_start'), \
                patch('mcpywrap_core.project_scripts.startup_options', return_value={}), \
                patch('mcpywrap_core.mcstudio.processes.identity', return_value={'pid': 42}), \
                patch.object(sessions.subprocess, 'Popen') as spawn, \
                patch.object(sessions, 'wait_started', side_effect=lambda project, sid, **kw: sessions.read(project, sid)):
            # Read the persisted record without process reconciliation.
            observed = []
            def start(*args, **kwargs):
                record = json.loads(next((Path(temp)/'.runtime/sessions').glob('*/session.json')).read_text())
                observed.append(record['background'])
                raise OSError('test stops before creating a worker')
            spawn.side_effect = start
            with self.assertRaises(EngineError):
                sessions.start(temp, background=True)
            self.assertEqual(observed, [True])

    @unittest.skipUnless(os.name == 'nt', 'Win32 startup structure requires Windows')
    def test_windows_startup_info_and_foreground_path(self):
        from mcpywrap_core.mcstudio import game
        with tempfile.TemporaryDirectory() as temp:
            exe = Path(temp)/'Minecraft.Windows.exe'
            exe.touch()
            engine = SimpleNamespace(executable=str(exe), engine_dir=temp, version='3.10', source='test')
            with patch.object(game, '_launch_message'), patch.object(game.subprocess, 'Popen') as spawn, \
                    patch('mcpywrap_core.mcstudio.window_activation.ActivationGuard') as guard:
                game.open_game(None, engine=engine, background=True, use_system_color=False)
                startup = spawn.call_args.kwargs['startupinfo']
                self.assertEqual(startup.wShowWindow, 4)
                self.assertTrue(startup.dwFlags & game.subprocess.STARTF_USESHOWWINDOW)
                self.assertEqual(spawn.call_args.kwargs['creationflags'], 4)
                guard.return_value.start.assert_called_once_with(spawn.return_value)
                game.open_game(None, engine=engine, background=False, use_system_color=False)
                self.assertIsNone(spawn.call_args.kwargs['startupinfo'])
                self.assertEqual(spawn.call_args.kwargs['creationflags'], 0)
                self.assertEqual(guard.call_count, 1)

    def test_macos_old_runtime_never_silently_activates(self):
        policy.require_native_background({}, False)
        policy.require_native_background({'background_window_protocol': 1}, True)
        with self.assertRaises(EngineError) as error:
            policy.require_native_background({}, True)
        self.assertEqual(error.exception.code, 'background_window_unavailable')

    def test_macos_launch_passes_background_only_when_requested(self):
        from mcpywrap_core.engines import macos
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp)
            helper = app/'Contents/Resources/launcher/run_netease_dev.py'
            helper.parent.mkdir(parents=True)
            helper.touch()
            data = {'mode': 'local', 'engine_log_path': str(app/'engine.log'),
                    'launch': {'runtime': str(app), 'game': temp, 'data': temp, 'cache': temp,
                               'world_id': 'world', 'world_name': 'world', 'packs': temp}}
            with patch.object(macos.install, 'read_json', return_value={'background_window_protocol': 1}), \
                    patch.object(macos.subprocess, 'Popen', return_value=Mock(pid=42, poll=Mock(return_value=None))) as spawn, \
                    patch('mcpywrap_core.mcstudio.processes.identity', return_value={'executable': '/mcpelauncher-client'}):
                data['background'] = True
                macos.launch_session(data)
                self.assertIn('--background', spawn.call_args.args[0])
                data['background'] = False
                macos.launch_session(data)
                self.assertNotIn('--background', spawn.call_args.args[0])

    def test_background_screenshot_cannot_fall_back_to_foreground(self):
        with patch.object(sessions, 'read', return_value={'background': True, 'backend': 'windows'}), \
                patch('mcpywrap_core.mcstudio.window.operate', return_value={}) as operate:
            screenshot.capture('.', 'a'*32)
            self.assertEqual(operate.call_args.args[-1], {'background_only': True})

    def test_background_desktop_input_rejected_before_window_access(self):
        from mcpywrap_core.mcstudio import window
        with patch.object(sessions, 'read', return_value={'background': True}), \
                patch.object(window, 'GameWindow') as target:
            for action in ('key', 'mouse', 'input-sequence'):
                with self.assertRaises(EngineError) as error:
                    window.operate('.', 'a'*32, action, {})
                self.assertEqual(error.exception.code, 'foreground_input_disabled')
            target.assert_not_called()

    def test_restart_keeps_session_policy(self):
        from mcpywrap_core.runtime import groups
        backend = Mock()
        data = {'backend': 'windows', 'mode': 'local', 'level_id': 'world', 'background': True}
        with patch.object(groups, 'membership', return_value=None), \
                patch.object(groups.sessions, 'read', return_value=data), \
                patch.object(groups.sessions, 'stop'), patch.object(groups, 'get_backend', return_value=backend):
            groups.restart('.', session='a'*32)
            self.assertTrue(backend.run.call_args.kwargs['background'])

    def test_group_member_keeps_recipe_policy(self):
        from mcpywrap_core.runtime import groups
        with tempfile.TemporaryDirectory() as temp:
            record = {'project': temp, 'backend': 'windows', 'group': 'b'*32,
                      'recipe': {'background': True}, 'members': [{'role': 'client1', 'state': 'pending', 'session': 'a'*32}]}
            backend = Mock()
            backend.connect.return_value = {'session': 'a'*32, 'state': 'running'}
            with patch.object(groups, 'save'), patch.object(groups, '_cancelled', return_value=False), \
                    patch.object(groups, '_ready'), patch.object(groups, 'get_backend', return_value=backend):
                groups._connect_member(record, 0, target=Mock())
                self.assertTrue(backend.connect.call_args.kwargs['background'])

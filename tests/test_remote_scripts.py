"""Portable Skill clients and bootstrap: no Qt, Windows desktop, real uv install, or network."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'skills/mcpywrap/scripts'/name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RemoteScripts(unittest.TestCase):
    def test_bootstrap_detects_runtime_subcommands(self):
        module = script('bootstrap.py')
        def invoke(args, **kwargs):
            if args[-2:] == ['runtime', '--help']:
                output = 'Commands:\n  py Execute\n  reload Reload\n  watch Watch\n'
            elif args[-2:] == ['run', '--help']:
                output = '--detach --no-gui'
            elif args[-2:] == ['connect', '--help']:
                output = '--detach'
            elif args[-2:] == ['doctor', '--capabilities']:
                output = '{"ok":true,"execution":"local"}'
            else:
                output = '--project --non-interactive --json status logs stop package\n  connect Connect\n  runtime Control\n'
            return Mock(returncode=0, stdout=output, stderr='')
        with patch.object(module, 'invoke', side_effect=invoke):
            result = module.capabilities('mcpy', local=True)
        self.assertTrue({'runtime', 'py', 'reload', 'watch'} <= set(result['capabilities']))

    def test_window_wrapper_preserves_command_arguments_and_remote(self):
        module = script('game_window.py')
        with patch.object(module.subprocess, 'run', return_value=Mock(returncode=0, stdout='{"ok":true}', stderr='')) as run, \
                redirect_stdout(io.StringIO()) as output:
            code = module.main(['--project', '/中文 project', '--session', 'a'*32, '--command', '/custom mcpy',
                                '--remote', 'http://windows:18765', 'mouse', 'click', '--x', '10', '--y', '20',
                                '--width', '800', '--height', '600'])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())['ok'])
        command = run.call_args.args[0]
        self.assertEqual(command[0], '/custom mcpy')
        self.assertEqual(command[command.index('--remote')+1], 'http://windows:18765')
        self.assertIn('mouse', command)
        self.assertIn('click', command)
        self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_smoke_remote_uses_public_cli_and_stops_only_own_session(self):
        module = script('smoke.py')
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            self.assertEqual(command[command.index('--remote')+1], 'http://windows:18765')
            result = {'ok': True}
            if 'connect' in command:
                result.update(session='owned', log_path='Windows/game.log')
            elif 'logs' in command:
                result.update(text='SERVER_READY 中文')
            return Mock(returncode=0, stdout=json.dumps(result), stderr='')
        with patch.object(module.subprocess, 'run', side_effect=run), redirect_stdout(io.StringIO()) as output:
            code = module.main(['--project', '.', '--remote', 'http://windows:18765', '--connect', 'server.local',
                                '--mcs-auth', '--expect-log', 'SERVER_READY'])
        data = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(data['stopped'])
        self.assertEqual(data['verified'], 'log-markers')
        self.assertEqual(calls[-1][calls[-1].index('--session')+1], 'owned')
        self.assertNotIn('package', sum(calls, []))

    def test_bootstrap_keeps_local_and_remote_capabilities_separate(self):
        module = script('bootstrap.py')
        def invoke(args, **kwargs):
            if '--capabilities' in args:
                return Mock(returncode=0, stdout=json.dumps({'ok': True, 'execution': 'remote',
                    'capabilities': ['network-sessions', 'screenshot', 'mcs-auth'],
                    'mcs_auth': {'component_available': True}}))
            if '--json' in args:
                self.assertIn('--local', args)
                return Mock(returncode=1, stdout='{"ok":false,"mcs_auth":{"component_available":false}}')
            if 'run' in args:
                text = '--detach --no-gui --mcs-auth'
            elif 'doctor' in args:
                text = '--mcs-auth --capabilities'
            elif 'connect' in args:
                text = '--detach'
            else:
                text = '--local --remote --project --non-interactive --json status logs stop package\n  connect game\n  screenshot image'
            return Mock(returncode=0, stdout=text)
        with patch.object(module, 'invoke', side_effect=invoke):
            result = module.capabilities('mcpy', 'http://windows:18765')
        self.assertFalse(result['mcs_auth']['component_available'])
        self.assertTrue(result['remote']['mcs_auth']['component_available'])
        self.assertIn('package', result['local_capabilities'])
        self.assertNotIn('package', result['remote']['capabilities'])

    def test_existing_install_is_reused_without_installing_and_remote_auth_can_satisfy_requirement(self):
        module = script('bootstrap.py')
        with tempfile.TemporaryDirectory() as tmp:
            command = Path(tmp)/('mcpy.exe' if os.name == 'nt' else 'mcpy')
            command.touch()
            calls = []
            def invoke(args, **kwargs):
                calls.append(args)
                return Mock(returncode=0, stdout=tmp if 'dir' in args else 'mcpy, version fixture')
            detected = {'capabilities': ['package'], 'local_capabilities': ['package'],
                        'mcs_auth': {'component_available': False},
                        'remote': {'ok': True, 'capabilities': ['mcs-auth'], 'mcs_auth': {'component_available': True}}}
            with patch.object(module.shutil, 'which', return_value='uv'), patch.object(module, 'invoke', side_effect=invoke), \
                    patch.object(module, 'capabilities', return_value=detected), redirect_stdout(io.StringIO()) as output:
                code = module.main(['--require-capability', 'mcs-auth'])
            self.assertEqual(code, 0, output.getvalue())
            self.assertNotIn('install', sum(calls, []))

    def test_host_bootstrap_local_overrides_endpoint_and_reports_serve(self):
        module = script('bootstrap.py')
        calls = []
        def invoke(args, **kwargs):
            calls.append(args)
            if '--json' in args:
                self.assertIn('--local', args)
                self.assertNotIn('--remote', args)
                return Mock(returncode=0, stdout='{"ok":true,"execution":"local","mcs_auth":{"component_available":true}}')
            if 'run' in args:
                text = '--detach --no-gui --mcs-auth'
            elif 'doctor' in args:
                text = '--mcs-auth --capabilities'
            else:
                text = '--local --remote --project --non-interactive --json status logs stop package\n  serve LAN host'
            return Mock(returncode=0, stdout=text)
        with patch.object(module, 'invoke', side_effect=invoke), patch.dict(os.environ, {'MCPY_REMOTE': 'http://unrelated:1'}):
            result = module.capabilities('mcpy', 'http://ignored:2', local=True)
        self.assertIsNone(result['remote'])
        self.assertEqual('serve' in result['local_capabilities'], os.name == 'nt')

    def test_macos_cli_flags_do_not_claim_local_game_execution(self):
        module = script('bootstrap.py')
        def invoke(args, **kwargs):
            if '--json' in args:
                return Mock(returncode=0, stdout='{"ok":true,"execution":"local"}')
            if 'run' in args:
                text = '--detach --no-gui --mcs-auth'
            elif 'connect' in args:
                text = '--detach'
            elif 'doctor' in args:
                text = '--capabilities --mcs-auth'
            else:
                text = '--local --remote --project --non-interactive --json status logs stop package\n  connect game\n  screenshot image\n  serve LAN'
            return Mock(returncode=0, stdout=text)
        with patch.object(module, 'invoke', side_effect=invoke), patch.object(module.os, 'name', 'posix'):
            result = module.capabilities('mcpy', local=True)
        self.assertIn('network-sessions', result['capabilities'])
        self.assertNotIn('network-sessions', result['local_capabilities'])
        self.assertNotIn('serve', result['local_capabilities'])
        self.assertIn('remote-client', result['local_capabilities'])


if __name__ == '__main__':
    unittest.main()

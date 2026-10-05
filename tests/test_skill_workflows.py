"""Exercise skill helpers through their public CLI boundary, without installing or launching games."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from mcpywrap.mcstudio import bridge_assets
from mcpywrap.mcstudio.log_protocol import TextLogDecoder
from mcpywrap.mcstudio.private_logs import EngineLogCapture

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('skill_smoke', ROOT/'skills/mcpywrap/scripts/smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class SmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifact = self.root/'test.zip'
        self.artifact.touch()
        self.calls = []

    def run_script(self, *args, text='LOADED', state='running', fail_log=False, clock=None, probe_state='completed', queued_ready=False):
        def invoke(command, **kwargs):
            self.calls.append(command)
            self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
            self.assertIn('--non-interactive', command)
            self.assertEqual(command[-1], '--json')
            operation = command[4]
            result = {'ok': True}
            if operation == 'package':
                result['artifact'] = str(self.artifact)
            elif operation in ('run', 'connect'):
                result.update(session='owned-session', log_path='game.log', engine_log_path='engine.log')
            elif operation == 'runtime':
                if 'capabilities' in command:
                    result.update(python={'client_queue': True})
                elif 'py-result' in command:
                    result.update(state='completed', side='client', value=True)
                elif '--file' in command:
                    result.update(ok=probe_state == 'completed', state=probe_state,
                                  side=command[command.index('--side')+1], value='probe-ok')
                else:
                    result.update(state='queued' if queued_ready else 'completed', side='client',
                                  value=True, request_id='c'*32)
            elif operation == 'logs':
                if fail_log:
                    raise OSError('log failure')
                result['text'] = text
            elif operation == 'status':
                result['state'] = state
            if operation in ('logs', 'status', 'stop'):
                self.assertEqual(command[command.index('--session')+1], 'owned-session')
            return Mock(returncode=0, stdout=json.dumps(result), stderr='')
        output = io.StringIO()
        with patch.object(smoke.subprocess, 'run', side_effect=invoke), redirect_stdout(output):
            if clock:
                with patch.object(smoke.time, 'monotonic', side_effect=clock):
                    code = smoke.main(['--project', str(self.root), *args])
            else:
                code = smoke.main(['--project', str(self.root), *args])
        return code, json.loads(output.getvalue())

    def test_anonymous_default_packages_without_launch(self):
        code, data = self.run_script()
        self.assertEqual(code, 0)
        self.assertEqual([c[4] for c in self.calls], ['doctor', 'package'])
        self.assertEqual(data['artifact'], str(self.artifact))

    def test_local_auth_passed_only_to_launch_and_cleanup(self):
        code, data = self.run_script('--game', '--mcs-auth', '--expect-log', 'LOADED')
        self.assertEqual(code, 0)
        self.assertTrue(data['stopped'])
        self.assertEqual(data['verified'], 'log-markers')
        self.assertEqual([c[4] for c in self.calls if '--mcs-auth' in c], ['run'])
        launch = next(c for c in self.calls if c[4] == 'run')
        self.assertIn('--new', launch)
        self.assertIn('--detach', launch)

    def test_network_ignores_project_and_reuses_log_verification(self):
        code, data = self.run_script('--connect', 'localhost', '--port', '20000', '--mcs-auth',
                                     '--expect-log', 'LOAD', '--expect-log', 'DED')
        self.assertEqual(code, 0)
        self.assertTrue(data['stopped'])
        self.assertEqual(self.calls[0][4:9], ['connect', 'localhost', '--port', '20000', '--detach'])
        self.assertNotIn('package', [c[4] for c in self.calls])
        self.assertNotIn('doctor', [c[4] for c in self.calls])
        self.assertNotIn('connection_verified', data)

    def test_no_marker_claims_only_process_start(self):
        code, data = self.run_script('--connect', 'localhost')
        self.assertEqual(code, 0)
        self.assertEqual(data['verified'], 'process-started')
        self.assertTrue(data['stopped'])

    def test_timeout_exit_and_log_failure_always_stop_owned_session(self):
        for options in ({'text': '', 'state': 'exited'}, {'fail_log': True}, {'clock': [0, 91]}):
            with self.subTest(options=options):
                code, data = self.run_script('--connect', 'localhost', '--expect-log', 'LOADED', **options)
                self.assertEqual(code, 1)
                self.assertTrue(data['stopped'])
                self.assertEqual(self.calls[-1][4], 'stop')

    def test_dual_side_headless_probes_execute_once_and_cleanup(self):
        script = self.root/'probe.py'
        script.write_text("assert True")
        code, data = self.run_script('--game', '--client-file', str(script), '--server-file', str(script))
        self.assertEqual(code, 0)
        probes = [c for c in self.calls if '--file' in c]
        self.assertEqual(len(probes), 2)
        self.assertEqual([p[p.index('--side')+1] for p in probes], ['client', 'server'])
        self.assertTrue(data['stopped'])
        self.assertEqual(data['verified'], 'python-probes')
        launch = next(c for c in self.calls if c[4] == 'run')
        self.assertIn('--no-gui', launch)
        self.assertIn('--detach', launch)

    def test_cold_start_queries_pending_readiness_without_resubmission(self):
        script = self.root/'probe.py'
        script.write_text('assert True')
        code, data = self.run_script('--game', '--client-file', str(script), queued_ready=True)
        self.assertEqual(code, 0)
        self.assertTrue(data['stopped'])
        self.assertEqual(len([c for c in self.calls if '--code' in c]), 1)
        self.assertEqual(len([c for c in self.calls if 'py-result' in c]), 1)
        self.assertEqual(len([c for c in self.calls if '--file' in c]), 1)

    def test_unknown_probe_is_not_retried_and_game_is_closed(self):
        script = self.root/'probe.py'
        script.write_text("side_effect()")
        code, data = self.run_script('--game', '--client-file', str(script), probe_state='unknown')
        self.assertEqual(code, 1)
        self.assertTrue(data['stopped'])
        self.assertEqual(len([c for c in self.calls if '--file' in c]), 1)
        self.assertEqual(data['probes']['client']['state'], 'unknown')

    def test_auth_without_launch_is_usage_error(self):
        with patch.object(smoke.subprocess, 'run') as invoke, self.assertRaises(SystemExit) as error:
            smoke.main(['--project', str(self.root), '--mcs-auth'])
        self.assertEqual(error.exception.code, 2)
        invoke.assert_not_called()


class BridgeInspection(unittest.TestCase):
    def test_source_install_without_payload_is_readonly(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'MCPY_MCS_BRIDGE_DIR': ''}), \
                patch.object(bridge_assets, 'PAYLOAD', Path(tmp)/'package'), \
                patch.object(bridge_assets.Path, 'home', return_value=Path(tmp)), \
                patch.object(bridge_assets, 'bridge_directory') as install:
            result = bridge_assets.inspect_bridge()
            self.assertFalse(result['component_available'])
            self.assertFalse(list(Path(tmp).iterdir()))
            install.assert_not_called()

    def test_developer_override_reports_files_not_trust_or_login(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'MCPY_MCS_BRIDGE_DIR': tmp}):
            for name in bridge_assets.BINARIES:
                (Path(tmp)/name).touch()
            result = bridge_assets.inspect_bridge()
            self.assertTrue(result['component_available'])
            self.assertFalse(result['trust_verified'])
            self.assertFalse(result['login_verified'])
            self.assertFalse(result['integrity_verified'])

    def test_bad_packaged_hash_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'MCPY_MCS_BRIDGE_DIR': ''}), \
                patch.object(bridge_assets, 'PAYLOAD', Path(tmp)):
            (Path(tmp)/'manifest.json').write_text(json.dumps({'files': {
                name: 'invalid' for name in (*bridge_assets.BINARIES, 'publisher.cer')}}))
            for name in (*bridge_assets.BINARIES, 'publisher.cer'):
                (Path(tmp)/name).touch()
            result = bridge_assets.inspect_bridge()
            self.assertFalse(result['component_available'])
            self.assertFalse(result['integrity_verified'])


class BootstrapCapabilities(unittest.TestCase):
    def test_old_new_and_missing_component_installations(self):
        spec = importlib.util.spec_from_file_location('bootstrap_test', ROOT/'skills/mcpywrap/scripts/bootstrap.py')
        bootstrap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bootstrap)
        for modern, ready in ((False, False), (True, False), (True, True)):
            def invoke(args):
                if '--json' in args:
                    data = {'ok': False, 'mcs_auth': {'component_available': ready}}
                    return Mock(stdout=json.dumps(data), returncode=1)
                if 'doctor' in args:
                    text = '--mcs-auth'
                elif 'run' in args:
                    text = '--detach --no-gui' + (' --mcs-auth' if modern else '')
                elif 'connect' in args:
                    text = '--detach --mcs-auth'
                else:
                    text = '--project --non-interactive --json status logs stop package'
                    if modern:
                        text += '\n  connect  network'
                return Mock(stdout=text, returncode=0)
            with patch.object(bootstrap, 'invoke', side_effect=invoke):
                result = bootstrap.capabilities('mcpy')
            self.assertEqual('network-sessions' in result['capabilities'], modern)
            self.assertEqual(result['mcs_auth']['component_available'], ready if modern else None)


class EncodingCompatibility(unittest.TestCase):
    def test_native_logs_multibyte_boundaries_and_redaction(self):
        text = '玩家中文 正在加载\n第二行 😀\n'
        for encoding in ('utf-8', 'gb18030'):
            raw = text.encode(encoding)
            for offset in range(len(raw)+1):
                decoder = TextLogDecoder()
                self.assertEqual(decoder.feed(raw[:offset])+decoder.feed(raw[offset:])+decoder.finish(), text)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'engine.log'
                capture = EngineLogCapture(io.BytesIO(raw), path, ['玩家中文'])
                capture.close()
                self.assertEqual(path.read_text(encoding='utf-8'), text.replace('玩家中文', '<redacted>'))
        # Traditional GBK remains valid input too, including a trailing line without newline.
        decoder = TextLogDecoder()
        self.assertEqual(decoder.feed('中文'.encode('gbk'))+decoder.finish(), '中文')

    def test_json_on_gbk_and_utf8_pipes_keeps_unicode_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = str(Path(tmp)/'中文 空格 😀')
            for encoding in ('gbk', 'utf-8'):
                env = dict(os.environ, PYTHONUTF8='0', PYTHONIOENCODING=encoding)
                commands = [
                    [sys.executable, '-m', 'mcpywrap', '--project', project, 'doctor', '--json'],
                    [sys.executable, str(ROOT/'skills/mcpywrap/scripts/smoke.py'), '--project', project,
                     '--command', str(Path(tmp)/'missing.exe')],
                    [sys.executable, str(ROOT/'skills/mcpywrap/scripts/game_window.py'), '--project', project,
                     '--session', 'a'*32, 'key', '不存在😀'],
                ]
                for command in commands:
                    with self.subTest(encoding=encoding, command=command[1:3]):
                        proc = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, timeout=30)
                        self.assertNotEqual(proc.returncode, 0)
                        data = json.loads(proc.stdout.decode('ascii'))
                        self.assertFalse(data['ok'])
                        self.assertNotIn(b'UnicodeEncodeError', proc.stderr)
                        if 'project' in data:
                            # Windows runners may expose TEMP through an 8.3 path alias.
                            self.assertEqual(data['project'], str(Path(project).resolve()))

    @unittest.skipUnless(shutil.which('powershell'), 'Windows PowerShell 5.1')
    def test_powershell_file_parses_using_native_encoding_rules(self):
        from itertools import chain
        for path in chain((ROOT/'scripts').rglob('*.ps1'), (ROOT/'skills').rglob('*.ps1')):
            # Parser.ParseFile uses Windows PowerShell's BOM/ANSI rules, unlike ReadAllText.
            script = "$tokens=$null; $errors=$null; $null=[System.Management.Automation.Language.Parser]::ParseFile('" + str(path).replace("'", "''") + "',[ref]$tokens,[ref]$errors); if($errors.Count) {exit 1}"
            proc = subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True, timeout=30)
            self.assertEqual(proc.returncode, 0, str(path))


if __name__ == '__main__':
    unittest.main()

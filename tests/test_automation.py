"""公开 CLI、日志与会话身份的行为测试；不启动真实游戏。"""
import importlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from click.testing import CliRunner
from mcpywrap.cli import cli
from mcpywrap.command_context import project_scope, project_dir
from mcpywrap.dependencies import read_project, write_project
from mcpywrap.mcstudio import sessions
from mcpywrap.mcstudio.file_logs import FileLogServer
from mcpywrap.mcstudio.log_protocol import LogDecoder
from mcpywrap.mcstudio.processes import checked_process


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / '中文 项目'
        self.project.mkdir()
        self.runner = CliRunner()

    def call(self, *args):
        result = self.runner.invoke(cli, ['--project', str(self.project), '--non-interactive', *args, '--json'])
        try:
            data = json.loads(result.stdout)
        except ValueError:
            self.fail(result.output)
        return result, data

    def initialize(self):
        result, data = self.call('init', '--name', 'demo', '--type', 'addon')
        self.assertEqual(result.exit_code, 0, result.output)
        return data

    def test_end_to_end_without_chdir(self):
        before = Path.cwd()
        self.initialize()
        result, data = self.call('mod', '--name', 'DemoMod')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue((Path(data['script_dir']) / 'modMain.py').is_file())
        result, data = self.call('package')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(Path(data['artifact']).is_file())
        self.assertEqual(Path.cwd(), before)
        self.assertFalse(any(p.name == '.runtime' for p in self.project.iterdir()))

    def test_init_never_installs_or_overwrites(self):
        with patch('subprocess.run') as run:
            self.initialize()
            run.assert_not_called()
        before = (self.project / 'pyproject.toml').read_bytes()
        result, data = self.call('init', '--name', 'other', '--type', 'addon')
        self.assertEqual(result.exit_code, 1)
        self.assertFalse(data['ok'])
        self.assertEqual((self.project / 'pyproject.toml').read_bytes(), before)

    def test_map_initialization_and_package_without_prompts(self):
        result, data = self.call('init', '--name', 'sample-map', '--type', 'map')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue((self.project / 'level.dat').is_file())
        result, data = self.call('package')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(Path(data['artifact']).is_file())

    def test_noninteractive_arguments_and_gui_boundary(self):
        cases = [('init',), ('add',), ('remove',), ('modsdk',), ('ui',), ('publish',), ('mod',)]
        self.initialize()
        for args in cases:
            with self.subTest(args=args):
                with patch('click.prompt', side_effect=AssertionError('不得等待输入')), patch('click.confirm', side_effect=AssertionError('不得等待输入')):
                    result, data = self.call(*args)
                self.assertNotEqual(result.exit_code, 0, result.output)
                self.assertFalse(data['ok'])
        result, data = self.call('run', '--delete', 'unknown')
        self.assertEqual(result.exit_code, 2)

    def test_global_json_and_parser_errors(self):
        result = self.runner.invoke(cli, ['--json', '--not-an-option'])
        self.assertEqual(result.exit_code, 2)
        self.assertFalse(json.loads(result.stdout)['ok'])
        result = self.runner.invoke(cli, ['--json', '--non-interactive'])
        self.assertEqual(result.exit_code, 2)
        self.assertFalse(json.loads(result.stdout)['ok'])

    def test_failed_build_and_dev_are_nonzero(self):
        for command in ['build', 'dev', 'package', 'edit', 'run', 'sync']:
            with self.subTest(command=command):
                result, data = self.call(command)
                self.assertNotEqual(result.exit_code, 0)
                self.assertFalse(data['ok'])

    def test_interrupt_is_130(self):
        self.initialize()
        module = importlib.import_module('mcpywrap.commands.package_cmd')
        with patch.object(module.AddonProjectBuilder, 'build', side_effect=KeyboardInterrupt):
            result, data = self.call('package')
        self.assertEqual(result.exit_code, 130)
        self.assertFalse(data['ok'])

    def test_mod_rejects_overwrite_and_invalid_identifier(self):
        self.initialize()
        self.call('mod', '--name', 'TestMod')
        result, _ = self.call('mod', '--name', 'TestMod')
        self.assertEqual(result.exit_code, 1)
        result, _ = self.call('mod', '--name', '../wrong')
        self.assertEqual(result.exit_code, 2)

    def test_local_dependency_then_package(self):
        self.initialize()
        dependency = self.root / 'dependency'
        dependency.mkdir()
        from mcpywrap.project_init import initialize_project
        initialize_project(dependency, 'shared', 'addon')
        result, data = self.call('add', '--path', '../dependency')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(data['source'], 'local')
        self.assertTrue(self.call('package')[1]['ok'])
        self.assertTrue(self.call('remove', '--path', '../dependency')[1]['ok'])
        self.assertTrue(dependency.is_dir())

    def test_map_sync_preserves_user_packages(self):
        from mcpywrap.config import update_map_setuptools_config
        (self.project / 'behavior_packs' / 'sample').mkdir(parents=True)
        write_project(self.project, {'tool': {'mcpywrap': {'project_type': 'map'},
                                            'setuptools': {'packages': ['custom', 'behavior_packs.old'],
                                                           'package-dir': {'custom': 'src/custom', 'behavior_packs.old': 'behavior_packs/old'}}}})
        with project_scope(self.project):
            update_map_setuptools_config()
        settings = read_project(self.project)['tool']['setuptools']
        self.assertEqual(settings['packages'], ['custom', 'behavior_packs.sample'])
        self.assertEqual(settings['package-dir']['custom'], 'src/custom')

    def test_sdk_explicit_selection_and_failure(self):
        module = importlib.import_module('mcpywrap.commands.modsdk_cmd')
        with patch.object(module, 'get_available_versions', return_value=['1', '2']), patch.object(module, 'download_and_install_package', return_value=False) as install:
            result, data = self.call('modsdk', '--latest')
            self.assertEqual(result.exit_code, 1)
            install.assert_called_once_with('2', force=True)

    def test_publish_uploads_only_fresh_artifacts(self):
        self.initialize()
        module = importlib.import_module('mcpywrap.commands.publish_cmd')
        called = []

        def process(command, **kwargs):
            called.append(command)
            if command[2] == 'build':
                directory = Path(command[4])
                (directory / 'demo.whl').write_bytes(b'test')
                (directory / 'demo.tar.gz').write_bytes(b'test')
            return Mock(returncode=0, stdout='', stderr='')

        with patch.object(module, 'check_credentials'), patch.object(module.subprocess, 'run', side_effect=process):
            result, data = self.call('publish', '--yes')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(called[0][0], sys.executable)
        self.assertIn('--non-interactive', called[1])
        self.assertEqual(len(called[1][-2:]), 2)
        self.assertTrue(data['published'])

    def test_missing_credentials_does_not_build_or_upload(self):
        import click
        self.initialize()
        module = importlib.import_module('mcpywrap.commands.publish_cmd')
        with patch.object(module, 'check_credentials', side_effect=click.ClickException('凭据不可用')), patch.object(module.subprocess, 'run') as start:
            result, data = self.call('publish', '--yes')
        self.assertEqual(result.exit_code, 1)
        self.assertIn('凭据', data['error'])
        start.assert_not_called()

    def test_scope_restores_project_without_os_chdir(self):
        before = project_dir()
        with project_scope(self.project):
            self.assertEqual(project_dir(), self.project)
        self.assertEqual(project_dir(), before)

    def test_qt_not_loaded_by_core_cli(self):
        proc = subprocess.run([sys.executable, '-B', '-c',
                               'import sys; import mcpywrap.cli; assert not any(k.startswith("PyQt5") for k in sys.modules)'],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class LogAndSessionTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows 文件共享语义')
    def test_session_save_retries_transient_sharing_error(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'session.json'
            replace = os.replace
            calls = []

            def briefly_locked(source, destination):
                calls.append(destination)
                if len(calls) == 1:
                    raise PermissionError('sharing violation')
                replace(source, destination)

            with patch.object(sessions.os, 'replace', side_effect=briefly_locked), patch.object(sessions.time, 'sleep'):
                sessions.save(target, {'state': 'running'})
            self.assertEqual(json.loads(target.read_text())['state'], 'running')
            self.assertEqual(len(calls), 2)

    def test_gbk_log_line_split_across_packets(self):
        decoder = LogDecoder()
        wire = '服务端已加载！\n'.encode('gbk')
        result = ''.join(decoder.feed(bytes([value])) for value in wire)
        self.assertEqual(result, '服务端已加载！\n')

    def test_split_utf8_and_command_frames(self):
        decoder = LogDecoder()
        wire = '加载正常'.encode() + b'\xff' + '{"command":"测试"}'.encode() + b'\xffend'
        decoded = ''.join(decoder.feed(bytes([byte])) for byte in wire) + decoder.finish()
        self.assertIn('加载正常', decoded)
        self.assertIn('测试', decoded)
        self.assertTrue(decoded.endswith('end'))

    def test_file_listener_receives_before_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'game.log'
            server = FileLogServer(path)
            server.start()
            try:
                with socket.create_connection(('127.0.0.1', server.port)) as client:
                    client.sendall('SERVER_LOADED 中文\n'.encode())
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and 'SERVER_LOADED' not in path.read_text(encoding='utf-8'):
                    time.sleep(0.02)
                self.assertIn('中文', path.read_text(encoding='utf-8'))
            finally:
                server.close()

    def test_pid_reuse_refused(self):
        fake = Mock()
        fake.create_time.return_value = 2
        with patch('mcpywrap.mcstudio.processes.psutil.Process', return_value=fake):
            with self.assertRaisesRegex(ValueError, '身份不匹配'):
                checked_process({'pid': 1, 'created_at': 1, 'executable': 'game.exe'})
            fake.terminate.assert_not_called()

    def test_stale_worker_and_idempotent_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            session = uuid.uuid4().hex
            path = sessions.session_path(directory, session)
            path.mkdir(parents=True)
            data = {'session': session, 'state': 'running', 'worker': {'pid': 1}, 'game': {'pid': 2}}
            sessions.save(path / 'session.json', data)
            with patch.object(sessions, 'checked_process', return_value=None):
                self.assertEqual(sessions.read(directory, session)['state'], 'failed')
                self.assertEqual(sessions.stop(directory, session)['state'], 'exited')
            with self.assertRaises(ValueError):
                sessions.session_path(directory, '../bad')

    def test_start_timeout_requests_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sessions.subprocess, 'Popen', return_value=Mock(poll=Mock(return_value=None))):
                with self.assertRaisesRegex(ValueError, '超时'):
                    sessions.start(directory, Path(directory) / 'test.cppconfig', 'test', timeout=0)
            self.assertEqual(len(list(Path(directory).rglob('stop'))), 1)

    def test_worker_listener_ready_before_game_and_failure_cleanup(self):
        from mcpywrap.mcstudio import session_worker as worker
        command = importlib.import_module('mcpywrap.commands.run_cmd')
        with tempfile.TemporaryDirectory() as directory:
            session = uuid.uuid4().hex
            path = sessions.session_path(directory, session)
            path.mkdir(parents=True)
            data = {'state': 'starting', 'game': None, 'config_path': 'fake.cppconfig', 'level_id': 'test',
                    'engine_overrides': {}, 'log_path': str(path / 'game.log')}
            sessions.save(path / 'session.json', data)

            def start_game(*args, **kwargs):
                self.assertTrue(kwargs['no_gui'])
                self.assertNotEqual(kwargs['output_path'], data['log_path'])
                with socket.create_connection(('127.0.0.1', kwargs['logging_port'])) as client:
                    client.sendall(b'EARLY_LOG\n')
                return False, None

            with patch.object(command, '_run_game_with_instance', side_effect=start_game):
                worker.run(directory, session)
            record = json.loads((path / 'session.json').read_text(encoding='utf-8'))
            self.assertEqual(record['state'], 'failed')
            self.assertIn('未成功启动', record['error'])


if __name__ == '__main__':
    unittest.main()

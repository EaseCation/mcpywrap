import importlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mcpywrap.mcstudio import sessions, session_worker
from mcpywrap.mcstudio.discovery import Engine
from mcpywrap.mcstudio.mcs_auth import AuthContext


def context():
    return AuthContext('ABEiM0RVZneImaq7zN3u/w==',
                       {'user_id': '456789', 'user_name': 'fixture', 'urs': 'fixture-account'},
                       'https://auth.example', 'https://web.example', 'https://core.example', 123)


class LocalAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_local_world_saves_only_anonymous_instance_configuration(self):
        run = importlib.import_module('mcpywrap.commands.run_cmd')
        identity = context()
        config = self.root/'.runtime/world.cppconfig'
        transient = self.root/'auth.cppconfig'
        engine = Engine('game', '3.10', 'engine', str(self.root), 'fixture')
        process = Mock()
        def launch(path, **kwargs):
            self.assertEqual(Path(path), transient)
            saved = json.loads(config.read_text(encoding='utf-8'))
            runtime = json.loads(transient.read_text(encoding='utf-8'))
            self.assertEqual(saved['room_info']['token'], '')
            self.assertNotIn('player_info', saved)
            self.assertEqual(runtime['room_info']['token'], identity.token)
            self.assertEqual(runtime['world_info']['level_id'], 'world')
            self.assertTrue(kwargs['capture_output'])
            self.assertNotIn('output_path', kwargs)
            return process
        with patch.object(run, '_setup_dependencies', return_value=[]), \
                patch.object(run, 'discover_engines', return_value=Mock(require_engine=lambda: engine)), \
                patch.object(run, 'require_resources'), patch.object(run, 'get_mcs_game_engine_data_path', return_value=str(self.root)), \
                patch.object(run, 'setup_global_addons_symlinks', return_value=(True, [], [])), \
                patch.object(run, 'open_game', side_effect=launch), patch.object(run, 'open_safaia') as gui:
            success, _ = run._run_game_with_instance(str(config), 'world', [], wait=False, no_gui=True,
                                                    logging_port=54321, auth_context=identity,
                                                    auth_config_path=str(transient))
            self.assertTrue(success)
            gui.assert_not_called()

    def test_session_credentials_use_stdin_not_metadata_or_arguments(self):
        identity = context()
        class CapturedPipe(io.BytesIO):
            def close(self):
                self.captured = self.getvalue()
                super().close()
        pipe = CapturedPipe()
        process = Mock(stdin=pipe)
        def start(args, **kwargs):
            record_path = sessions.session_path(self.root, args[-1])/'session.json'
            data = json.loads(record_path.read_text())
            self.assertNotIn(identity.token, record_path.read_text())
            self.assertNotIn(identity.token, str(args))
            data.update(state='running', game={'pid': 77})
            sessions.save(record_path, data)
            return process
        with patch.object(sessions.subprocess, 'Popen', side_effect=start):
            result = sessions.start(self.root, self.root/'.runtime/world.cppconfig', 'world', auth_context=identity)
        self.assertTrue(result['mcs_auth'])
        self.assertEqual(json.loads(pipe.captured)['token'], identity.token)

    def test_worker_redacts_and_removes_credential_configuration(self):
        identity = context()
        session = 'a'*32
        directory = sessions.session_path(self.root, session)
        directory.mkdir(parents=True)
        metadata = {'state': 'starting', 'game': None, 'mcs_auth': True, 'mcs_pid': 123,
                    'config_path': str(self.root/'.runtime/world.cppconfig'), 'level_id': 'world',
                    'log_path': str(directory/'game.log'), 'engine_overrides': {}}
        sessions.save(directory/'session.json', metadata)
        process = Mock(pid=77, stdout=io.BytesIO(('LoginToken: '+identity.token).encode()))
        process.poll.side_effect = [None, 0]
        process.wait.return_value = 0
        def launch(*args, **kwargs):
            self.assertEqual(kwargs['auth_context'].token, identity.token)
            Path(kwargs['auth_config_path']).write_text(identity.token)
            return True, process
        run = importlib.import_module('mcpywrap.commands.run_cmd')
        with patch.object(run, '_run_game_with_instance', side_effect=launch), \
                patch.object(session_worker, 'identity', side_effect=lambda pid: {'pid': pid}), \
                patch.object(session_worker.sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(json.dumps(identity.to_payload()).encode()))):
            session_worker.run(str(self.root), session)
        self.assertFalse((directory/'auth.cppconfig').exists())
        self.assertEqual(json.loads((directory/'session.json').read_text())['state'], 'exited')
        for path in directory.iterdir():
            if path.is_file():
                self.assertNotIn(identity.token, path.read_text(encoding='utf-8'))
        self.assertIn('<redacted>', (directory/'engine.log').read_text())


if __name__ == '__main__':
    unittest.main()

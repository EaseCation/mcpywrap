"""自定义离线玩家名：身份派生、CLI 校验，以及本地世界、连接服务器、双客户端与远程服务的传递。"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from click.testing import CliRunner

from mcpywrap_core.cli import cli
from mcpywrap_core.engines.host import EngineError
from mcpywrap_core.mcstudio import sessions
from mcpywrap_core.mcstudio.discovery import Engine
from mcpywrap_core.mcstudio.network import ServerTarget
from mcpywrap_core.runtime import groups
from mcpywrap_core.runtime.player_identity import player_identity, requested_players


class IdentityRules(unittest.TestCase):
    def test_identity_is_stable_and_accepts_chinese_names(self):
        for name in ('Steve_1', '测试玩家', '玩家007'):
            first, second = player_identity(name), player_identity(name)
            self.assertEqual(first, second)
            self.assertEqual(first['user_name'], name)
            self.assertTrue(0 < first['user_id'] < 2**31)
        self.assertNotEqual(player_identity('Alpha')['user_id'], player_identity('Beta')['user_id'])

    def test_invalid_names_are_rejected(self):
        for name in ('', 'a b', 'x' * 17, '测' * 17, '中"', "a'b", 'é', 'a\n', None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                player_identity(name)

    def test_one_name_per_client_and_distinct_ignoring_case(self):
        self.assertIsNone(requested_players((), 2))
        self.assertEqual(len(requested_players(('甲', 'Bob'), 2)), 2)
        for names, clients in ((('Alpha',), 2), (('Alpha', 'Beta'), 1), (('Steve', 'steve'), 2)):
            with self.subTest(names=names), self.assertRaises(ValueError):
                requested_players(names, clients)


class CommandValidation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def call(self, *args):
        return CliRunner().invoke(cli, ['--local', '--project', str(self.root), '--non-interactive', *args, '--json'])

    def test_invalid_combinations_fail_before_any_backend_work(self):
        with patch('mcpywrap_core.engines.backend.get_backend') as backend:
            for args in (['connect', 'localhost', '--detach', '--player-name', 'a b'],
                         ['connect', 'localhost', '--detach', '--player-name', 'Alpha', '--mcs-auth'],
                         ['connect', 'localhost', '--detach', '--clients', '2', '--player-name', 'Alpha'],
                         ['run', '--list', '--player-name', 'Alpha']):
                with self.subTest(args=args):
                    result = self.call(*args)
                    self.assertNotEqual(result.exit_code, 0)
                    self.assertIn('--player-name', result.output + (result.stderr if result.stderr_bytes else ''))
            backend.return_value.connect.assert_not_called()
            backend.return_value.run.assert_not_called()


class MacOSIdentity(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        from mcpywrap_core.engines.macos import MacOSBackend
        self.backend = MacOSBackend()
        self.state = {'runtime': str(self.root/'runtime'), 'game': str(self.root/'game'),
                      'profile': {'apk': {'version': '3.10'}}, 'network_connect_protocol': 1,
                      'background_window_protocol': 1, 'developer_identity_protocol': 1, 'runtime_id': 'fixture'}
        for name, value in [('mcpywrap_core.engines.backend.get_backend', self.backend),
                            ('mcpywrap_core.engines.macos.require_macos', {}),
                            ('mcpywrap_core.engines.macos_network.require_macos', {}),
                            ('mcpywrap_core.engines.macos.ensure_runtime', self.state),
                            ('mcpywrap_core.engines.macos.pinned_runtime', self.state),
                            ('mcpywrap_core.engines.install.home', self.root/'resources')]:
            obj = patch(name, return_value=value); obj.start(); self.addCleanup(obj.stop)
        obj = patch.object(sessions, 'start', side_effect=self.start)
        self.start_mock = obj.start(); self.addCleanup(obj.stop)

    def start(self, root, *args, **options):
        return {'session': options.get('session_id') or 'a' * 32, 'project': str(root), 'state': 'running',
                'game': {'pid': 123}, 'log_path': 'game.log', 'engine_log_path': 'engine.log',
                'level_id': None, 'mode': 'network', 'mcs_auth': False, **options}

    def call(self, *args):
        return CliRunner().invoke(cli, ['--local', '--project', str(self.root), '--non-interactive', *args, '--json'])

    def test_connect_applies_the_requested_name(self):
        result = self.call('connect', 'localhost', '--detach', '--player-name', 'Steve_1')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.start_mock.call_args.kwargs['network']['player'], player_identity('Steve_1'))

    def test_chinese_server_name_requires_the_unicode_identity_runtime(self):
        result = self.call('connect', 'localhost', '--detach', '--player-name', '测试玩家')
        self.assertEqual(json.loads(result.stdout)['code'], 'runtime_incompatible')
        self.start_mock.assert_not_called()
        self.state['offline_identity_protocol'] = 1
        result = self.call('connect', 'localhost', '--detach', '--player-name', '测试玩家')
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.start_mock.call_args.kwargs['network']['player']['user_name'], '测试玩家')

    def test_local_world_name_requires_runtime_protocol(self):
        with patch('mcpywrap_core.engines.macos.instances', return_value=[]), \
                patch('mcpywrap_core.runtime.instances.attempt'):
            with self.assertRaises(EngineError) as error:
                self.backend.run(self.root, detach=True, player=player_identity('Steve_1'))
            self.assertEqual(error.exception.code, 'runtime_incompatible')
            self.start_mock.assert_not_called()
            self.state['offline_identity_protocol'] = 1
            self.backend.run(self.root, detach=True, player=player_identity('测试玩家'))
        self.assertEqual(self.start_mock.call_args.kwargs['launch']['player'], player_identity('测试玩家'))

    def launch_command(self, metadata, plan):
        from mcpywrap_core.engines import macos
        app = self.root/'runtime.app'
        helper = app/'Contents/Resources/launcher/run_netease_dev.py'
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.touch()
        data = {'mode': 'local', 'engine_log_path': str(self.root/'engine.log'),
                'launch': dict({'runtime': str(app), 'game': str(self.root/'game'), 'data': str(self.root/'data'),
                                'cache': str(self.root/'cache'), 'cppconfig': str(self.root/'world.cppconfig')}, **plan)}
        process = Mock(pid=os.getpid())
        process.poll.return_value = None
        with patch.object(macos.install, 'read_json', return_value=metadata), \
                patch.object(macos.subprocess, 'Popen', return_value=process) as popen, \
                patch('mcpywrap_core.engines.shared_assets.seed'), \
                patch('mcpywrap_core.mcstudio.processes.identity', return_value={'executable': '/x/mcpelauncher-client'}):
            macos.launch_session(data)
        return popen.call_args.args[0]

    def test_launcher_receives_identity_only_when_requested(self):
        command = self.launch_command({'offline_identity_protocol': 1}, {})
        self.assertNotIn('--player-name', command)
        player = player_identity('测试玩家')
        command = self.launch_command({'offline_identity_protocol': 1}, {'player': player})
        index = command.index('--player-name')
        self.assertEqual(command[index:index + 4], ['--player-name', '测试玩家', '--player-id', str(player['user_id'])])
        with self.assertRaises(EngineError):
            self.launch_command({}, {'player': player})


class WindowsIdentity(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def launched_identity(self, plan=None):
        from runtime_support import launch_world
        engine = Engine('game', '3.10', 'engine', str(self.root), 'fixture')
        captured = {}
        def launch(path, **kwargs):
            captured.update(json.loads(Path(path).read_text(encoding='utf-8')))
            return Mock(pid=os.getpid())
        with patch('mcpywrap_core.runtime.windows.discover_engines', return_value=Mock(require_engine=lambda: engine)), \
                patch('mcpywrap_core.runtime.windows.require_resources'), \
                patch('mcpywrap_core.mcstudio.game.open_game', side_effect=launch), patch('mcpywrap_core.mcstudio.game.open_safaia'):
            launch_world(self.root, self.root/'.runtime/world.cppconfig', 'world', plan=plan)
        saved = json.loads((self.root/'.runtime/world.cppconfig').read_text(encoding='utf-8'))
        self.assertNotIn('player_info', saved)
        return captured['player_info']

    def test_local_world_uses_requested_name_and_keeps_default_otherwise(self):
        self.assertEqual(self.launched_identity()['user_id'], 0)
        player = player_identity('测试玩家')
        self.assertEqual(self.launched_identity({'player': player}), dict(player, urs=''))


class GroupIdentity(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.backend = Mock(id='windows', capabilities=())
        self.backend.connect.side_effect = lambda *args, **kwargs: {'session': kwargs.get('session_id', 'b' * 32),
                                                                     'state': 'running'}

    def test_requested_names_belong_to_roles_and_survive_retries(self):
        players = requested_players(('甲玩家', 'Bob'), 2)
        record = groups._new(self.root, self.backend, 'network', {'overrides': {}}, players)
        with patch.object(groups, 'get_backend', return_value=self.backend), patch.object(groups, '_ready'):
            for index in (0, 1, 1):
                groups._connect_member(record, index, ServerTarget('localhost'))
        sent = [call.kwargs['player'] for call in self.backend.connect.call_args_list]
        self.assertEqual(sent, [players[0], players[1], players[1]])

    def test_default_identities_are_unchanged_without_names(self):
        record = groups._new(self.root, self.backend, 'network', {'overrides': {}})
        with patch.object(groups, 'get_backend', return_value=self.backend), patch.object(groups, '_ready'):
            groups._connect_member(record, 0, ServerTarget('localhost'))
        self.assertTrue(self.backend.connect.call_args.kwargs['player']['user_name'].startswith('mcpy_'))

    def test_single_session_restart_keeps_identity(self):
        player = player_identity('Steve_1')
        session = 'c' * 32
        data = {'session': session, 'mode': 'network', 'backend': 'windows', 'background': False,
                'network': {'target': {'host': 'localhost', 'port': 19132, 'auth': 'none'}, 'player': player}}
        with patch.object(groups, 'membership', return_value=None), patch.object(sessions, 'read', return_value=data), \
                patch.object(sessions, 'stop'), patch.object(groups, 'get_backend', return_value=self.backend):
            groups.restart(self.root, session=session)
        self.assertEqual(self.backend.connect.call_args.kwargs['player'], player)


class RemoteIdentity(unittest.TestCase):
    def test_service_derives_identity_and_rejects_invalid_requests(self):
        from mcpywrap_core.remote import service as api
        from mcpywrap_core.remote.protocol import RemoteError
        with tempfile.TemporaryDirectory() as root:
            game = api.GameService(Path(root))
            started = {}
            def start(project, **kwargs):
                started.update(kwargs)
                return {'session': kwargs['session_id'], 'state': 'running', 'game': None}
            with patch.object(api, 'capabilities', return_value={'desktop': {'available': True}}), \
                    patch.object(api, 'prepare_network', return_value=(Engine('g', '3.10', 'e', 'd', 't'), None)), \
                    patch.object(sessions, 'start', side_effect=start), \
                    patch.object(sessions, 'handoff', side_effect=lambda data: dict(data)):
                game.create({'request_id': 'd' * 32, 'host': 'server.local', 'player_name': '测试玩家'})
                self.assertEqual(started['network']['player'], player_identity('测试玩家'))
                for request in ({'request_id': 'e' * 32, 'host': 'server.local', 'player_name': 'a b'},
                                {'request_id': 'f' * 32, 'host': 'server.local', 'player_name': 'Alpha', 'mcs_auth': True}):
                    with self.subTest(request=request), self.assertRaises(RemoteError):
                        game.create(request)
            game.close()


if __name__ == '__main__':
    unittest.main()

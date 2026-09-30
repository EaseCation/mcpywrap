"""Safaia protocol and session command contracts without a live game."""
import base64
import json
import re
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from click.testing import CliRunner

from mcpywrap.cli import cli
from mcpywrap.mcstudio.hot_reload import reload_code, target_from_file, reload_session
from mcpywrap.mcstudio.runtime_debug import SafaiaChannel, RuntimeControlServer, frame, recv_frame, recv_exact, script_request
from mcpywrap.commands.dev_cmd import changed_reload_targets


class RuntimeDebugTests(unittest.TestCase):
    def test_server_reload_cli_routes_selected_side(self):
        with patch('mcpywrap.mcstudio.hot_reload.reload_session', return_value={'state':'completed'}) as call:
            result=CliRunner().invoke(cli,['--local','runtime','reload','python','--session','a'*32,
                                          '--module','Demo.server','--side','server','--json'])
        self.assertEqual(result.exit_code,0,result.output)
        self.assertEqual(call.call_args.kwargs['side'],'server')
        bad=CliRunner().invoke(cli,['--local','runtime','reload','ui','--session','a'*32,'--side','server','--json'])
        self.assertNotEqual(bad.exit_code,0)

    def test_reload_transport_preserves_server_side(self):
        with patch('mcpywrap.mcstudio.sessions.read',return_value={'mode':'local','game':{'executable':'engine/game.exe'}}), \
             patch('mcpywrap.mcstudio.runtime_debug.control_request',return_value={'state':'completed','value':{'ok':True}}) as request:
            reload_session('.', 'a'*32, 'python', 'Demo.server', source=b'VALUE=2', side='server')
        self.assertEqual(request.call_args.kwargs['side'],'server')

    def test_worker_executes_server_reload_in_server_context(self):
        channel=Mock();channel.execute.return_value={'state':'completed'}
        control=RuntimeControlServer(channel,'test-token');control.start()
        try:
            payload=json.dumps({'token':'test-token','action':'reload','kind':'python','target':'Demo.server',
                                'side':'server','source':base64.b64encode(b'VALUE=2').decode('ascii')}).encode()
            with socket.create_connection(control.server_address,timeout=2) as client:
                client.sendall(struct.pack('!I',len(payload))+payload)
                size=struct.unpack('!I',recv_exact(client,4))[0]
                result=json.loads(recv_exact(client,size))
            self.assertEqual(result['state'],'completed')
            self.assertEqual(channel.execute.call_args.args[1],'server')
        finally:control.close()

    def test_runtime_group_is_public_and_old_commands_are_hidden(self):
        runner = CliRunner()
        root_help = runner.invoke(cli, ['--help']).output
        runtime_help = runner.invoke(cli, ['runtime', '--help']).output
        self.assertIn('  runtime ', root_help)
        self.assertNotIn('  py ', root_help)
        self.assertNotIn('  reload ', root_help)
        for name in ('py', 'reload', 'watch'):
            self.assertIn('  '+name+' ', runtime_help)

    def test_runtime_watch_passes_session_to_build_watcher(self):
        with patch('mcpywrap.commands.dev_cmd.dev_cmd.callback', return_value={'started': True}) as watch:
            result = CliRunner().invoke(cli, ['runtime', 'watch', '--session', 'a'*32, '--json'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(json.loads(result.stdout)['started'])
        watch.assert_called_once_with(reload_session='a'*32)

    def connect(self, channel):
        client = socket.create_connection(('127.0.0.1', channel.port))
        client.settimeout(2)
        client.sendall(frame(3, '{"connect_port":"26613","name":"game"}'))
        kind, payload = recv_frame(client)
        self.assertEqual(kind, 48)
        self.assertEqual(json.loads(payload), {'notify': 'pass'})
        self.assertTrue(channel.connected.wait(2))
        return client

    @staticmethod
    def reply(client, source, value):
        request_id = re.search(r'__MCPY_RESULT_([0-9a-f]{32})__', source).group(1)
        encoded = base64.b64encode(json.dumps({'stdout': 'hello\n', 'stderr': '',
                                               'value': value, 'error': None}).encode('utf-8'))
        marker = ('__MCPY_RESULT_'+request_id+'__').encode('ascii')
        client.sendall(frame(4, b'other log\n'+marker+encoded[:7]))
        client.sendall(frame(4, encoded[7:]+b'\n'))

    def test_handshake_split_result_and_raw_log(self):
        logs = []
        channel = SafaiaChannel(logs.append)
        with patch('mcpywrap.mcstudio.runtime_debug.owned_udp_ports', return_value={26613}), \
                patch('mcpywrap.mcstudio.runtime_debug.owned_udp_endpoints', return_value=set()):
            channel.start(123)
            client = self.connect(channel)
            def game():
                kind, payload = recv_frame(client)
                self.assertEqual(kind, 22)
                self.reply(client, payload.decode('utf-8'), 42)
            worker = threading.Thread(target=game)
            worker.start()
            result = channel.execute('40 + 2')
            worker.join(2)
            client.close()
            channel.close()
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['value'], 42)
        self.assertEqual(result['stdout'], 'hello\n')
        self.assertIn('other log', ''.join(logs))

    def test_timeout_does_not_consume_late_result(self):
        channel = SafaiaChannel(lambda _: None)
        with patch('mcpywrap.mcstudio.runtime_debug.owned_udp_ports', return_value={26613}), \
                patch('mcpywrap.mcstudio.runtime_debug.owned_udp_endpoints', return_value=set()):
            channel.start(123)
            client = self.connect(channel)
            first = channel.execute('1', timeout=.05)
            with self.assertRaisesRegex(ValueError, '上一请求结果未知'):
                channel.execute('2')
            _, payload = recv_frame(client)
            self.reply(client, payload.decode('utf-8'), 1)
            deadline = time.monotonic() + 2
            while channel.pending is not None and time.monotonic() < deadline:
                time.sleep(.01)
            def game():
                _, second = recv_frame(client)
                self.reply(client, second.decode('utf-8'), 2)
            worker = threading.Thread(target=game)
            worker.start()
            second = channel.execute('2')
            worker.join(2)
            client.close()
            channel.close()
        self.assertEqual(first['state'], 'unknown')
        self.assertEqual(second['value'], 2)

    def test_frame_limits_and_python_wrapper(self):
        with self.assertRaises(ValueError):
            frame(22, b'x' * (1024 * 1024 + 1))
        source = script_request('print("hello")', 'a'*32)
        self.assertIn('except SyntaxError:', source)
        self.assertIn('__MCPY_RESULT_'+'a'*32, source)

    def test_reload_paths_and_engine_probes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = root/'resource_pack'
            (pack/'ui').mkdir(parents=True)
            (pack/'manifest.json').write_text('{}')
            target = pack/'ui'/'menu.json'
            target.write_text('{}')
            self.assertEqual(target_from_file(root, 'ui', target), 'menu.json')
            with self.assertRaises(ValueError):
                target_from_file(root, 'shader', target)
        self.assertIn('reload_one_shader', reload_code('shader', 'entity.fragment'))
        self.assertIn('reload_one_material_file', reload_code('material', 'x.material'))
        self.assertIn('_particle_system.load', reload_code('particle', 'x.json'))
        self.assertIn('exec compile(', reload_code('python', 'MyMod.logic', b'VALUE = 1\n'))

    def test_watch_batch_keeps_each_module_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp)/'behavior_pack'
            (pack/'MyMod').mkdir(parents=True)
            (pack/'manifest.json').write_text('{}')
            first = pack/'MyMod'/'first.py'
            second = pack/'MyMod'/'second.py'
            first.write_text('VALUE = 1\n')
            second.write_text('VALUE = 2\n')
            targets = changed_reload_targets(tmp, {str(first), str(second)})
            self.assertEqual(targets[('python', 'MyMod.first')], str(first))
            self.assertEqual(targets[('python', 'MyMod.second')], str(second))


if __name__ == '__main__':
    unittest.main()

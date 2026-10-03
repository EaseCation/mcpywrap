"""真实注入源码与有状态引擎适配器：节点失效、释放、路由和幂等。"""
import json
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from click.testing import CliRunner
from mcpywrap.cli import cli
from mcpywrap.mcstudio.runtime_ui import install_source, call_source, compact_source
from mcpywrap.mcstudio.runtime_ui_payload import UIController, UIError
from mcpywrap.remote.http_server import GameHTTPServer


ROOT = '/variables_button_mappings_and_controls'


class Control:
    def __init__(self, node, path):
        self.node, self.path = node, path
        self.data = node.data[path]

    def GetVisible(self): return self.data.get('visible', True)
    def GetGlobalPosition(self): return self.data.get('pos', (0, 0))
    def GetSize(self): return self.data.get('size', (200, 30))
    def GetClipsChildren(self): return self.data.get('clip', False)
    def asLabel(self): return self
    def asTextEditBox(self): return self
    def asSwitchToggle(self): return self
    def asSlider(self): return self
    def asScrollView(self): return self if self.data.get('scroll') else None
    def GetText(self): return self.data.get('text', '')
    def GetEditText(self): return self.data.get('value', '')
    def SetEditText(self, value): self.data['value'] = value
    def GetToggleState(self, toggle_path='/this_toggle'):
        assert toggle_path == ''
        return self.data.get('value', False)
    def SetToggleState(self, value, toggle_path='/this_toggle'):
        assert toggle_path == ''
        self.data['value'] = value
    def GetSliderValue(self): return self.data.get('value', 0)
    def SetSliderValue(self, value): self.data['value'] = value
    def GetScrollViewContentPath(self): return self.path + '/scroll_touch/scroll_view/content'
    def GetScrollViewPercentValue(self): return self.data.get('value', 0)
    def SetScrollViewPercentValue(self, value): self.data['value'] = value
    def GetScrollViewPos(self): return self.GetScrollViewPercentValue() * 10.


class Node:
    def __init__(self):
        self.screen = 'settings.screen'
        self.top = 'settings - first'
        self.data = {
            ROOT: {'kind': 10, 'size': (512, 384)},
            ROOT+'/button': {'kind': 0, 'pos': (20, 20)},
            ROOT+'/button/label': {'kind': 9, 'text': '设置', 'pos': (20, 20)},
            ROOT+'/edit': {'kind': 4, 'pos': (20, 70), 'value': '原值'},
            ROOT+'/slider': {'kind': 16, 'pos': (20, 120), 'size': (100, 10), 'value': 1.},
            ROOT+'/toggle': {'kind': 19, 'pos': (20, 170), 'value': False},
            ROOT+'/area': {'kind': 10, 'pos': (250, 0), 'size': (200, 300), 'scroll': True},
            ROOT+'/area/scroll_touch': {'kind': 10, 'pos': (250, 0), 'size': (200, 300)},
            ROOT+'/area/scroll_touch/scroll_view': {'kind': 14, 'pos': (250, 0), 'size': (200, 300)},
            ROOT+'/area/scroll_touch/scroll_view/content': {'kind': 9, 'pos': (260, 30), 'text': '内容'},
            ROOT+'/hidden': {'kind': 10, 'visible': False},
            ROOT+'/hidden/button': {'kind': 0},
            ROOT+'/clip': {'kind': 10, 'pos': (0, 300), 'size': (20, 20), 'clip': True},
            ROOT+'/clip/button': {'kind': 0, 'pos': (30, 330), 'size': (20, 20)},
        }

    def GetScreenName(self): return self.screen
    def GetChildrenName(self, path):
        if path not in self.data: return None
        return [p.rsplit('/', 1)[-1] for p in self.data if p.rsplit('/', 1)[0] == path]
    def GetBaseUIControl(self, path): return Control(self, path) if path in self.data else None


class API(types.ModuleType):
    def __init__(self):
        super().__init__('mod.client.extraClientApi')
        self.node = Node()
        self.timers = []
        self.systems = {}
        self.listeners = []
        api = self
        class System:
            def __init__(self, namespace, system): pass
            def ListenForEvent(self, ns, system, event, owner, callback):
                api.listeners.append((event, owner, callback))
            def UnListenForEvent(self, ns, system, event, owner, callback):
                api.listeners.remove((event, owner, callback))
        self.base = System

    def GetTopUINode(self): return self.node
    def GetTopUI(self): return self.node.top
    def GetLevelId(self): return 'level'
    def GetEngineCompFactory(self): return self
    def CreateGame(self, level): return self
    def AddTimer(self, seconds, callback): self.timers.append(callback); return len(self.timers)
    def GetClientSystemCls(self): return self.base
    def GetEngineNamespace(self): return 'Minecraft'
    def GetEngineSystemName(self): return 'game'
    def GetSystem(self, namespace, system): return self.systems.get((namespace, system))
    def RegisterSystem(self, namespace, system, qualified):
        module, name = qualified.rsplit('.', 1)
        value = getattr(sys.modules[module], name)(namespace, system)
        self.systems[(namespace, system)] = value
        return value
    def tick(self):
        timers, self.timers = self.timers, []
        for timer in timers: timer()
    def emit(self, event):
        for name, owner, callback in list(self.listeners):
            if name == event: callback({})


class GUI(types.ModuleType):
    def __init__(self, api):
        super().__init__('gui')
        self.api, self.inputs = api, []
        self.accept_down = True
        self.accept_up = True
    def get_client_ui_screen_size(self): return (512, 384)
    def get_client_screen_size(self): return (1024, 768)
    def get_control_def_type(self, screen, path): return self.api.node.data[path]['kind']
    def simulate_button_event(self, x, y, state):
        self.inputs.append((x, y, state))
        return self.accept_up if state == 1 else self.accept_down


class RuntimeUITests(unittest.TestCase):
    def setUp(self):
        self.api = API()
        self.gui = GUI(self.api)
        self.now = [1.]
        self.ui = UIController(self.api, self.gui, '3.10.0.420447', clock=lambda: self.now[0])
        self.ui.events = Mock()

    def observe(self, role='button', **kwargs):
        snapshot = self.ui.snapshot(**kwargs)
        row = next(r for r in snapshot['nodes'] if r['role'] == role)
        return row['id'], snapshot['snapshot']

    def test_snapshot_prunes_hidden_and_clipped_nodes_and_labels(self):
        state = self.ui.snapshot(details=True)
        self.assertIn('button 设置', state['tree'])
        self.assertNotIn('label 设置', state['tree'])
        self.assertFalse(any('/hidden/' in r['path'] or '/clip/button' in r['path'] for r in state['nodes']))
        all_rows = self.ui.snapshot(include_offscreen=True, details=True)['nodes']
        self.assertFalse(next(r for r in all_rows if r['path'].endswith('/clip/button'))['in_view'])

    def test_utf8_byte_labels_and_returned_actions_are_not_live_state(self):
        self.api.node.data[ROOT+'/button/label']['text'] = '设置'.encode('utf-8')
        node, snap = self.observe()
        result = self.ui.click(node, snap)
        self.assertNotIn('signature', result)
        result['point'][0] = 99999
        self.api.tick()
        self.assertEqual(self.gui.inputs[-1], (240, 70, 1))

    def test_click_scales_engine_pixels_and_releases_without_caller(self):
        node, snap = self.observe()
        result = self.ui.click(node, snap)
        self.assertEqual(result['state'], 'pending')
        self.assertEqual(self.gui.inputs, [(240, 70, 0)])
        self.api.tick()
        self.assertEqual(self.gui.inputs[-1], (240, 70, 1))
        self.assertTrue(self.ui.status(result['id'])['released'])
        self.assertFalse(self.ui.status(result['id'])['effect_verified'])

    def test_duplicate_request_does_not_click_again_and_conflict_rejected(self):
        node, snap = self.observe()
        rid = 'a'*32
        first = self.ui.click(node, snap, request_id=rid)
        again = self.ui.click(node, snap, request_id=rid)
        self.assertEqual(first['id'], again['id'])
        self.assertEqual(len(self.gui.inputs), 1)
        self.api.tick()
        self.ui.click(node, snap, request_id=rid)
        self.assertEqual(len(self.gui.inputs), 2)
        with self.assertRaises(UIError) as error:
            self.ui.click(node+1, snap, request_id=rid)
        self.assertEqual(error.exception.code, 'request_conflict')

    def test_native_rejection_still_releases_and_reports_failure(self):
        node, snap = self.observe()
        self.gui.accept_down = False
        result = self.ui.click(node, snap)
        self.assertEqual(result['state'], 'failed')
        self.assertTrue(result['released'])
        self.api.tick()
        self.assertEqual(len(self.gui.inputs), 2)

    def test_delayed_release_does_not_turn_rejected_press_into_success(self):
        node, snap = self.observe()
        self.gui.accept_down = self.gui.accept_up = False
        result = self.ui.click(node, snap)
        self.assertEqual(result['state'], 'unknown')
        self.gui.accept_up = True
        self.api.tick()
        self.assertEqual(self.ui.status(result['id'])['state'], 'failed')

    def test_release_failure_blocks_new_actions_until_cancel_releases(self):
        node, snap = self.observe()
        result = self.ui.click(node, snap)
        self.gui.accept_up = False
        self.api.tick()
        self.assertEqual(self.ui.status(result['id'])['state'], 'unknown')
        with self.assertRaises(UIError): self.ui.snapshot()
        with self.assertRaises(UIError): self.ui.close()
        self.gui.accept_up = True
        self.ui.cancel(result['id'])
        self.assertIsNone(self.ui.active)
        self.ui.snapshot()

    def test_timer_failure_never_leaves_a_pressed_input(self):
        node, snap = self.observe()
        self.api.AddTimer = Mock(side_effect=ValueError('timer unavailable'))
        result = self.ui.click(node, snap)
        self.assertFalse(result['ok'])
        self.assertFalse(any(event[2] == 0 for event in self.gui.inputs))

    def test_missing_timer_handle_prevents_press(self):
        node, snap = self.observe()
        self.api.AddTimer = Mock(return_value=None)
        result = self.ui.click(node, snap)
        self.assertFalse(result['ok'])
        self.assertEqual(result['code'], 'timer_unavailable')
        self.assertFalse(any(event[2] == 0 for event in self.gui.inputs))
        self.assertIsNone(self.ui.active)

    def test_changed_geometry_value_tab_and_lifecycle_reject_stale_input(self):
        changes = [lambda: self.api.node.data[ROOT+'/button'].update(pos=(30, 20)),
                   lambda: self.api.node.data[ROOT+'/edit'].update(value='改变'),
                   lambda: setattr(self.api.node, 'top', 'settings - second'),
                   lambda: self.ui._changed()]
        for change in changes:
            with self.subTest(change=change):
                node, snap = self.observe()
                change()
                result = self.ui.dispatch('click', node=node, snapshot=snap)
                self.assertEqual(result['code'], 'stale_snapshot')
                self.assertEqual(self.gui.inputs, [])

    def test_snapshot_expiration_and_new_observation(self):
        node, snap = self.observe()
        self.now[0] += 121
        with self.assertRaises(UIError): self.ui.click(node, snap)
        node, snap = self.observe()
        self.ui.snapshot(query='内容')
        with self.assertRaises(UIError): self.ui.click(node, snap)

    def test_only_returned_nodes_can_be_operated(self):
        result = self.ui.snapshot(query='设置', limit=1)
        with self.assertRaises(UIError): self.ui.click(2, result['snapshot'])
        self.assertEqual(self.gui.inputs, [])

    def test_duplicate_template_paths_are_readable_but_never_actionable(self):
        original = self.api.node.GetChildrenName
        self.api.node.GetChildrenName = lambda path: original(path) + ['button'] if path == ROOT else original(path)
        state = self.ui.snapshot()
        row = next(r for r in state['nodes'] if r['name'] == '设置')
        self.assertTrue(row['ambiguous'])
        self.assertEqual(row['actions'], [])
        with self.assertRaises(UIError): self.ui.click(row['id'], state['snapshot'])
        self.assertEqual(self.gui.inputs, [])

    def test_scroll_targets_outer_wrapper_and_invalidates_observation(self):
        node, snap = self.observe('scroll')
        result = self.ui.scroll(node, 50, snap)
        self.assertEqual((result['before'], result['after'], result['position']), (0, 50, 500.))
        self.assertEqual(self.api.node.data[ROOT+'/area']['value'], 50)
        with self.assertRaises(UIError): self.ui.scroll(node, 25, snap)

    def test_setter_is_explicitly_control_only_and_parameters_are_typed(self):
        node, snap = self.observe('edit')
        value = '中文\n\"; __import__(\"os\")'
        result = self.ui.set_control_value(node, value, snap)
        self.assertEqual(result['after'], value)
        self.assertEqual(result['verification'], 'control_only')
        self.assertFalse(result['effect_verified'])
        node, snap = self.observe('toggle')
        with self.assertRaises(UIError): self.ui.set_control_value(node, 'false', snap)
        self.assertFalse(self.api.node.data[ROOT+'/toggle']['value'])

    def test_unsupported_engine_never_falls_back_to_input(self):
        self.ui.engine = 'unverified'
        node, snap = self.observe()
        with self.assertRaises(UIError): self.ui.click(node, snap)
        self.assertEqual(self.gui.inputs, [])

    def test_offscreen_and_invalid_numeric_arguments(self):
        state = self.ui.snapshot(query='/clip/button', include_offscreen=True)
        with self.assertRaises(UIError): self.ui.click(state['nodes'][0]['id'], state['snapshot'])
        node, snap = self.observe('slider')
        for value in (float('nan'), float('inf'), -.1, True):
            with self.subTest(value=value), self.assertRaises(UIError):
                self.ui.slide(node, value, snap)

    def test_close_cancels_pending_input_and_unbinds_only_owned_events(self):
        node, snap = self.observe()
        self.ui.click(node, snap)
        self.ui.close()
        self.ui.events.bind.assert_called_once_with(None)
        self.api.tick()
        self.assertEqual([event[2] for event in self.gui.inputs], [0, 1])
        with self.assertRaises(UIError): self.ui.snapshot()

    def test_vertical_slider_is_not_advertised_or_guessed(self):
        self.api.node.data[ROOT+'/slider']['size'] = (10, 100)
        state = self.ui.snapshot()
        row = next(r for r in state['nodes'] if r['role'] == 'slider')
        self.assertNotIn('slide', row['actions'])
        with self.assertRaises(UIError): self.ui.slide(row['id'], .25, state['snapshot'])
        self.assertEqual(self.gui.inputs, [])


class RuntimeUIInjectionTests(unittest.TestCase):
    def setUp(self):
        self.api = API()
        self.gui = GUI(self.api)
        mod, client = types.ModuleType('mod'), types.ModuleType('mod.client')
        mod.client = client
        client.extraClientApi = self.api
        self.modules = patch.dict(sys.modules, {'mod': mod, 'mod.client': client,
            'mod.client.extraClientApi': self.api, 'gui': self.gui})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.old = sys.modules.pop('_mcpywrap_ui_runtime', None)
        self.addCleanup(self.restore)
        self.scope = {}

    def restore(self):
        sys.modules.pop('_mcpywrap_ui_runtime', None)
        if self.old is not None: sys.modules['_mcpywrap_ui_runtime'] = self.old

    def run_code(self, code):
        exec(compile(code, '<test-game>', 'exec'), self.scope)
        return self.scope['_result']

    def test_real_payload_installs_idempotently_and_lifecycle_is_guarded(self):
        source = install_source('3.10.0.420447')
        self.assertLess(len(source.encode('utf-8')), 32768)
        self.assertTrue(self.run_code(source)['lifecycle_guard'])
        ui = self.scope['mcpy'].ui
        listeners = len(self.api.listeners)
        self.run_code(source)
        self.assertIs(self.scope['mcpy'].ui, ui)
        self.assertEqual(len(self.api.listeners), listeners)
        module = sys.modules['_mcpywrap_ui_runtime']
        module.source_hash = 'previous-build'
        self.run_code(source)
        self.assertIs(sys.modules['_mcpywrap_ui_runtime'], module)
        self.assertEqual(len(self.api.listeners), listeners)
        ui = self.scope['mcpy'].ui
        snap = ui.snapshot()
        self.api.emit('PushScreenEvent')
        response = self.run_code(call_source('click', {'node': 1, 'snapshot': snap['snapshot']}))
        self.assertEqual(response['code'], 'stale_snapshot')
        self.run_code(call_source('close', {}))
        self.assertEqual(self.api.listeners, [])
        self.run_code(source)
        self.assertEqual(len(self.api.listeners), listeners)

    def test_call_serialization_cannot_execute_value_as_python(self):
        self.run_code(install_source('3.10.0.420447'))
        snap = self.run_code(call_source('snapshot', {'query': '/edit'}))
        value = "中文'\n\"; raise Exception('not code')"
        response = self.run_code(call_source('set_control_value', {
            'node': snap['nodes'][0]['id'], 'snapshot': snap['snapshot'], 'value': value}))
        self.assertEqual(response['after'], value)

    def test_alias_collision_is_not_overwritten(self):
        original = object()
        self.scope['mcpy'] = original
        with self.assertRaises(ValueError): self.run_code(install_source('3.10.0.420447'))
        self.assertIs(self.scope['mcpy'], original)

    def test_comment_compaction_preserves_literals_encoding_and_lines(self):
        source = '# coding: utf-8\n# 注释\nVALUE = "#字符串" # 尾部注释\nTEXT = """line\n#not a comment\n"""\n'.encode('utf-8')
        compacted = compact_source(source)
        self.assertEqual(compacted.count(b'\n'), source.count(b'\n'))
        self.assertTrue(compacted.startswith(b'# coding: utf-8'))
        scope = {}
        exec(compile(compacted, '<compact>', 'exec'), scope)
        self.assertEqual(scope['VALUE'], '#字符串')
        self.assertIn('#not a comment', scope['TEXT'])

    def test_remote_cli_uses_existing_python_endpoint_even_for_ui_status(self):
        calls = []
        def execute(session, data):
            calls.append((session, data))
            value = self.run_code(data['code'])
            return {'ok': True, 'state': 'completed', 'side': 'client', 'request_id': 'wire', 'value': value}
        service = Mock()
        service.describe.return_value = {'protocol_version': 1, 'capabilities': ['py']}
        service.record.return_value = {'state': 'running', 'game': {'executable': r'D:\engine\3.10.0.420447\Minecraft.Windows.exe'}}
        service.execute_python.side_effect = execute
        server = GameHTTPServer(('127.0.0.1', 0), service)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01})
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as project:
                prefix = ['--remote', 'http://127.0.0.1:'+str(server.server_port), '--project', project, 'runtime', 'ui']
                for command in ('install', 'status', 'snapshot'):
                    result = CliRunner().invoke(cli, prefix+[command, '--session', 'a'*32, '--json'])
                    self.assertEqual(result.exit_code, 0, result.output)
                player_prefix=prefix[:-1]+['player']
                for command in ('install','status','stop'):
                    result=CliRunner().invoke(cli,player_prefix+[command,'--session','a'*32,'--json'])
                    self.assertEqual(result.exit_code,0,result.output)
                self.assertEqual(len(calls), 6)
                self.assertTrue(all(data['side'] == 'client' for _, data in calls))
                self.assertEqual(service.record.call_count, 2)
                service.stop.assert_not_called()
        finally:
            server.shutdown(); server.server_close(); thread.join(2)

    def test_mutation_timeout_returns_operation_for_status_not_retry(self):
        with patch('mcpywrap.mcstudio.runtime_debug.control_request', side_effect=OSError('lost reply')):
            result = CliRunner().invoke(cli, ['--local', 'runtime', 'ui', 'click', '1',
                '--session', 'a'*32, '--snapshot', 'b'*32, '--request-id', 'c'*32, '--json'])
        self.assertEqual(result.exit_code, 1)
        data = json.loads(result.stdout)
        self.assertEqual(data['state'], 'unknown')
        self.assertEqual(data['operation'], 'c'*32)


if __name__ == '__main__':
    unittest.main()

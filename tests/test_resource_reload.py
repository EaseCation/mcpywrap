"""Per-engine restrictions must be checked before mutating files or invoking game code."""
import unittest
from unittest.mock import patch
import types
from mcpywrap.mcstudio.hot_reload import reload_session, reload_ui
from mcpywrap.engines.macos import MacOSBackend


class ResourceReloadTests(unittest.TestCase):
    def setUp(self):
        self.data = {'state':'running','mode':'local','backend':'macos-arm64',
                     'launch':{'engine_version':'3.9.100.297020'}}

    def test_unavailable_native_resources_never_deploy_or_invoke(self):
        for kind in ('ui','material','shader'):
            with self.subTest(kind=kind), patch('mcpywrap.mcstudio.sessions.read',return_value=self.data), \
                    patch.object(MacOSBackend,'deploy') as deploy, \
                    patch('mcpywrap.mcstudio.runtime_debug.control_request') as request:
                result=reload_session('.', 'a'*32, kind, 'fixture')
            self.assertEqual(result['state'],'unsupported')
            self.assertIn('重载世界',result['error'])
            deploy.assert_not_called();request.assert_not_called()

    def test_unknown_version_keeps_unverified_shader_and_material_disabled(self):
        self.data['launch']['engine_version'] = 'future'
        for kind in ('material', 'shader'):
            with self.subTest(kind=kind), patch('mcpywrap.mcstudio.sessions.read', return_value=self.data), \
                    patch.object(MacOSBackend, 'deploy') as deploy, \
                    patch('mcpywrap.mcstudio.runtime_debug.control_request') as request:
                result = reload_session('.', 'a'*32, kind, 'fixture')
            self.assertEqual(result['state'], 'unsupported')
            deploy.assert_not_called(); request.assert_not_called()

    def test_optional_ui_recognition_failure_blocks_before_deploy(self):
        self.data['launch'].update(runtime='/runtime/app', compat_report='/report.json')
        metadata = {'json_ui_reload_protocol': 1, 'game_compatibility': {'elf_rules_schema': 1}}
        with patch('mcpywrap.mcstudio.sessions.read', return_value=self.data), \
                patch('mcpywrap.engines.macos.install.read_json', side_effect=[metadata, {'ui': None}]), \
                patch.object(MacOSBackend, 'deploy') as deploy, \
                patch('mcpywrap.mcstudio.runtime_debug.control_request') as request:
            result = reload_session('.', 'a'*32, 'ui')
        self.assertEqual(result['state'], 'unsupported')
        deploy.assert_not_called(); request.assert_not_called()

    def test_direct_ui_helper_respects_same_restriction(self):
        with patch('mcpywrap.mcstudio.sessions.read',return_value=self.data), \
                patch('mcpywrap.mcstudio.runtime_debug.control_request') as request:
            result=reload_ui('.', 'a'*32)
        self.assertEqual(result['state'],'unsupported');request.assert_not_called()

    def test_native_ui_dispatch_and_result_states(self):
        self.data['game'] = {'pid': 1}
        self.data['launch']['runtime'] = '/runtime/McpyRuntime.app'
        for payload, expected in (({'ok': True}, 'triggered'),
                                  ({'ok': False}, 'failed'),
                                  ({'ok': False, 'unsupported': True}, 'unsupported')):
            with self.subTest(payload=payload), \
                    patch('mcpywrap.mcstudio.sessions.read', return_value=self.data), \
                    patch('mcpywrap.engines.macos.install.read_json', return_value={'json_ui_reload_protocol': 1}), \
                    patch('mcpywrap.mcstudio.processes.checked_process', return_value=True), \
                    patch.object(MacOSBackend, 'deploy') as deploy, \
                    patch('mcpywrap.mcstudio.runtime_debug.control_request', return_value={
                        'state': 'completed', 'side': 'client', 'value': payload}) as request:
                result = reload_session('.', 'a'*32, 'ui')
            self.assertEqual(result['state'], expected)
            self.assertFalse(result['effect_verified'])
            self.assertIn('_mcpy_launcher', request.call_args.kwargs['code'])
            self.assertNotIn('simulate_keyboard_event', request.call_args.kwargs['code'])
            deploy.assert_called_once()

    def test_native_binding_unavailable_or_rejected_is_not_success(self):
        for module, expected in ((types.SimpleNamespace(), {'ok': False, 'unsupported': True}),
                                 (types.SimpleNamespace(reload_ui=lambda: False), {'ok': False}),
                                 (types.SimpleNamespace(reload_ui=lambda: True), {'ok': True})):
            with patch.dict('sys.modules', {'_mcpy_launcher': module}):
                scope = {}
                exec(MacOSBackend().ui_reload_code(), scope)
                self.assertEqual(scope['_result'], expected)

    def test_particle_acknowledgement_is_triggered_not_verified_effect(self):
        with patch('mcpywrap.mcstudio.sessions.read',return_value=self.data), \
                patch.object(MacOSBackend,'deploy') as deploy, \
                patch('mcpywrap.mcstudio.runtime_debug.control_request',return_value={
                    'state':'completed','side':'client','value':{'ok':True}}) as request:
            result=reload_session('.', 'a'*32, 'particle', 'probe.json')
        self.assertEqual(result['state'],'triggered')
        self.assertFalse(result['effect_verified'])
        self.assertIn('新增',result['hint'])
        deploy.assert_called_once();request.assert_called_once()

    def test_python_remains_completed(self):
        with patch('mcpywrap.mcstudio.sessions.read',return_value=self.data), \
                patch.object(MacOSBackend,'deploy'), \
                patch('mcpywrap.mcstudio.runtime_debug.control_request',return_value={
                    'state':'completed','side':'server','value':{'ok':True}}):
            result=reload_session('.', 'a'*32, 'python', 'Probe.config', b'VALUE=1', 'server')
        self.assertEqual(result['state'],'completed')
        self.assertNotIn('effect_verified',result)


if __name__=='__main__':unittest.main()

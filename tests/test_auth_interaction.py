"""Recovery tests never install certificates or modify host security policy."""
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from click.testing import CliRunner
from mcpywrap.cli import cli
from mcpywrap.mcstudio import mcs_auth as auth, auth_interaction as ui, bridge_assets as assets


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.certificate = {'path': 'publisher.cer', 'thumbprint': 'TEST', 'subject': 'Test publisher', 'expires': '2030'}
        self.error = auth.AuthError('Windows 阻止了登录组件', 'component_blocked')
        options = {'mix_stderr': False} if 'mix_stderr' in inspect.signature(CliRunner).parameters else {}
        self.runner = CliRunner(**options)

    def recovery(self, effects, consent=True, install_error=None):
        self.capture = patch.object(auth, 'capture_identity', side_effect=effects).start()
        self.confirm = patch.object(ui, 'confirm_certificate', return_value=consent).start()
        self.install = patch.object(ui, 'install_certificate', side_effect=install_error).start()
        self.failure = patch.object(ui, 'show_failure').start()
        patch.object(assets, 'bridge_directory', return_value=self.root).start()
        patch.object(assets, 'trusted_certificate_candidate', return_value=self.certificate).start()
        patch.object(ui, 'certificate_can_help', return_value=True).start()
        self.addCleanup(patch.stopall)

    def test_direct_success_never_prompts(self):
        identity = object()
        self.recovery([identity])
        self.assertIs(auth.acquire_identity(interactive=True), identity)
        self.confirm.assert_not_called(); self.install.assert_not_called()

    def test_consent_then_exactly_one_retry(self):
        identity = object()
        self.recovery([self.error, identity])
        self.assertIs(auth.acquire_identity(interactive=True), identity)
        self.confirm.assert_called_once(); self.install.assert_called_once()
        self.assertEqual(self.capture.call_count, 2)

    def test_cancel_never_installs_or_retries(self):
        self.recovery([self.error], consent=False)
        with self.assertRaises(auth.AuthError) as error:
            auth.acquire_identity(interactive=True)
        self.assertEqual(error.exception.code, 'cancelled')
        self.install.assert_not_called(); self.failure.assert_not_called()
        self.assertEqual(self.capture.call_count, 1)

    def test_failed_retry_has_plain_explanation_and_no_loop(self):
        self.recovery([self.error, self.error])
        with self.assertRaisesRegex(auth.AuthError, '证书已安装'):
            auth.acquire_identity(interactive=True)
        self.assertEqual(self.capture.call_count, 2)
        self.install.assert_called_once()
        self.assertIn('去掉 --mcs-auth', self.failure.call_args.args[0])

    def test_install_failure_never_retries(self):
        self.recovery([self.error], install_error=ValueError('证书未能安装'))
        with self.assertRaises(auth.AuthError):
            auth.acquire_identity(interactive=True)
        self.assertEqual(self.capture.call_count, 1)
        self.failure.assert_called_once()

    def test_studio_exit_during_recovery_is_not_mislabeled_as_policy(self):
        self.recovery([self.error, auth.AuthError('请先打开并登录 MC Studio', 'studio_unavailable')])
        with self.assertRaises(auth.AuthError) as result:
            auth.acquire_identity(interactive=True)
        self.assertEqual(result.exception.code, 'studio_unavailable')
        self.assertIn('MC Studio', str(result.exception))
        self.assertNotIn('组织策略', str(result.exception))

    def test_missing_studio_is_not_a_certificate_problem(self):
        self.recovery([auth.AuthError('请先打开并登录 MC Studio', 'studio_unavailable')])
        with self.assertRaises(auth.AuthError):
            auth.acquire_identity(interactive=True)
        self.confirm.assert_not_called(); self.install.assert_not_called()
        self.failure.assert_called_once_with('请先打开并登录 MC Studio')

    def test_skill_cli_missing_mcs_returns_json_without_qt(self):
        self.recovery([auth.AuthError('请先打开并登录 MC Studio', 'studio_unavailable')])
        with patch('mcpywrap.mcstudio.network.discover_engines', return_value=Mock(require_engine=lambda: Mock())), \
                patch('mcpywrap.mcstudio.network.require_resources'):
            # Route directly to identity acquisition without a native engine fixture.
            with patch('mcpywrap.mcstudio.network.unauthenticated_config', return_value={}):
                result = self.runner.invoke(cli, ['--non-interactive', 'connect', 'localhost', '--mcs-auth', '--detach', '--json'])
        data = json.loads(result.stdout)
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(data['code'], 'studio_unavailable')
        self.assertIn('MC Studio', data['error'])
        self.assertIn('--mcs-auth', data['hint'])
        self.confirm.assert_not_called(); self.install.assert_not_called(); self.failure.assert_not_called()

    def test_noninteractive_security_error_never_installs(self):
        self.recovery([self.error])
        with self.assertRaises(auth.AuthError):
            auth.acquire_identity(interactive=False)
        self.confirm.assert_not_called(); self.install.assert_not_called(); self.failure.assert_not_called()

    def test_signature_recovery_rejects_tampering_and_expired_chains(self):
        rows = [{'status': 'UnknownError', 'thumbprint': 'TEST', 'untrusted_root': True} for _ in range(3)]
        with patch.object(ui, '_powershell_json', return_value=rows):
            self.assertTrue(ui.certificate_can_help(self.root, self.certificate))
            rows[0]['status'] = 'HashMismatch'
            self.assertFalse(ui.certificate_can_help(self.root, self.certificate))
            rows[0]['status'] = 'UnknownError'; rows[0]['untrusted_root'] = False
            self.assertFalse(ui.certificate_can_help(self.root, self.certificate))

    def test_altered_payload_cannot_be_offered_for_trust(self):
        self.assertIsNone(assets.trusted_certificate_candidate(self.root))

    def test_studio_disappearing_has_stable_error(self):
        import psutil
        with patch.object(auth, '_capture_identity', side_effect=psutil.NoSuchProcess(123)):
            with self.assertRaises(auth.AuthError) as error:
                auth.capture_identity()
        self.assertEqual(error.exception.code, 'studio_unavailable')
        self.assertIn('重新打开', str(error.exception))


class ConsentDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_default_is_cancel_and_explicit_accept_is_required(self):
        from PyQt5.QtWidgets import QMessageBox
        certificate = {'subject': 'Test publisher', 'thumbprint': 'TEST', 'expires': '2030'}
        for accept in (False, True):
            observed = []
            def choose(dialog):
                observed.append(dialog.defaultButton().text())
                target = '信任此发布者并重试' if accept else '暂不启用'
                next(b for b in dialog.buttons() if b.text() == target).click()
                return 0
            # Inspect real Qt widgets without a platform-native modal loop in offscreen CI.
            with patch.object(QMessageBox, 'exec_', choose):
                self.assertEqual(ui.confirm_certificate(certificate), accept)
            self.assertEqual(observed, ['暂不启用'])

    def test_gui_checks_identity_on_ui_entry_not_in_worker(self):
        from types import SimpleNamespace
        from mcpywrap.ui.project_ui import GameInstanceManager
        identity = object()
        view = SimpleNamespace(mcs_auth=True, all_packs=[], log=Mock(), refresh_instances=Mock())
        with patch.object(auth, 'acquire_identity', return_value=identity) as capture, \
                patch('mcpywrap.ui.project_ui.GameRunThread') as thread:
            GameInstanceManager.start_game_thread(view, 'config', 'world')
            capture.assert_called_once_with(interactive=True)
            self.assertIs(thread.call_args.args[-1], identity)
            thread.return_value.start.assert_called_once()

    def test_gui_missing_identity_does_not_launch_thread(self):
        from types import SimpleNamespace
        from mcpywrap.ui.project_ui import GameInstanceManager
        view = SimpleNamespace(mcs_auth=True, all_packs=[], log=Mock())
        with patch.object(auth, 'acquire_identity', side_effect=auth.AuthError('请先打开并登录 MC Studio')), \
                patch('mcpywrap.ui.project_ui.GameRunThread') as thread:
            GameInstanceManager.start_game_thread(view, 'config', 'world')
            thread.assert_not_called()
            view.log.assert_called_once_with('请先打开并登录 MC Studio', 'error')


if __name__ == '__main__':
    unittest.main()

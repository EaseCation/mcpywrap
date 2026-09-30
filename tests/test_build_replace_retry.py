import unittest
import os
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner
from mcpywrap.cli import cli
from mcpywrap.builders.project_builder import _replace_with_retry, AddonProjectBuilder
from test_local_dependencies import addon


def locked(code=5):
    error=PermissionError('Windows directory temporarily locked')
    error.winerror=code
    return error


class ReplaceRetry(unittest.TestCase):
    def test_recovers_from_transient_windows_lock(self):
        with patch('mcpywrap.builders.project_builder.os.replace',side_effect=[locked(),locked(32),None]) as replace, patch('mcpywrap.builders.project_builder.time.sleep') as sleep:
            _replace_with_retry('source','target')
        self.assertEqual(replace.call_count,3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list],[.05,.1])
        self.assertTrue(all(c.args==('source','target') for c in replace.call_args_list))

    def test_persistent_lock_is_bounded_and_propagated(self):
        error=locked(33)
        with patch('mcpywrap.builders.project_builder.os.replace',side_effect=error) as replace, patch('mcpywrap.builders.project_builder.time.sleep') as sleep:
            with self.assertRaises(PermissionError) as caught:_replace_with_retry('source','target')
        self.assertIs(caught.exception,error)
        self.assertEqual(replace.call_count,7)
        self.assertLess(sum(c.args[0] for c in sleep.call_args_list),4)

    def test_non_windows_or_non_lock_errors_are_not_retried(self):
        for error in (PermissionError('permissions'),FileNotFoundError('missing')):
            with patch('mcpywrap.builders.project_builder.os.replace',side_effect=error) as replace, patch('mcpywrap.builders.project_builder.time.sleep') as sleep:
                with self.assertRaises(type(error)):_replace_with_retry('source','target')
                self.assertEqual(replace.call_count,1);sleep.assert_not_called()


class BuildRecovery(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='mcpy-build-recovery-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = addon(self.root, 'source', configured=True)
        self.target = self.source / 'build'
        self.target.mkdir()
        (self.target / 'known-good.txt').write_text('previous build', encoding='utf-8')

    def test_install_failure_restores_old_build(self):
        replace = os.replace
        def fail_install(src, dst):
            if Path(src).name == 'output':
                raise locked()
            return replace(src, dst)
        with patch('mcpywrap.builders.project_builder.os.replace', side_effect=fail_install), \
             patch('mcpywrap.builders.project_builder.time.sleep'):
            ok, error = AddonProjectBuilder(self.source, self.target).build()
        self.assertFalse(ok)
        self.assertIn('locked', error)
        self.assertEqual((self.target / 'known-good.txt').read_text(), 'previous build')
        self.assertFalse(list(self.source.glob('.mcpy-build-*')))

    def test_failed_rollback_preserves_recovery_directory_and_both_errors(self):
        replace = os.replace
        def fail_destination(src, dst):
            if Path(dst) == self.target:
                raise OSError('restore denied' if Path(src).name == 'previous' else 'install denied')
            return replace(src, dst)
        with patch('mcpywrap.builders.project_builder.os.replace', side_effect=fail_destination), \
             patch('mcpywrap.builders.project_builder.report_warning'):
            ok, error = AddonProjectBuilder(self.source, self.target).build()
        self.assertFalse(ok)
        backup = next(self.source.glob('.mcpy-build-*/previous'))
        self.assertEqual((backup / 'known-good.txt').read_text(), 'previous build')
        for detail in ('install denied', 'restore denied', str(backup), str(self.target)):
            self.assertIn(detail, error)
        self.assertFalse(self.target.exists())

    def test_interrupted_install_keeps_previous_build(self):
        replace = os.replace
        def interrupt(src, dst):
            if Path(src).name == 'output':
                raise KeyboardInterrupt()
            return replace(src, dst)
        with patch('mcpywrap.builders.project_builder.os.replace', side_effect=interrupt), \
             patch('mcpywrap.builders.project_builder.report_warning'):
            with self.assertRaises(KeyboardInterrupt):
                AddonProjectBuilder(self.source, self.target).build()
        self.assertEqual(len(list(self.source.glob('.mcpy-build-*/previous/known-good.txt'))), 1)

    def test_cleanup_failure_keeps_success_and_json_warning(self):
        with patch('mcpywrap.builders.project_builder.shutil.rmtree', side_effect=locked()):
            result = CliRunner().invoke(cli, ['--project', str(self.source), 'build', '--json'])
        self.assertEqual(result.exit_code, 0, result.output)
        data = json.loads(result.stdout)
        self.assertTrue(data['ok'])
        self.assertTrue(any('.mcpy-build-' in message for message in data['warnings']))
        self.assertTrue((self.target / 'behavior_pack/marker.py').is_file())
        self.assertEqual(len(list(self.source.glob('.mcpy-build-*/previous/known-good.txt'))), 1)

    def test_assembly_failure_leaves_existing_build_and_cleans_stage(self):
        with patch('mcpywrap.builders.project_builder.assemble_addon', side_effect=ValueError('bad input')):
            ok, error = AddonProjectBuilder(self.source, self.target).build()
        self.assertFalse(ok)
        self.assertEqual(error, 'bad input')
        self.assertTrue((self.target / 'known-good.txt').is_file())
        self.assertFalse(list(self.source.glob('.mcpy-build-*')))


if __name__=='__main__':unittest.main()

"""Automatic compatibility must be checked before changing a selected runtime."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from mcpywrap.engines import install as installer
from mcpywrap.engines.host import EngineError
import test_engine_install


class PreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app, self.game = self.root/'runtime.app', self.root/'engine/game'
        self.metadata = {'game_compatibility': {'elf_rules_schema': 1, 'rules_sha256': 'a'*64}}
        self.profile = {'apk': {'version': 'future'}, 'files': {'lib/arm64-v8a/libminecraftpe.so': 'b'*64}}
        self.report = self.game.parent/'compatibility'/('a'*64+'.json')

    def run_preflight(self):
        return installer.preflight_runtime(self.app, self.game, self.profile, self.metadata, 'candidate')

    def success(self, command, **kwargs):
        self.assertIn('-B', command)
        self.assertEqual(kwargs['timeout'], 120)
        self.report.parent.mkdir(parents=True, exist_ok=True)
        installer.write_json(self.report, {'schema': 1, 'elf_sha256': 'b'*64, 'rules_sha256': 'a'*64})
        return Mock(returncode=0, stdout='{"ok":true}')

    def test_cache_bound_to_both_elf_and_rules(self):
        with patch.object(installer.subprocess, 'run', side_effect=self.success) as analyze:
            self.assertEqual(self.run_preflight(), str(self.report))
            self.assertEqual(self.run_preflight(), str(self.report))
            self.assertEqual(analyze.call_count, 1)
            cached = json.loads(self.report.read_text()); cached['elf_sha256'] = 'c'*64
            installer.write_json(self.report, cached)
            self.run_preflight()
            self.assertEqual(analyze.call_count, 2)

    def test_rejection_timeout_and_malformed_response_write_diagnostic(self):
        failures = [Mock(returncode=1, stdout='{"ok":false,"error":"unknown dispatcher"}'),
                    subprocess.TimeoutExpired('analyzer', 120), Mock(returncode=0, stdout='[]')]
        for failure in failures:
            with self.subTest(failure=failure):
                options = {'side_effect': failure} if isinstance(failure, Exception) else {'return_value': failure}
                with patch.object(installer.subprocess, 'run', **options):
                    with self.assertRaises(EngineError) as raised:
                        self.run_preflight()
                self.assertEqual(raised.exception.code, 'unsupported_engine_structure')
                data = json.loads(Path(raised.exception.details['diagnostic_path']).read_text())
                self.assertEqual(data['stage'], 'native_compatibility')
                self.assertEqual(data['engine_version'], 'future')
                self.assertFalse(self.report.exists())

    def test_legacy_runtime_does_not_require_analysis(self):
        with patch.object(installer.subprocess, 'run', side_effect=AssertionError('unexpected analyzer')):
            self.assertIsNone(installer.preflight_runtime(self.app, self.game, self.profile, {}, 'legacy'))


class SelectionTests(unittest.TestCase):
    setUp = test_engine_install.InstallerTests.setUp

    def test_failed_preflight_preserves_existing_selection(self):
        installer.install(str(self.catalog), str(self.apk))
        before = (installer.home()/'current.json').read_bytes()
        self.cat['runtime']['id'] = 'candidate2'
        self.catalog.write_text(json.dumps(self.cat))
        with patch.object(installer, 'preflight_runtime', side_effect=EngineError('unknown structure')):
            with self.assertRaises(EngineError):
                installer.install(str(self.catalog), str(self.apk))
        self.assertEqual((installer.home()/'current.json').read_bytes(), before)

    def test_profile_mismatch_requires_explicit_matching_rule_contract(self):
        app = self.root/'McpyRuntime.app'
        meta_path = app/'Contents/Resources/runtime.json'
        integrity = self.root/'McpyRuntime.integrity.json'
        profile = dict(self.profile, id='future', package_name='com.netease.mctest')
        with self.assertRaises(EngineError):
            installer.verify_runtime(app, integrity, profile)
        meta = json.loads(meta_path.read_text())
        meta['game_compatibility'] = {'elf_rules_schema': 1, 'package_name': 'com.netease.mctest', 'abi': 'arm64-v8a'}
        meta_path.write_text(json.dumps(meta))
        manifest = json.loads(integrity.read_text())
        manifest['files']['Contents/Resources/runtime.json'] = installer.digest(meta_path)
        integrity.write_text(json.dumps(manifest))
        installer.verify_runtime(app, integrity, profile)
        with self.assertRaises(EngineError):
            installer.verify_runtime(app, integrity, dict(profile, package_name='other.package'))

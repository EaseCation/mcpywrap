"""Installer verifies before selecting; damaged resources can be repaired offline."""
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest.mock import patch, Mock
import zipfile
from mcpywrap.engines import install as installer
from mcpywrap.engines.host import EngineError


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'MCPY_ENGINE_HOME': str(self.root/'home'), 'MCPY_RUNTIME_CATALOG': ''})
        self.env.start(); self.addCleanup(self.env.stop)
        host = {'backend': 'macos-arm64', 'macos_version': '14.0'}
        for name in ('describe', 'require_macos'):
            mock = patch.object(installer, name, return_value=host)
            mock.start(); self.addCleanup(mock.stop)
        signing = patch.object(installer.subprocess, 'run', return_value=Mock(returncode=0))
        signing.start(); self.addCleanup(signing.stop)
        self.apk = self.root/'dev_launcher_3.9.apk'
        with zipfile.ZipFile(self.apk, 'w') as archive:
            archive.writestr('AndroidManifest.xml', b'fixture')
            archive.writestr('assets/data.bin', b'data')
        self.profile = {'id': 'fixture', 'package_name': 'com.netease.mctest',
                        'apk': {'version': '3.9', 'filename': self.apk.name, 'size': self.apk.stat().st_size,
                                'sha256': installer.digest(self.apk)}, 'unpacked_size': 11, 'file_count': 2,
                        'files': {'AndroidManifest.xml': hashlib.sha256(b'fixture').hexdigest()}}
        app = self.root/'McpyRuntime.app'
        exe = app/'Contents/MacOS/mcpelauncher-client'; exe.parent.mkdir(parents=True)
        exe.write_bytes(struct.pack('<II', 0xfeedfacf, 0x100000c)); exe.chmod(0o755)
        meta = app/'Contents/Resources/runtime.json'; meta.parent.mkdir()
        meta.write_text(json.dumps({'platform': 'darwin-arm64', 'minimum_macos': '11.0',
                                   'launch_protocol': 1, 'client_python_protocol': 1, 'game_profile': self.profile}))
        integrity = self.root/'McpyRuntime.integrity.json'
        integrity.write_text(json.dumps({'files': {str(p.relative_to(app)): installer.digest(p) for p in (exe, meta)}}))
        self.archive = self.root/'runtime.tar.gz'
        with tarfile.open(self.archive, 'w:gz') as archive:
            archive.add(app, arcname=app.name)
            archive.add(integrity, arcname=integrity.name)
        self.cat = {'schema': 1, 'runtime': {'id': 'fixture1', 'platform': 'darwin-arm64',
                    'minimum_macos': '11.0', 'archive_root': app.name, 'url': self.archive.name,
                    'size': self.archive.stat().st_size, 'sha256': installer.digest(self.archive)}, 'profile': self.profile}
        self.catalog = self.root/'catalog.json'; self.catalog.write_text(json.dumps(self.cat))

    def test_install_reuse_repair_and_immutable_release(self):
        first = installer.install(str(self.catalog), str(self.apk))
        self.assertTrue(first['ok'])
        game = Path(first['game'])
        (game/'assets/data.bin').unlink()
        self.assertFalse(installer.diagnose(check_files=True)['ok'])
        with patch.object(installer, 'urlopen', side_effect=AssertionError('network')):
            repaired = installer.install(apk=str(self.apk))
        self.assertTrue(repaired['ok'])
        self.assertEqual((game/'assets/data.bin').read_bytes(), b'data')
        (game/'installed.json').unlink()
        self.assertTrue(installer.install(apk=str(self.apk))['ok'])
        exe = Path(first['runtime'])/'Contents/MacOS/mcpelauncher-client'
        exe.write_bytes(b'broken')
        self.assertTrue(installer.install(apk=str(self.apk))['ok'])
        self.cat['runtime']['sha256'] = '0'*64
        self.catalog.write_text(json.dumps(self.cat))
        with self.assertRaisesRegex(EngineError, '同一运行包 ID'):
            installer.install(str(self.catalog), str(self.apk))

    def test_failed_apk_keeps_retry_source_without_selecting(self):
        with self.assertRaises(EngineError): installer.install(str(self.catalog), str(self.catalog))
        self.assertFalse((installer.home()/'current.json').exists())
        self.assertTrue((installer.home()/'install-plan.json').exists())
        self.assertTrue(installer.install(apk=str(self.apk))['ok'])

    def test_archive_links_and_traversal_rejected(self):
        for name, kind in [('../outside', tarfile.REGTYPE), ('link', tarfile.SYMTYPE)]:
            archive = self.root/'unsafe.tar'
            with tarfile.open(archive, 'w') as tar:
                entry = tarfile.TarInfo(name); entry.type = kind; entry.linkname = '/tmp'
                tar.addfile(entry)
            with self.assertRaises(EngineError): installer.extract_runtime(archive, self.root/'stage')
        self.assertFalse((self.root.parent/'outside').exists())

    def test_download_resume_checks_range_and_checksum(self):
        content = b'fixture-download'
        target = self.root/'cache.bin'
        target.with_suffix('.bin.part').write_bytes(content[:4])
        response = io.BytesIO(content[4:]); response.status = 206
        response.headers = {'Content-Range': 'bytes 4-15/16'}
        with patch.object(installer, 'urlopen', return_value=response) as download:
            installer.fetch('https://example.org/a', target, hashlib.sha256(content).hexdigest(), len(content))
        self.assertEqual(download.call_args.args[0].get_header('Range'), 'bytes=4-')
        self.assertEqual(target.read_bytes(), content)

    def test_os_floor_fails_before_creating_home(self):
        self.cat['runtime']['minimum_macos'] = '99.0'; self.catalog.write_text(json.dumps(self.cat))
        with self.assertRaises(EngineError): installer.install(str(self.catalog), str(self.apk))
        self.assertFalse(installer.home().exists())


if __name__ == '__main__': unittest.main()

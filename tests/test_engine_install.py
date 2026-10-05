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
        integrity.write_text(json.dumps({'files': {p.relative_to(app).as_posix(): installer.digest(p) for p in (exe, meta)}}))
        self.archive = self.root/'runtime.tar.gz'
        with tarfile.open(self.archive, 'w:gz') as archive:
            archive.add(app, arcname=app.name)
            archive.add(integrity, arcname=integrity.name)
        self.cat = {'schema': 1, 'runtime': {'id': 'fixture1', 'platform': 'darwin-arm64',
                    'minimum_macos': '11.0', 'archive_root': app.name, 'url': self.archive.name,
                    'size': self.archive.stat().st_size, 'sha256': installer.digest(self.archive)}, 'profile': self.profile}
        self.catalog = self.root/'catalog.json'; self.catalog.write_text(json.dumps(self.cat))

    def test_fresh_install_uses_bundled_default_catalog_url(self):
        with patch.object(installer, 'urlopen', return_value=io.BytesIO(json.dumps(self.cat).encode())) as download:
            cat, base = installer.catalog()
        self.assertEqual(cat, self.cat)
        self.assertEqual(base, installer.DEFAULT_CATALOG)
        download.assert_called_once_with(installer.DEFAULT_CATALOG, timeout=20)
        self.assertFalse(installer.home().exists())

    def test_pinned_apk_download_does_not_depend_on_moving_discovery_channels(self):
        from urllib.parse import urlsplit, parse_qs
        with patch.object(installer, 'urlopen', side_effect=AssertionError('discovery request')):
            url = installer.official_apk_url(self.profile)
        parsed = urlsplit(url)
        self.assertEqual(parsed.netloc, 'g79.gdl.netease.com')
        self.assertEqual(parsed.path, '/' + self.apk.name)
        self.assertEqual(set(parse_qs(parsed.query)), {'key1', 'key2'})

    def test_catalog_network_failure_does_not_request_manual_configuration(self):
        from urllib.error import URLError
        with patch.object(installer, 'urlopen', side_effect=URLError('offline')):
            with self.assertRaises(EngineError) as caught:
                installer.catalog()
        self.assertEqual(caught.exception.code, 'catalog_download_failed')
        self.assertIn('网络', caught.exception.hint)

    def test_install_reuse_repair_and_immutable_release(self):
        first = installer.install(str(self.catalog), str(self.apk))
        self.assertTrue(first['ok'])
        self.assertEqual(first['cppconfig_protocol'], 0)
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

    def test_transient_download_failure_retries_the_existing_range(self):
        from urllib.error import URLError
        content = b'complete-download'
        target = self.root/'retry.bin'
        target.with_suffix('.bin.part').write_bytes(content[:4])
        response = io.BytesIO(content[4:]); response.status = 206
        response.headers = {'Content-Range': 'bytes 4-%d/%d' % (len(content)-1, len(content))}
        with patch.object(installer, 'urlopen', side_effect=[URLError('temporary TLS failure'), response]) as download, \
                patch.object(installer.time, 'sleep'):
            installer.fetch('https://example.org/file', target, hashlib.sha256(content).hexdigest(), len(content))
        self.assertEqual(target.read_bytes(), content)
        self.assertEqual(download.call_count, 2)
        self.assertTrue(all(call.args[0].get_header('Range') == 'bytes=4-' for call in download.call_args_list))

    def test_cdn_chunks_reuse_contiguous_progress_and_verify_whole_file(self):
        from urllib.error import URLError
        content = b'0123456789abcdef'
        target = self.root/'ranges.bin'
        target.with_suffix('.bin.part').write_bytes(content[:6])
        requested = []
        def response(request, **kwargs):
            value = request.get_header('Range'); requested.append(value)
            start, end = map(int, value.removeprefix('bytes=').split('-'))
            data = io.BytesIO(content[start:end+1]); data.status = 206
            data.headers = {'Content-Range': 'bytes %d-%d/%d' % (start, end, len(content))}
            return data
        with patch.object(installer, 'urlopen', side_effect=response):
            installer._fetch_ranges('https://g79.gdl.netease.com/file', target,
                hashlib.sha256(content).hexdigest(), len(content), chunk_size=4, workers=2)
        self.assertEqual(target.read_bytes(), content)
        self.assertNotIn('bytes=0-3', requested)
        self.assertFalse(target.with_suffix('.bin.ranges.json').exists())

    def test_cdn_invalid_range_is_not_promoted_to_cache(self):
        content = b'abcdefgh'
        target = self.root/'invalid.bin'
        response = io.BytesIO(content); response.status = 200; response.headers = {}
        with patch.object(installer, 'urlopen', return_value=response):
            with self.assertRaises(EngineError):
                installer._fetch_ranges('https://g79.gdl.netease.com/file', target,
                    hashlib.sha256(content).hexdigest(), len(content), chunk_size=8, workers=1)
        self.assertFalse(target.exists())

    def test_cdn_resume_downloads_holes_not_sparse_file_length(self):
        content = b'0123456789abcdef'
        target = self.root/'resume.bin'
        expected = hashlib.sha256(content).hexdigest()
        target.with_suffix('.bin.part').write_bytes(b'\0'*4 + content[4:8] + b'\0'*4 + content[12:])
        target.with_suffix('.bin.ranges.json').write_text(json.dumps({
            'sha256': expected, 'size': len(content), 'chunk_size': 4, 'done': [1, 3]}))
        requested = []
        def response(request, **kwargs):
            start, end = map(int, request.get_header('Range').removeprefix('bytes=').split('-'))
            requested.append(start)
            data = io.BytesIO(content[start:end+1]); data.status = 206
            data.headers = {'Content-Range': 'bytes %d-%d/%d' % (start, end, len(content))}
            return data
        with patch.object(installer, 'urlopen', side_effect=response):
            installer._fetch_ranges('https://g79.gdl.netease.com/file', target,
                expected, len(content), chunk_size=4, workers=2)
        self.assertEqual(set(requested), {0, 8})
        self.assertEqual(target.read_bytes(), content)

    def test_sparse_resume_counts_only_allocated_space(self):
        target = self.root/'sparse.apk'
        size = 128*1024*1024
        part = target.with_suffix('.apk.part')
        with part.open('wb') as stream:
            stream.write(b'partial')
            stream.truncate(size)
        target.with_suffix('.apk.ranges.json').write_text(json.dumps({
            'sha256': 'a'*64, 'size': size, 'chunk_size': 16*1024*1024, 'done': []}))
        remaining = installer._remaining_download(target, 'a'*64, size)
        self.assertEqual(remaining, max(0, size-min(size, getattr(part.stat(), 'st_blocks', 0)*512)))
        self.assertEqual(installer._remaining_download(target, 'b'*64, size), size)

    def test_verified_cache_needs_no_download_space(self):
        self.assertEqual(installer._remaining_download(self.apk, installer.digest(self.apk), self.apk.stat().st_size), 0)

    def test_os_floor_fails_before_creating_home(self):
        self.cat['runtime']['minimum_macos'] = '99.0'; self.catalog.write_text(json.dumps(self.cat))
        with self.assertRaises(EngineError): installer.install(str(self.catalog), str(self.apk))
        self.assertFalse(installer.home().exists())


if __name__ == '__main__': unittest.main()

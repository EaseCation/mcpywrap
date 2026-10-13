"""APK resource identity, Retina artwork, immutable runtime and Qt app branding."""
import os
from pathlib import Path
import plistlib
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
except ImportError:
    QImage = None

from mcpywrap.engines import android_icon, macos_icons, install


def strings(values):
    encoded, offsets = b'', []
    for value in values:
        raw = value.encode()
        offsets.append(len(encoded))
        encoded += bytes([len(value), len(raw)]) + raw + b'\0'
    start = 28 + len(values) * 4
    return (struct.pack('<HHIIIIII', 1, 28, start + len(encoded), len(values), 0, 0x100, start, 0)
            + b''.join(struct.pack('<I', offset) for offset in offsets) + encoded)


def table(paths, *, alias=False, sparse=False, offset16=False):
    pool = strings(paths)
    types = b''
    for i in range(len(paths)):
        # One configuration per image, resource 0x7f010000.
        entries = struct.pack('<HHI', 8, 0, 0) + struct.pack('<HBBI', 8, 0, 3, i)
        if alias:
            entries += struct.pack('<HHI', 8, 0, 0) + struct.pack('<HBBI', 8, 0, 1, 0x7f010000)
        count = 2 if alias else 1
        if sparse:
            offsets = b''.join(struct.pack('<HH', j, j * 4) for j in range(count))
        else:
            offsets = b''.join(struct.pack('<H' if offset16 else '<I', j * (4 if offset16 else 16)) for j in range(count))
        start = 24 + len(offsets)
        types += (struct.pack('<HHIBBHIII', 0x201, 24, start + len(entries), 1,
                              1 if sparse else 2 if offset16 else 0, 0, count, start, 4)
                  + offsets + entries)
    package = struct.pack('<HHII', 0x200, 288, 288 + len(types), 0x7f) + bytes(276) + types
    return struct.pack('<HHII', 2, 12, 12 + len(pool) + len(package), 1) + pool + package


@unittest.skipIf(QImage is None, 'Qt image support unavailable')
class IconTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.game = self.root/'engine/game'
        self.game.mkdir(parents=True)
        self.apk = self.root/'developer.apk'
        self.make_apk()

    def make_apk(self, paths=None):
        paths = paths or ['res/drawable/icon.png', 'res/drawable-xxxhdpi/icon.png', 'res/mipmap-anydpi-v26/icon.xml']
        with zipfile.ZipFile(self.apk, 'w') as archive:
            archive.writestr('AndroidManifest.xml', '<manifest xmlns:android="%s"><application android:icon="@0x7f010000"/></manifest>' % android_icon.ANDROID)
            archive.writestr('resources.arsc', table(paths))
            for path, size in zip(paths, (32, 512, 128)):
                if path.endswith('.xml'):
                    archive.writestr(path, '<adaptive-icon/>')
                else:
                    image = QImage(size, size, QImage.Format.Format_ARGB32)
                    image.fill(Qt.GlobalColor.green)
                    archive.writestr(path, macos_icons._png(image))
            # A larger unrelated image must not be selected.
            image = QImage(1024, 1024, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.red)
            archive.writestr('res/drawable/notification.png', macos_icons._png(image))
        self.profile = {'apk': {'filename': self.apk.name, 'size': self.apk.stat().st_size,
                                'sha256': install.digest(self.apk)}}
        install.write_json(self.game/'installed.json', {'profile': self.profile})

    def test_resolves_declared_icon_and_largest_raster_variant(self):
        with zipfile.ZipFile(self.apk) as archive:
            path, image = android_icon.read_icon(archive)
        self.assertEqual(path, 'res/drawable-xxxhdpi/icon.png')
        self.assertEqual(image.width(), 512)
        self.assertEqual(image.pixelColor(0, 0), Qt.GlobalColor.green)

    def test_alias_sparse_and_offset16_resources(self):
        for options in ({}, {'sparse': True}, {'offset16': True}):
            self.assertEqual(android_icon.resource_values(table(['res/drawable/icon.png'], alias=True, **options), 0x7f010001), ['res/drawable/icon.png'])

    def test_binary_manifest_application_icon(self):
        pool = strings(['application', android_icon.ANDROID, 'icon'])
        attr = struct.pack('<IIIHBBI', 1, 2, 0xffffffff, 8, 0, 1, 0x7f010000)
        element = (struct.pack('<HHIII', 0x102, 16, 56, 1, 0xffffffff)
                   + struct.pack('<IIHHHHHH', 0xffffffff, 0, 20, 20, 1, 0, 0, 0) + attr)
        data = struct.pack('<HHI', 3, 8, 8 + len(pool) + len(element)) + pool + element
        self.assertEqual(android_icon.manifest_icon(data), 0x7f010000)
        with self.assertRaises(ValueError):
            android_icon.manifest_icon(data[:-1])

    def test_adaptive_xml_is_not_mistaken_for_bitmap(self):
        self.make_apk(['res/mipmap-anydpi-v26/icon.xml'])
        with zipfile.ZipFile(self.apk) as archive, self.assertRaisesRegex(ValueError, 'raster variant'):
            android_icon.read_icon(archive)

    def test_icon_cache_can_be_reused_offline_and_repaired(self):
        before = (self.game/'installed.json').read_bytes()
        directory = macos_icons.prepare_icons(self.game, self.profile, self.apk)
        with patch.object(install, 'digest', wraps=install.digest) as digest:
            self.assertEqual(macos_icons.prepare_icons(self.game, self.profile), directory)
        self.assertNotIn(self.apk, [call.args[0] for call in digest.call_args_list])
        (directory/'game.icns').write_bytes(b'corrupt')
        macos_icons.prepare_icons(self.game, self.profile, self.apk)
        self.assertTrue(macos_icons._valid_icons(directory, self.profile))
        self.assertEqual((self.game/'installed.json').read_bytes(), before)
        self.assertEqual(list(self.game.iterdir()), [self.game/'installed.json'])

    def test_mismatched_apk_is_not_used(self):
        self.profile['apk']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, '摘要不匹配'):
            macos_icons.prepare_icons(self.game, self.profile, self.apk)
        self.assertFalse((self.game.parent/'icons').exists())

    def test_icns_representations_and_transparency(self):
        image = QImage(100, 50, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.blue)
        macos_icons.write_icons(image, self.root/'icons')
        raw = (self.root/'icons/game.icns').read_bytes()
        self.assertEqual(raw[:4], b'icns')
        self.assertEqual(struct.unpack_from('>I', raw, 4)[0], len(raw))
        chunks, at = {}, 8
        while at < len(raw):
            tag, size = struct.unpack_from('>4sI', raw, at)
            chunks[tag] = QImage.fromData(raw[at + 8:at + size])
            at += size
        self.assertEqual(chunks[b'ic10'].width(), 1024)
        self.assertEqual(chunks[b'ic11'].width(), 32)
        self.assertEqual(chunks[b'ic14'].width(), 512)
        self.assertEqual(chunks[b'ic10'].pixelColor(0, 0).alpha(), 0)
        self.assertEqual(chunks[b'ic10'].pixelColor(512, 512), Qt.GlobalColor.blue)

    def test_derived_app_keeps_original_bytes_and_requires_signature(self):
        macos_icons.prepare_icons(self.game, self.profile, self.apk)
        app = self.root/'runtime/McpyRuntime.app'
        (app/'Contents/Resources').mkdir(parents=True)
        (app/'Contents/MacOS').mkdir()
        (app/'Contents/MacOS/mcpelauncher-client').write_bytes(b'fake executable')
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable': 'mcpelauncher-client'}))
        install.write_json(app.parent/'McpyRuntime.integrity.json', {'fixture': True})
        before = {str(p.relative_to(app)): p.read_bytes() for p in app.rglob('*') if p.is_file()}
        with patch.object(macos_icons, '_codesign') as sign:
            derived = macos_icons.runtime_application(app, self.game)
            self.assertEqual(sign.call_count, 2)
            self.assertEqual(macos_icons.runtime_application(app, self.game), derived)
            self.assertEqual(sign.call_count, 3)  # Cache signature is checked too.
        self.assertEqual(before, {str(p.relative_to(app)): p.read_bytes() for p in app.rglob('*') if p.is_file()})
        self.assertEqual(plistlib.loads((derived/'Contents/Info.plist').read_bytes())['CFBundleIconFile'], 'game.icns')
        with patch.object(macos_icons, '_codesign', side_effect=ValueError('signing failed')), \
                patch.object(install, '_require_idle'), patch.object(macos_icons, 'warn_icon'):
            self.assertEqual(macos_icons.optional_runtime_application(app, self.game), app)

    def test_gui_identity_and_packaged_icon(self):
        from mcpywrap.ui.application import create_application, application_icon
        app = create_application()
        self.assertEqual(app.applicationName(), 'mcpy')
        self.assertEqual(app.applicationDisplayName(), 'mcpy')
        self.assertFalse(app.windowIcon().isNull())
        self.assertFalse(application_icon().pixmap(32, 32).isNull())


if __name__ == '__main__':
    unittest.main()

"""Local APK artwork and signed, disposable app copies; release files stay immutable."""
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import tempfile
import zipfile
import zlib
from xml.etree.ElementTree import ParseError

from . import install

SCHEMA = 1


def _png(image):
    from PySide6.QtCore import QBuffer, QIODevice
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, 'PNG'):
        raise ValueError('Could not encode application icon')
    return bytes(buffer.data())


def write_icons(image, directory):
    """Encode RGBA PNG representations at macOS point/Retina sizes in an ICNS."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    canvas = QImage(1024, 1024, QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    scaled = image.scaled(1024, 1024, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
    painter = QPainter(canvas)
    painter.drawImage((1024 - scaled.width()) // 2, (1024 - scaled.height()) // 2, scaled)
    painter.end()
    (directory/'game.png').write_bytes(_png(canvas))
    chunks = []
    for tag, size in ((b'icp4', 16), (b'icp5', 32), (b'icp6', 64), (b'ic07', 128),
                      (b'ic08', 256), (b'ic09', 512), (b'ic10', 1024),
                      (b'ic11', 32), (b'ic12', 64), (b'ic13', 256), (b'ic14', 512)):
        raw = _png(canvas.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation))
        chunks.append(tag + struct.pack('>I', len(raw) + 8) + raw)
    payload = b''.join(chunks)
    (directory/'game.icns').write_bytes(b'icns' + struct.pack('>I', len(payload) + 8) + payload)


def _valid_icons(directory, profile):
    try:
        receipt = install.read_json(directory/'icon.json')
        return (receipt['schema'] == SCHEMA and receipt['apk_sha256'] == profile['apk']['sha256']
                and all(install.digest(directory/name) == receipt['files'][name]
                        for name in ('game.png', 'game.icns')))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def prepare_icons(game, profile, apk=None):
    """Migrate existing installs using a matching cache, without another download."""
    from .android_icon import read_icon
    game = Path(game)
    directory = game.parent/'icons'
    if _valid_icons(directory, profile):
        return directory
    source = Path(apk) if apk else install.home()/'cache'/profile['apk']['filename']
    if not source.is_file():
        raise ValueError('找不到匹配 APK；可用 mcpy engine install --apk <原 APK> 补全游戏图标')
    if source.stat().st_size != profile['apk']['size'] or install.digest(source) != profile['apk']['sha256']:
        raise ValueError('图标来源 APK 摘要不匹配')
    game.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.icons-', dir=game.parent))
    try:
        with zipfile.ZipFile(source) as archive:
            resource, image = read_icon(archive)
        write_icons(image, stage)
        install.write_json(stage/'icon.json', {
            'schema': SCHEMA, 'apk_sha256': profile['apk']['sha256'], 'resource': resource,
            'source_size': [image.width(), image.height()],
            'files': {name: install.digest(stage/name) for name in ('game.png', 'game.icns')}})
        install._replace(stage, directory)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return directory


def _codesign(*arguments):
    result = subprocess.run(['/usr/bin/codesign', *map(str, arguments)], capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError('本地图标运行包签名失败：' + result.stderr.decode('utf-8', 'replace')[:1000])


def runtime_application(app, game):
    """Build once per verified runtime/icon. Caller holds the engine install lock."""
    app, game = Path(app), Path(game)
    profile = install.read_json(game/'installed.json')['profile']
    icons = prepare_icons(game, profile)
    identity = {'schema': SCHEMA, 'runtime': install.digest(app.parent/'McpyRuntime.integrity.json'),
                'icon': install.digest(icons/'game.icns')}
    import hashlib
    import json
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    destination = app.parent/'applications'/key
    name = 'Minecraft China.app'
    derived = destination/name
    try:
        if install.read_json(destination/'application.json') == identity:
            _codesign('--verify', '--deep', '--strict', derived)
            return derived
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    if destination.exists():
        install._require_idle(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.application-', dir=destination.parent))
    try:
        target = stage/name
        shutil.copytree(app, target)
        shutil.copy2(icons/'game.icns', target/'Contents/Resources/game.icns')
        plist = target/'Contents/Info.plist'
        info = plistlib.loads(plist.read_bytes())
        info.update(CFBundleName='我的世界中国版', CFBundleDisplayName='我的世界中国版',
                    CFBundleIconFile='game.icns', CFBundleIdentifier='net.easecation.mcpy.game.' + key[:16])
        plist.write_bytes(plistlib.dumps(info))
        _codesign('--force', '--sign', '-', '--preserve-metadata=entitlements,flags', '--timestamp=none', target)
        _codesign('--verify', '--deep', '--strict', target)
        install.write_json(stage/'application.json', identity)
        install._replace(stage, destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return derived


def warn_icon(error):
    # Called by both JSON CLI and workers; warnings must never contaminate stdout.
    import sys
    print('游戏图标暂未应用：' + str(error), file=sys.stderr, flush=True)


def optional_icons(game, profile, apk=None):
    try:
        return prepare_icons(game, profile, apk)
    except (OSError, ValueError, KeyError, IndexError, struct.error, zipfile.BadZipFile,
            zlib.error, ParseError, ImportError) as error:
        warn_icon(error)
        return None


def optional_runtime_application(app, game):
    try:
        return runtime_application(app, game)
    except (OSError, ValueError, KeyError, IndexError, struct.error, zipfile.BadZipFile,
            zlib.error, ParseError, ImportError, subprocess.SubprocessError) as error:
        warn_icon(error)
        return Path(app)

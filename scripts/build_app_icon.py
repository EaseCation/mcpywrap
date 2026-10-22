"""Render mcpy's editable Icon Composer source with Apple's macOS 27 renderer.

Developer-only: requires Xcode 27 / Icon Composer 27 and PySide6. End users need
neither Xcode nor Icon Composer; wheels include the rendered PNG/ICNS assets.
"""
from pathlib import Path
import subprocess
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QColorSpace

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT/'core/mcpywrap_core/ui/assets'


def main():
    developer = Path(subprocess.check_output(['xcode-select', '-p'], text=True).strip())
    tool = developer.parent/'Applications/Icon Composer.app/Contents/Executables/ictool'
    with tempfile.TemporaryDirectory() as temporary:
        temporary = Path(temporary)
        rendered = temporary/'rendered.png'
        subprocess.run([str(tool), str(ASSETS/'mcpy.icon'), '--export-image',
                        '--output-file', str(rendered), '--platform', 'macOS',
                        '--rendition', 'Default', '--width', '1024', '--height', '1024',
                        '--scale', '1', '--design-generation', '27'], check=True)
        source = QImage(str(rendered))
        if source.isNull():
            raise RuntimeError('Icon Composer did not produce an image')
        # ictool exports the icon face full-bleed. Legacy Qt/ICNS consumers need
        # Dock canvas padding, matching actool's macOS compatibility output:
        # 100 pt inset on a 1024 pt canvas (face width 824 pt).
        canvas = QImage(1024, 1024, QImage.Format.Format_ARGB32)
        canvas.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.drawImage(100, 100, source.scaled(824, 824, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation))
        painter.end()
        if not canvas.save(str(ASSETS/'mcpy.png')):
            raise RuntimeError('Could not save mcpy.png')
        iconset = temporary/'mcpy.iconset'
        iconset.mkdir()
        for points in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                name = 'icon_%dx%d%s.png' % (points, points, '@2x' if scale == 2 else '')
                image = canvas.scaled(points * scale, points * scale, Qt.AspectRatioMode.IgnoreAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
                if not image.save(str(iconset/name)):
                    raise RuntimeError('Could not save ' + name)
        subprocess.run(['/usr/bin/iconutil', '-c', 'icns', str(iconset), '-o', str(ASSETS/'mcpy.icns')], check=True)


if __name__ == '__main__':
    main()

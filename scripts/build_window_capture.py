"""Build the optional x64 Windows Graphics Capture helper."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='cl', help='x64 MSVC cl executable')
    parser.add_argument('--output', type=Path,
                        default=Path('mcpywrap/mcstudio/window_capture'))
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('This build requires Windows')
    compiler = Path(shutil.which(args.cc) or args.cc).resolve()
    if not compiler.is_file():
        parser.error('x64 MSVC cl.exe was not found')
    if os.environ.get('VSCMD_ARG_TGT_ARCH') not in (None, 'x64'):
        parser.error('Use an x64 Visual Studio developer environment')

    root = Path(__file__).resolve().parent.parent
    source = root / 'native/window_capture/window_capture.cpp'
    output = (root / args.output).resolve() if not args.output.is_absolute() else args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    target = output / 'mcpy-window-capture.exe'
    command = [
        str(compiler), '/nologo', '/std:c++20', '/EHsc', '/O2', '/MT', '/utf-8',
        str(source), '/Fe:' + str(target),
        '/link', '/MACHINE:X64',
        'd3d11.lib', 'dxgi.lib', 'dwmapi.lib', 'ole32.lib', 'user32.lib',
        'windowscodecs.lib', 'windowsapp.lib',
    ]
    subprocess.run(command, cwd=root, check=True)
    manifest = {
        'executable_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
        'source_sha256': hashlib.sha256(source.read_text(encoding='utf-8').encode('utf-8')).hexdigest(),
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Built Windows Graphics Capture helper:', target)


if __name__ == '__main__':
    main()

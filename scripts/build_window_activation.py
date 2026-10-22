"""Build the x64 process-scoped background activation guard."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='cl')
    parser.add_argument('--output', type=Path, default=Path('desktop/mcpywrap_assets/window_activation'))
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('This build requires Windows')
    compiler = Path(shutil.which(args.cc) or args.cc).resolve()
    if not compiler.is_file() or os.environ.get('VSCMD_ARG_TGT_ARCH') not in (None, 'x64'):
        parser.error('Use an x64 Visual Studio developer environment')
    root = Path(__file__).resolve().parents[1]
    source = root/'native/window_activation/window_activation.cpp'
    output = (root/args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    target = output/'mcpy-window-activation.dll'
    with tempfile.TemporaryDirectory(prefix='mcpy-activation-build-') as temp:
        subprocess.run([str(compiler), '/nologo', '/std:c++17', '/EHsc', '/O2', '/MT', '/utf-8', '/LD',
                        str(source), '/Fe:' + str(target), '/link', '/MACHINE:X64', 'user32.lib'], cwd=temp, check=True)
    manifest = {'background_window_protocol': 1, 'architecture': 'x64',
                'dll_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                'source_sha256': hashlib.sha256(source.read_text(encoding='utf8').encode('utf8')).hexdigest()}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf8')
    print('Built background activation guard:', target)


if __name__ == '__main__':
    main()

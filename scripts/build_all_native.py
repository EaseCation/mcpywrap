"""Build every Windows native component from a source checkout."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path,
                        help='Build into BRIDGE and CAPTURE subdirectories here; default is package payload directories')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Native components can only be built on Windows')

    root = Path(__file__).resolve().parent.parent
    vswhere = Path(os.environ.get('ProgramFiles(x86)', '')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    if not vswhere.is_file():
        parser.error('Visual Studio Build Tools with the x86/x64 C++ workload are required')
    query = subprocess.run(
        [str(vswhere), '-latest', '-products', '*',
         '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
         '-property', 'installationPath'],
        capture_output=True, text=True, encoding='mbcs', errors='replace', check=True)
    installation = query.stdout.strip()
    devcmd = Path(installation) / 'Common7/Tools/VsDevCmd.bat'
    if not installation or not devcmd.is_file():
        parser.error('A complete Visual Studio x86/x64 C++ installation was not found')

    if args.output_root:
        output_root = args.output_root.resolve()
        bridge_output = output_root / 'bridge'
        capture_output = output_root / 'capture'
    else:
        bridge_output = root / 'mcpywrap/mcstudio/bridge_payload'
        capture_output = root / 'mcpywrap/mcstudio/window_capture'

    with tempfile.TemporaryDirectory(prefix='mcpy-native-') as temporary:
        for arch, script, output in (
            ('x86', 'build_mcs_auth_bridge.py', bridge_output),
            ('x64', 'build_window_capture.py', capture_output),
        ):
            python_command = subprocess.list2cmdline([
                sys.executable, str(root / 'scripts' / script), '--cc', 'cl', '--output', str(output),
            ])
            batch = Path(temporary) / f'build-{arch}.cmd'
            batch.write_text('\n'.join([
                '@echo off',
                f'call "{devcmd}" -arch={arch} -host_arch=x64',
                'if errorlevel 1 exit /b %errorlevel%',
                python_command,
                'exit /b %errorlevel%',
                '',
            ]), encoding='mbcs')
            subprocess.run(['cmd.exe', '/d', '/c', str(batch)], cwd=root, check=True)
    print('Built all native components:', bridge_output, capture_output)


if __name__ == '__main__':
    main()

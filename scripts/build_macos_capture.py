"""Build the arm64 macOS ScreenCaptureKit recording helper and ad-hoc sign it."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'native/macos_capture/macos_capture.swift'
NAME = 'mcpy-macos-capture'


def manifest(target):
    return {
        'executable_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
        'source_sha256': hashlib.sha256(SOURCE.read_text(encoding='utf-8').encode('utf-8')).hexdigest(),
        'sources': {p.name: hashlib.sha256(p.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
                    for p in sorted(SOURCE.parent.glob('*.swift'))},
        'media_protocol': 1,
        'architecture': 'arm64',
        'minimum_macos': '13.0',
        'signing': 'ad-hoc',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('desktop/mcpywrap_assets/macos_capture'))
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('This build requires macOS with the Xcode command line tools')
    output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    target = output / NAME
    subprocess.run(['xcrun', 'swiftc', '-O', '-parse-as-library', '-target', 'arm64-apple-macos13.0',
                    str(SOURCE), '-o', str(target)], cwd=ROOT, check=True)
    # 开发签名：ad-hoc 签名满足 Apple Silicon 的可执行要求；没有 Developer ID 与公证，
    # 经 pip 安装的文件不带隔离属性，因此不触发 Gatekeeper 下载检查。
    subprocess.run(['codesign', '--force', '--sign', '-', '--options', 'runtime', str(target)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(target)], check=True)
    (output / 'manifest.json').write_text(json.dumps(manifest(target), indent=2), encoding='utf-8')
    print('Built macOS capture helper:', target)


if __name__ == '__main__':
    main()

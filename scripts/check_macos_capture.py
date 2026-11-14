"""Verify the bundled arm64 macOS capture helper and its source."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
source = root / 'native/macos_capture/macos_capture.swift'
payload = root / 'desktop/mcpywrap_assets/macos_capture'
executable = payload / 'mcpy-macos-capture'
manifest = json.loads((payload / 'manifest.json').read_text(encoding='utf-8'))
assert set(manifest) == {'executable_sha256', 'source_sha256', 'sources', 'media_protocol', 'architecture',
                         'minimum_macos', 'signing'}
assert manifest['media_protocol'] == 1 and manifest['architecture'] == 'arm64' and manifest['signing'] == 'ad-hoc'
assert set(manifest['sources']) == {'macos_capture.swift'}
for name, digest in manifest['sources'].items():
    assert hashlib.sha256((source.parent / name).read_text(encoding='utf-8').encode('utf-8')).hexdigest() == digest
assert hashlib.sha256(source.read_text(encoding='utf-8').encode('utf-8')).hexdigest() == manifest['source_sha256']
data = executable.read_bytes()
assert hashlib.sha256(data).hexdigest() == manifest['executable_sha256']
# 64 位 Mach-O，CPU_TYPE_ARM64 = 0x0100000c；不接受通用二进制或 x86_64。
assert struct.unpack_from('<I', data, 0)[0] == 0xfeedfacf
assert struct.unpack_from('<I', data, 4)[0] == 0x0100000c
if sys.platform == 'darwin':
    subprocess.run(['codesign', '--verify', '--strict', str(executable)], check=True)
print('macOS capture helper and source match; Mach-O architecture is arm64')

"""Verify the bundled x64 window capture helper and its source."""
import hashlib
import json
from pathlib import Path
import struct


root = Path(__file__).resolve().parent.parent
source = root / 'native/window_capture/window_capture.cpp'
payload = root / 'mcpywrap/mcstudio/window_capture'
executable = payload / 'mcpy-window-capture.exe'
manifest = json.loads((payload / 'manifest.json').read_text(encoding='utf-8'))
assert set(manifest) == {'executable_sha256', 'source_sha256'}
assert hashlib.sha256(source.read_text(encoding='utf-8').encode('utf-8')).hexdigest() == manifest['source_sha256']
data = executable.read_bytes()
assert hashlib.sha256(data).hexdigest() == manifest['executable_sha256']
offset = struct.unpack_from('<I', data, 0x3c)[0]
assert data[:2] == b'MZ' and data[offset:offset + 4] == b'PE\0\0'
assert struct.unpack_from('<H', data, offset + 4)[0] == 0x8664
print('Window capture helper and source match; PE architecture is x64')

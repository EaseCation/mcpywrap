"""Verify the shipped bridge, its public certificate, and matching native sources."""
import hashlib
import json
import argparse
from pathlib import Path
import struct

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--require-signed', action='store_true')
options = parser.parse_args()

root = Path(__file__).resolve().parent.parent
payload = root/'mcpywrap/mcstudio/bridge_payload'
manifest = json.loads((payload/'manifest.json').read_text(encoding='utf-8'))
publisher = json.loads((root/'native/mcs_auth/publisher.json').read_text(encoding='utf-8-sig'))
assert manifest['thumbprint'] == publisher['thumbprint']
assert manifest['files']['publisher.cer'] == publisher['certificate_sha256']
if options.require_signed:
    assert manifest.get('signed') is True, 'Release payload must be signed'
assert set(manifest['files']) == {'Injector.exe', 'Loader.dll', 'McpyMcsAuth.dll', 'publisher.cer'}
for name, expected in manifest['files'].items():
    assert hashlib.sha256((payload/name).read_bytes()).hexdigest() == expected, name
    if name.endswith(('.exe', '.dll')):
        data = (payload/name).read_bytes()
        offset = struct.unpack_from('<I', data, 0x3c)[0]
        assert struct.unpack_from('<H', data, offset+4)[0] == 0x14c, name
for name, expected in manifest['sources'].items():
    text = (root/'native/mcs_auth'/name).read_text(encoding='utf-8')
    assert hashlib.sha256(text.encode('utf-8')).hexdigest() == expected, name
assert not any(p.suffix in ('.pfx', '.p12', '.key') for p in payload.iterdir())
print('Bridge payload, public certificate and native sources match; no private keys bundled')

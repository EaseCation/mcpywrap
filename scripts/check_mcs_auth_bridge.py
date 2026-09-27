"""Verify the shipped bridge, its public certificate, and matching native sources."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
payload = root/'mcpywrap/mcstudio/bridge_payload'
manifest = json.loads((payload/'manifest.json').read_text(encoding='utf-8'))
assert set(manifest['files']) == {'Injector.exe', 'Loader.dll', 'McpyMcsAuth.dll', 'publisher.cer'}
for name, expected in manifest['files'].items():
    assert hashlib.sha256((payload/name).read_bytes()).hexdigest() == expected, name
for name, expected in manifest['sources'].items():
    text = (root/'native/mcs_auth'/name).read_text(encoding='utf-8')
    assert hashlib.sha256(text.encode('utf-8')).hexdigest() == expected, name
assert not any(p.suffix in ('.pfx', '.p12', '.key') for p in payload.iterdir())
print('Bridge payload, public certificate and native sources match; no private keys bundled')

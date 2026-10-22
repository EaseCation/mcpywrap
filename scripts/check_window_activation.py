"""Verify the built activation guard without loading Windows code on other hosts."""
import hashlib
import json
from pathlib import Path
import struct


def main():
    root = Path(__file__).resolve().parents[1]
    payload = root/'desktop/mcpywrap_assets/window_activation'
    manifest = json.loads((payload/'manifest.json').read_text(encoding='utf8'))
    binary = (payload/'mcpy-window-activation.dll').read_bytes()
    assert manifest['background_window_protocol'] == 1 and manifest['architecture'] == 'x64'
    assert hashlib.sha256(binary).hexdigest() == manifest['dll_sha256']
    source = (root/'native/window_activation/window_activation.cpp').read_text(encoding='utf8').encode('utf8')
    assert hashlib.sha256(source).hexdigest() == manifest['source_sha256']
    assert binary[:2] == b'MZ'
    header = struct.unpack_from('<I', binary, 0x3c)[0]
    assert binary[header:header+4] == b'PE\0\0'
    assert struct.unpack_from('<H', binary, header+4)[0] == 0x8664
    print('Windows activation guard: x64, protocol and hashes verified')


if __name__ == '__main__':
    main()

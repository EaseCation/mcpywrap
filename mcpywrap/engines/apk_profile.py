"""Inspect downloaded APK bytes before deriving a local compatibility profile."""
import hashlib
import struct
import zipfile
import zlib
from xml.etree import ElementTree
from pathlib import Path
from .host import EngineError


def package_name(data):
    """Read the manifest package from Android's binary XML string/element chunks."""
    if data.lstrip().startswith(b'<'):
        return ElementTree.fromstring(data).attrib.get('package')
    def u16(at): return struct.unpack_from('<H', data, at)[0]
    def u32(at): return struct.unpack_from('<I', data, at)[0]
    if u16(0) != 3 or u32(4) != len(data): raise ValueError('Invalid binary manifest')
    strings = []
    at = u16(2)
    while at < len(data):
        kind, header, size = u16(at), u16(at+2), u32(at+4)
        if size < header or header < 8 or at+size > len(data): raise ValueError('Invalid XML chunk')
        if kind == 1:
            count, flags, start = u32(at+8), u32(at+16), u32(at+20)
            if count > size//4: raise ValueError('Invalid string pool')
            def length(pos, utf8):
                value = data[pos] if utf8 else u16(pos)
                width, mask = (1, 0x80) if utf8 else (2, 0x8000)
                if value & mask:
                    low = data[pos+width] if utf8 else u16(pos+width)
                    return ((value & (mask-1)) << (width*8)) | low, pos+width*2
                return value, pos+width
            for i in range(count):
                pos = at+start+u32(at+header+i*4)
                utf8 = bool(flags & 0x100)
                n, pos = length(pos, utf8)
                if utf8: n, pos = length(pos, True)
                end = pos+n*(1 if utf8 else 2)
                if pos < at or end > at+size: raise ValueError('Invalid string extent')
                strings.append(data[pos:end].decode('utf-8' if utf8 else 'utf-16-le'))
        elif kind == 0x102:
            ext = at+header
            if strings[u32(ext+4)] == 'manifest':
                offset, width, count = u16(ext+8), u16(ext+10), u16(ext+12)
                if width < 20 or ext+offset+width*count > at+size: raise ValueError('Invalid attributes')
                for i in range(count):
                    attr = ext+offset+i*width
                    if strings[u32(attr+4)] == 'package':
                        raw = u32(attr+8)
                        return strings[raw] if raw != 0xffffffff else strings[u32(attr+16)]
        at += size
    raise ValueError('Package not found')


def inspect_apk(path, version):
    from .install import digest, safe_member
    path = Path(path)
    try:
        files, count, total, seen = {}, 0, 0, set()
        critical = {'AndroidManifest.xml', 'lib/arm64-v8a/libminecraftpe.so', 'assets/assets/vanilla.mcp'}
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                name = item.filename
                if name != 'AndroidManifest.xml' and not name.startswith(('assets/', 'lib/arm64-v8a/')): continue
                safe_member(name)
                if name.casefold() in seen or (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('Duplicate or linked APK member')
                seen.add(name.casefold())
                if item.is_dir(): continue
                count += 1; total += item.file_size
                if total > 32*1024**3 or count > 200000: raise ValueError('APK exceeds installation limit')
                if name in critical:
                    h = hashlib.sha256()
                    with archive.open(item) as stream:
                        head = stream.read(64); h.update(head)
                        if name.endswith('.so') and (head[:5] != b'\x7fELF\x02' or head[5] != 1 or struct.unpack_from('<H', head, 18)[0] != 183):
                            raise ValueError('Game library is not ARM64 ELF')
                        for block in iter(lambda: stream.read(1024*1024), b''): h.update(block)
                    files[name] = h.hexdigest()
            manifest = archive.getinfo('AndroidManifest.xml')
            if manifest.file_size > 4*1024*1024: raise ValueError('Manifest too large')
            package = package_name(archive.read(manifest))
            if package != 'com.netease.mctest' or set(files) != critical:
                raise ValueError('Not an ARM64 developer APK')
        return {'id': 'netease-dev-'+version+'-arm64', 'package_name': package,
                'apk': {'version': version, 'filename': path.name, 'size': path.stat().st_size, 'sha256': digest(path)},
                'unpacked_size': total, 'file_count': count, 'files': files}
    except (ValueError, KeyError, IndexError, struct.error, zipfile.BadZipFile, zlib.error, ElementTree.ParseError, EOFError) as error:
        raise EngineError('下载的开发者 APK 无法通过校验：'+str(error), 'invalid_apk',
                          '未替换现有游戏环境；请重试或反馈此版本。') from None

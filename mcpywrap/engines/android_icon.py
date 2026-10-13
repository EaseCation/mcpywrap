"""Read an APK's declared launcher icon, without an Android SDK or filename guesses.

Prefer the largest raster variant of application/@android:icon. Adaptive XML
is not a bitmap: use its legacy variant when present, otherwise report that it
cannot be converted. No unrelated notification/login artwork is substituted.
"""
import struct
from xml.etree import ElementTree

ANDROID = 'http://schemas.android.com/apk/res/android'


def _u16(data, offset):
    return struct.unpack_from('<H', data, offset)[0]


def _u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def _chunks(data, start, end):
    while start < end:
        kind, header, size = struct.unpack_from('<HHI', data, start)
        if header < 8 or size < header or start + size > end:
            raise ValueError('Invalid Android resource chunk')
        yield kind, header, data[start:start + size]
        start += size


def _strings(data):
    header = _u16(data, 2)
    count, flags, start = _u32(data, 8), _u32(data, 16), _u32(data, 20)
    if header + count * 4 > len(data):
        raise ValueError('Invalid Android string pool')
    utf8 = bool(flags & 0x100)

    def length(pos):
        value = data[pos] if utf8 else _u16(data, pos)
        width, mask = (1, 0x80) if utf8 else (2, 0x8000)
        if value & mask:
            low = data[pos + width] if utf8 else _u16(data, pos + width)
            return ((value & (mask - 1)) << (width * 8)) | low, pos + width * 2
        return value, pos + width

    result = []
    for index in range(count):
        pos = start + _u32(data, header + index * 4)
        if pos < start or pos >= len(data):
            raise ValueError('Invalid Android string offset')
        size, pos = length(pos)
        if utf8:
            size, pos = length(pos)
        end = pos + size * (1 if utf8 else 2)
        if end > len(data):
            raise ValueError('Invalid Android string extent')
        result.append(data[pos:end].decode('utf-8' if utf8 else 'utf-16-le'))
    return result


def manifest_icon(data):
    if data.lstrip().startswith(b'<'):
        application = ElementTree.fromstring(data).find('application')
        value = application.get('{%s}icon' % ANDROID) if application is not None else None
        if value and value.startswith('@0x'):
            return int(value[1:], 16)
        return value
    if _u16(data, 0) != 3 or _u32(data, 4) != len(data):
        raise ValueError('Invalid Android manifest')
    strings = []
    for kind, header, chunk in _chunks(data, _u16(data, 2), len(data)):
        if kind == 1:
            strings = _strings(chunk)
        elif kind == 0x102 and strings[_u32(chunk, header + 4)] == 'application':
            offset, width, count = struct.unpack_from('<HHH', chunk, header + 8)
            if width < 20 or header + offset + width * count > len(chunk):
                raise ValueError('Invalid manifest attributes')
            for index in range(count):
                at = header + offset + index * width
                namespace, name = _u32(chunk, at), _u32(chunk, at + 4)
                if namespace != 0xffffffff and strings[namespace] == ANDROID and strings[name] == 'icon':
                    kind, value = chunk[at + 15], _u32(chunk, at + 16)
                    if kind == 1:
                        return value
                    if kind == 3:
                        return strings[value]
    return None


def resource_values(data, resource):
    """Resolve simple resource references across configurations, including aliases."""
    if _u16(data, 0) != 2 or _u32(data, 4) != len(data):
        raise ValueError('Invalid Android resource table')
    global_strings, packages = [], []
    for kind, header, chunk in _chunks(data, _u16(data, 2), len(data)):
        if kind == 1:
            global_strings = _strings(chunk)
        elif kind == 0x200:
            packages.append((header, chunk))

    def resolve(identity, seen):
        if identity in seen or len(seen) > 16:
            return []
        seen = seen | {identity}
        values = []
        for header, package in packages:
            if _u32(package, 8) != identity >> 24:
                continue
            type_offset = _u32(package, 284) if header >= 288 else 0
            for kind, size, chunk in _chunks(package, header, len(package)):
                if kind != 0x201 or chunk[8] + type_offset != (identity >> 16) & 255:
                    continue
                count, start, index = _u32(chunk, 12), _u32(chunk, 16), identity & 0xffff
                flags = chunk[9]
                if start < size or start > len(chunk):
                    raise ValueError('Invalid Android entries')
                if flags & 1:  # Sparse (entry index, offset / 4) pairs.
                    if size + count * 4 > start:
                        raise ValueError('Invalid sparse entries')
                    offsets = dict(struct.unpack_from('<HH', chunk, size + i * 4) for i in range(count))
                    offset = offsets.get(index)
                    if offset is None:
                        continue
                    offset *= 4
                else:
                    width = 2 if flags & 2 else 4
                    if size + count * width > start:
                        raise ValueError('Invalid entry offsets')
                    if index >= count:
                        continue
                    offset = (_u16 if width == 2 else _u32)(chunk, size + index * width)
                    if offset == (0xffff if width == 2 else 0xffffffff):
                        continue
                    if width == 2:
                        offset *= 4
                at = start + offset
                entry_size, entry_flags = struct.unpack_from('<HH', chunk, at)
                if entry_flags & 1:  # Complex/bag entry.
                    continue
                if entry_flags & 8:  # Compact entry packs type into flags, value into key.
                    value_kind, value = entry_flags >> 8, _u32(chunk, at + 4)
                else:
                    if entry_size < 8 or at + entry_size + 8 > len(chunk):
                        raise ValueError('Invalid resource value')
                    value_kind, value = chunk[at + entry_size + 3], _u32(chunk, at + entry_size + 4)
                if value_kind == 3:
                    values.append(global_strings[value])
                elif value_kind == 1:
                    values.extend(resolve(value, seen))
        return values

    return resolve(resource, set())


def read_icon(archive):
    from PySide6.QtGui import QImageReader
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    def read(name, limit):
        info = archive.getinfo(name)
        if info.file_size > limit:
            raise ValueError('Android icon resource is too large')
        return archive.read(info)

    icon = manifest_icon(read('AndroidManifest.xml', 4 * 1024**2))
    if not icon:
        raise ValueError('APK application does not declare an icon')
    paths = resource_values(read('resources.arsc', 32 * 1024**2), icon) if isinstance(icon, int) else [icon]
    candidates = []
    for path in set(paths):
        if not path.startswith('res/') or not path.lower().endswith(('.png', '.webp', '.jpg', '.jpeg')):
            continue
        raw = read(path, 16 * 1024**2)
        buffer = QBuffer()
        buffer.setData(QByteArray(raw))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buffer)
        size = reader.size()
        if size.width() <= 0 or size.height() <= 0 or max(size.width(), size.height()) > 4096:
            continue
        image = reader.read()
        if not image.isNull():
            candidates.append((image.width() * image.height(), path, image))
    if not candidates:
        raise ValueError('APK icon has no supported raster variant (adaptive/vector XML is not a bitmap)')
    _, path, image = max(candidates, key=lambda row: (row[0], row[1]))
    return path, image

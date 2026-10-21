"""PNG encoding for packed four-byte game pixels; no platform APIs."""
import struct
import zlib


def png_bytes(width, height, pixels, *, rgba=False, bottom_up=False):
    """Encode Windows BGRA or launcher RGBA pixels as an opaque RGB PNG."""
    if width <= 0 or height <= 0 or len(pixels) != width * height * 4:
        raise ValueError('截图像素尺寸无效')
    rgb = bytearray(width * height * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = pixels[0 if rgba else 2::4], pixels[1::4], pixels[2 if rgba else 0::4]
    offsets = range(0, len(rgb), width * 3)
    rows = b''.join(b'\0' + rgb[n:n + width * 3] for n in (reversed(offsets) if bottom_up else offsets))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))

    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


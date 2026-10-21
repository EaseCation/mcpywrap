"""Bounded artifact transfer and validated PNG archive publication on the caller."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from .mcstudio.recordings import CHUNK, MAX_VIDEO, RecordingError


def output_path(value, directory=False):
    path = Path(value).expanduser().resolve()
    if path.exists() or (not directory and path.suffix.lower() != '.mp4'):
        raise RecordingError('Output must be a nonexistent ' + ('directory' if directory else '.mp4 file'), 'invalid_output')
    return path


@contextmanager
def staged_file(target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + target.name + '-', suffix='.part', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            yield stream, Path(name)
    finally:
        Path(name).unlink(missing_ok=True)


def transfer(source, target, size, sha256, publish=True):
    if type(size) is not int or not 0 < size <= MAX_VIDEO or not isinstance(sha256, str) or not re.fullmatch('[0-9a-f]{64}', sha256):
        raise RecordingError('Invalid artifact length/hash', 'invalid_response')
    with staged_file(target) as (output, temporary):
        copied = 0
        digest = hashlib.sha256()
        while True:
            block = source.read(CHUNK)
            if not block:
                break
            copied += len(block)
            if copied > size:
                raise RecordingError('Artifact exceeds declared length', 'invalid_response')
            output.write(block)
            digest.update(block)
        if copied != size or digest.hexdigest() != sha256:
            raise RecordingError('Artifact length/hash mismatch', 'invalid_response')
        output.flush()
        os.fsync(output.fileno())
        output.close()
        if publish:
            # Windows rename refuses replacement; POSIX needs link for exclusive publication.
            if os.name == 'nt':
                temporary.rename(target)
            else:
                os.link(temporary, target)
        else:
            unpack(temporary, target)


def unpack(archive, target):
    target = Path(target)
    with zipfile.ZipFile(archive) as bundle:
        infos = bundle.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)) or len(names) > 101 or 'manifest.json' not in names:
            raise RecordingError('Invalid frame archive entries', 'invalid_response')
        if bundle.getinfo('manifest.json').file_size > 256 * 1024 or sum(i.file_size for i in infos) > MAX_VIDEO:
            raise RecordingError('Frame archive exceeds extraction limits', 'invalid_response')
        manifest = json.loads(bundle.read('manifest.json').decode('utf-8'))
        if not isinstance(manifest, dict):
            raise RecordingError('Invalid frame manifest', 'invalid_response')
        entries = manifest.get('frames')
        if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
            raise RecordingError('Invalid frame manifest', 'invalid_response')
        expected = {'manifest.json'}
        for entry in entries:
            if not isinstance(entry, dict):
                raise RecordingError('Invalid frame entry', 'invalid_response')
            name = entry.get('image')
            if type(entry.get('frame')) is not int or name != 'frame-' + str(entry['frame']) + '.png' or entry['frame'] < 0:
                raise RecordingError('Invalid frame filename', 'invalid_response')
            if name in expected:
                raise RecordingError('Duplicate frame', 'invalid_response')
            expected.add(name)
        if set(names) != expected or any(i.is_dir() or (i.external_attr >> 16) & 0o170000 == 0o120000 for i in infos):
            raise RecordingError('Unexpected frame archive entry', 'invalid_response')
        with tempfile.TemporaryDirectory(prefix='.' + target.name + '-', dir=target.parent) as temporary:
            stage = Path(temporary)
            for entry in entries:
                info = bundle.getinfo(entry['image'])
                if info.file_size != entry.get('size'):
                    raise RecordingError('Frame size mismatch', 'invalid_response')
                with bundle.open(info) as source, (stage / entry['image']).open('xb') as output:
                    digest = hashlib.sha256()
                    signature = source.read(8)
                    if signature != b'\x89PNG\r\n\x1a\n':
                        raise RecordingError('Invalid PNG frame', 'invalid_response')
                    output.write(signature)
                    digest.update(signature)
                    for block in iter(lambda: source.read(CHUNK), b''):
                        output.write(block)
                        digest.update(block)
                    if digest.hexdigest() != entry.get('sha256'):
                        raise RecordingError('Frame hash mismatch', 'invalid_response')
            (stage / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding='utf-8')
            target.mkdir()  # Reserve the directory exclusively after all validation succeeds.
            try:
                for path in stage.iterdir():
                    path.rename(target / path.name)
            except BaseException:
                shutil.rmtree(target)
                raise


def frame_result(output):
    manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
    return {**manifest, 'manifest': str(output / 'manifest.json'),
            'images': [str(output / entry['image']) for entry in manifest['frames']]}

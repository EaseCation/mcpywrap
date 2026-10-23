"""Verify assembly sees one stable source snapshot, after legitimate preparation hooks."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path


def fingerprint(manager):
    digest=hashlib.sha256()
    packs=[manager.root_node.addon_pack,*manager.get_all_dependencies().values()]
    for pack in packs:
        root=Path(pack.path)
        for name in ('pyproject.toml','mcpy-git.lock.json','mcpy-code-libraries.lock.json'):
            file=root/name;digest.update(str(file).encode())
            if file.is_file():digest.update(file.read_bytes())
        directories=[getattr(pack,key,None) for key in ('behavior_pack_dir','resource_pack_dir')]
        directories.extend(lib['source'] for lib in getattr(pack,'code_libraries',[]))
        for directory in directories:
            if not directory:continue
            visited=set()
            for current,dirs,files in os.walk(directory,followlinks=True):
                canonical=os.path.realpath(current)
                if canonical in visited:dirs[:]=[];continue
                visited.add(canonical);dirs.sort();digest.update(str(current).encode())
                for name in sorted(files):
                    file=Path(current)/name;digest.update(name.encode())
                    with file.open('rb') as stream:
                        for chunk in iter(lambda: stream.read(65536), b''):digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def stable_inputs(manager):
    before=fingerprint(manager)
    yield
    if before!=fingerprint(manager):
        raise ValueError('组装期间源码发生变化，请重新构建；没有确认可运行的产物。')

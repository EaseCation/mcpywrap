"""Verify both real distributions, shared version and exclusive file ownership."""
import argparse
from email.parser import BytesParser
from pathlib import Path
import tarfile
import zipfile

from version import ROOT, release_version


def check_native_payload(archive, folder):
    # 编译器的 .obj/.lib 等中间产物不属于发行资源；同时必须拒绝缺件。
    required = {
        'bridge_payload': {'manifest.json', 'Injector.exe', 'Loader.dll', 'McpyMcsAuth.dll', 'publisher.cer'},
        'window_capture': {'manifest.json', 'mcpy-window-capture.exe'},
        'window_activation': {'manifest.json', 'mcpy-window-activation.dll'},
    }[folder]
    prefix = 'mcpywrap_assets/' + folder + '/'
    packaged = {name[len(prefix):] for name in archive.namelist() if name.startswith(prefix)}
    assert packaged == required, 'Unexpected/missing native payload: ' + folder
    source = ROOT/'desktop/mcpywrap_assets'/folder
    for name in required:
        assert archive.read(prefix + name) == (source/name).read_bytes(), 'Stale native payload: ' + name


def check(outdir, require_native=False):
    version = release_version()
    code = {p.relative_to(ROOT/'core').as_posix(): p.read_bytes()
            for directory in ('mcpywrap_core', 'mcpywrap_host')
            for p in (ROOT/'core'/directory).rglob('*.py') if '__pycache__' not in p.parts}
    skill = {p.relative_to(ROOT/'skills/mcpywrap').as_posix():p.read_bytes()
             for p in (ROOT/'skills/mcpywrap').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    namespaces = {}
    for group, name in (('core', 'mcpywrap_core'), ('desktop', 'mcpywrap')):
        prefix = name+'-'+version
        wheel = Path(outdir)/group/(prefix+'-py3-none-any.whl')
        with zipfile.ZipFile(wheel) as archive:
            files = set(archive.namelist())
            package = BytesParser().parsebytes(archive.read(prefix+'.dist-info/METADATA'))
            assert package['Version'] == version
            assert package['Name'].replace('-', '_') == name
            requirements = package.get_all('Requires-Dist', [])
            owned = {p for p in files if '.dist-info/' not in p}
            namespaces[group] = owned
            if group == 'core':
                assert all(n.startswith(('mcpywrap_core/', 'mcpywrap_host/')) for n in owned)
                for path, content in code.items():
                    assert archive.read(path) == content, 'Stale/missing source: '+path
                assert not any(n.endswith(('.exe','.dll','.so','.pyd','.dylib','.pth')) for n in files)
                bundled = {n.removeprefix('mcpywrap_core/skill/'):archive.read(n) for n in owned if n.startswith('mcpywrap_core/skill/')}
                assert bundled == skill, 'Missing, stale or unexpected bundled skill files'
                assert not any(n.endswith('/entry_points.txt') for n in files), 'Core must not own desktop console scripts'
                assert all('extra ==' in r or r.split('>')[0] in ('click', 'packaging', 'tomli', 'tomli-w') for r in requirements)
            else:
                assert all(n.startswith('mcpywrap_assets/') for n in owned)
                assert 'mcpywrap-core=='+version in requirements
                assert any(r.startswith('PySide6-Essentials') for r in requirements)
                entries = archive.read(prefix+'.dist-info/entry_points.txt').decode()
                assert 'mcpy = mcpywrap_core.__main__:main' in entries
                assert not any(n.startswith('mcpywrap/') for n in files), 'Legacy import package must not be shipped'
                if require_native:
                    for folder in ('bridge_payload','window_capture','window_activation'):
                        check_native_payload(archive, folder)
            for path in files:
                assert not any(p in ('.local-notes','__pycache__','.runtime','.git') for p in Path(path).parts), path
                assert not path.endswith(('.pyc','.pfx','.p12','.key','.log')), path
        with tarfile.open(Path(outdir)/group/(prefix+'.tar.gz')) as archive:
            paths = {p.name.split('/',1)[1] for p in archive.getmembers() if '/' in p.name}
            assert 'pyproject.toml' in paths
            if group == 'core':
                assert set(code) <= paths
                for path,content in skill.items():
                    source=archive.extractfile(prefix+'/mcpywrap_core/skill/'+path)
                    assert source is not None and source.read()==content, 'Stale/missing sdist skill: '+path
            else:
                assert 'core/mcpywrap_core/_version.py' in paths
                assert not any(p.startswith('desktop/mcpywrap/') for p in paths)
                assert not any(p.startswith('core/mcpywrap_core/commands/') for p in paths)
    assert not namespaces['core'] & namespaces['desktop'], 'The two wheels overlap file ownership'
    print(version+': two distributions, one exact version, no overlapping modules/scripts')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist', default=str(ROOT/'dist'))
    parser.add_argument('--require-native', action='store_true')
    args = parser.parse_args()
    check(args.dist, args.require_native)

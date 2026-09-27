"""检查实际发布产物的版本、代码完整性及本机文件排除规则。"""
from email.parser import BytesParser
from pathlib import Path
import tarfile
import tomllib
import zipfile


root = Path(__file__).resolve().parent.parent
config = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']
version = config['version']
wheel = root / 'dist' / f'mcpywrap-{version}-py3-none-any.whl'
sdist = root / 'dist' / f'mcpywrap-{version}.tar.gz'
expected = {p.relative_to(root).as_posix() for p in (root / 'mcpywrap').rglob('*.py')}

with zipfile.ZipFile(wheel) as archive:
    wheel_names = set(archive.namelist())
    assert expected <= wheel_names, f'Wheel missing modules: {expected - wheel_names}'
    assert all(name.startswith(('mcpywrap/', f'mcpywrap-{version}.dist-info/')) for name in wheel_names)
    metadata = BytesParser().parsebytes(archive.read(f'mcpywrap-{version}.dist-info/METADATA'))
    assert metadata['Version'] == version
    assert metadata['Requires-Python'] == config['requires-python']
    assert any(requirement.startswith('pip>=') for requirement in metadata.get_all('Requires-Dist'))
    entries = archive.read(f'mcpywrap-{version}.dist-info/entry_points.txt').decode()
    assert 'mcpy = mcpywrap.__main__:main' in entries

with tarfile.open(sdist) as archive:
    sdist_names = {'/'.join(Path(name).parts[1:]) for name in archive.getnames()}
    assert expected <= sdist_names, f'Sdist missing modules: {expected - sdist_names}'
    assert 'tests/test_local_dependencies.py' in sdist_names
    skill_files = {p.relative_to(root).as_posix() for p in (root / 'skills').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    assert skill_files <= sdist_names, f'Sdist missing skill files: {skill_files - sdist_names}'

for name in wheel_names | sdist_names:
    parts = Path(name).parts
    assert not any(part in ('test', '.runtime', '__pycache__', '.git') for part in parts), name
    assert not name.endswith(('.cppconfig', '.log', '.pyc', '.pyo', '.png')), name
print(f'{version}: wheel and sdist contain all {len(expected)} Python modules; no local test artifacts')

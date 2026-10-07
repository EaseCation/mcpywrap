"""检查实际发布产物的版本、代码完整性及本机文件排除规则。"""
from email.parser import BytesParser
import json
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
    for name in expected:
        assert archive.read(name) == (root / name).read_bytes(), f'Wheel has stale module: {name}'
    assert all(name.startswith(('mcpywrap/', f'mcpywrap-{version}.dist-info/')) for name in wheel_names)
    metadata = BytesParser().parsebytes(archive.read(f'mcpywrap-{version}.dist-info/METADATA'))
    assert metadata['Version'] == version
    assert metadata['Requires-Python'] == config['requires-python']
    assert any(requirement.startswith('pip>=') for requirement in metadata.get_all('Requires-Dist'))
    entries = archive.read(f'mcpywrap-{version}.dist-info/entry_points.txt').decode()
    assert 'mcpy = mcpywrap.__main__:main' in entries
    bridge_manifest = json.loads((root/'mcpywrap/mcstudio/bridge_payload/manifest.json').read_text(encoding='utf-8'))
    bridge_files = {f'mcpywrap/mcstudio/bridge_payload/{name}' for name in bridge_manifest['files']}
    bridge_files.add('mcpywrap/mcstudio/bridge_payload/manifest.json')
    assert bridge_files <= wheel_names, 'Wheel missing signed bridge payload'
    capture_files = {f'mcpywrap/mcstudio/window_capture/{name}' for name in ('mcpy-window-capture.exe', 'manifest.json')}
    assert capture_files <= wheel_names, 'Wheel missing window capture helper'

with tarfile.open(sdist) as archive:
    sdist_names = {'/'.join(Path(name).parts[1:]) for name in archive.getnames()}
    assert expected <= sdist_names, f'Sdist missing modules: {expected - sdist_names}'
    assert 'tests/test_local_dependencies.py' in sdist_names
    assert {'docs/code-libraries.md', 'docs/git-dependencies.md', 'docs/qumod.md', 'docs/runtime-debug.md'} <= sdist_names
    runtime_files = {'docs/runtime-ui.md', 'docs/runtime-player.md', 'docs/input-sequence.md', 'docs/runtime-input.md',
                     'tests/test_runtime_input.py', 'tests/test_host_input.py', 'tests/test_runtime_key_timeline.py',
                     'tests/manual_runtime_input_unified.py', 'tests/manual_runtime_key_timeline.py',
                     'native/runtime_input/README.md', 'native/runtime_input/steady_clock.h',
                     'native/runtime_input/launcher-monotonic.patch',
                     'tests/test_runtime_ui.py', 'tests/test_runtime_ui_outline.py',
                     'tests/test_runtime_player.py', 'tests/manual_runtime_ui.py', 'tests/manual_runtime_player.py',
                     'tests/test_input_sequence.py', 'tests/test_native_input_sequence.py',
                     'tests/manual_input_window.py', 'tests/manual_runtime_input.py',
                     'docs/game-backends.md', 'docs/launcher-client-python.md', 'docs/macos-resource-reload.md',
                     'docs/qt6-development.md', 'docs/shared-log-ui.md', 'docs/release-0.4.0.md',
                     'tests/test_session_capabilities.py', 'tests/test_engine_install.py', 'tests/test_shared_logs.py'}
    manual_files = {p.relative_to(root).as_posix() for p in (root / 'tests/manual/runtime_controls').rglob('*')
                    if p.is_file() and '__pycache__' not in p.parts}
    runtime_files.update(manual_files)
    assert runtime_files <= sdist_names, f'Sdist missing runtime documentation/tests: {runtime_files - sdist_names}'
    for name in manual_files:
        assert archive.extractfile(f'mcpywrap-{version}/{name}').read() == (root/name).read_bytes(), \
            f'Sdist has stale optional manual test: {name}'
    skill_files = {p.relative_to(root).as_posix() for p in (root / 'skills').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    assert skill_files <= sdist_names, f'Sdist missing skill files: {skill_files - sdist_names}'
    for name in skill_files:
        assert archive.extractfile(f'mcpywrap-{version}/{name}').read() == (root/name).read_bytes(), \
            f'Sdist has stale skill: {name}'
    assert bridge_files <= sdist_names, 'Sdist missing signed bridge payload'
    assert 'native/mcs_auth/Bridge.cs' in sdist_names
    assert capture_files <= sdist_names, 'Sdist missing window capture helper'
    assert 'native/window_capture/window_capture.cpp' in sdist_names
    assert 'native/window_capture/video_capture.h' in sdist_names

for name in wheel_names | sdist_names:
    parts = Path(name).parts
    assert not any(part in ('test', '.runtime', '__pycache__', '.git') for part in parts), name
    assert not name.endswith(('.cppconfig', '.log', '.pyc', '.pyo', '.png', '.pfx', '.p12', '.key')), name
print(f'{version}: wheel and sdist contain all {len(expected)} Python modules; no local test artifacts')

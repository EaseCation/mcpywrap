"""Android harness payload; diagnostic controller is NOT a production updater.

由临时 Chaquopy 探针 Activity 在导入共享核心前调用。
The JSON request simulates a release descriptor authenticated by the host.
Production apps must never trust a descriptor merely because it is on /sdcard.
"""
import hashlib
import json
from pathlib import Path
import time
import zipfile


def start(private_dir, python_ms):
    from mcpywrap_host import CoreStore
    base = Path('/sdcard/mcpy/core-upgrade-probe')
    request = json.loads((base/'request.json').read_text())
    action = request['action']
    store = CoreStore(Path(private_dir)/'core-releases')
    def configure(Core):
        # Import host types only after the new core has been selected.
        from mcpywrap_core.host import HostServices
        return Core(HostServices(python_executable=None, allow_processes=False,
                                lock_directory=Path(private_dir)/'locks'))
    if action == 'upgrade':
        store.stage(request['wheel'], expected_sha256=request['sha256'], expected_version=request['version'])
        core = store.activate(request['sha256'], configure=configure)
    else:
        if action == 'rollback':
            store.rollback()
        core = store.load_selected(configure=configure)
        if core is None:
            from mcpywrap_core.api import Core
            core = configure(Core)
    from core_fixture import projects
    import mcpywrap_core
    fixture = base/('fixture-'+str(time.time_ns()))
    project = projects(fixture)
    result = {'action': action, 'core': core.describe(), 'loadedFrom': mcpywrap_core.__file__,
              'pythonStartMs': python_ms, 'selection': store.selection()}
    result['resolve'] = core.execute('resolve', project)
    output = Path(core.execute('build', project)['output'])
    result['files'] = {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in output.rglob('*') if p.is_file()}
    package = core.execute('package', project)['artifact']
    with zipfile.ZipFile(package) as archive:
        result['archive'] = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}
    result['sync'] = core.execute('sync', project)
    (base/(action+'-result.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return json.dumps(result, ensure_ascii=False)

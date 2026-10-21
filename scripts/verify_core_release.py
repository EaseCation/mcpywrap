"""Exercise real release wheels through fresh workers and normal project APIs.

The +upgradeprobe wheel is a local test fixture, never a published release.
Only its package version changes; project rules remain the exact same source.
"""
import argparse
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile


def upgrade_fixture(wheel, output):
    with zipfile.ZipFile(wheel) as archive:
        files = {name: archive.read(name) for name in archive.namelist() if not name.endswith('/')}
    metadata_path = next(name for name in files if name.endswith('.dist-info/METADATA'))
    old_info = metadata_path.split('/')[0]
    old_version = BytesParser().parsebytes(files[metadata_path])['Version']
    version = old_version.split('+')[0] + '+upgradeprobe'
    new_info = 'mcpywrap_core-' + version + '.dist-info'
    files = {name.replace(old_info+'/', new_info+'/'): value for name, value in files.items() if not name.endswith('.dist-info/RECORD')}
    # Windows 构建的 METADATA 使用 CRLF，不能只替换 LF 行尾。
    files[new_info+'/METADATA'], count = re.subn(
        rb'(?m)^Version: [^\r\n]+\r?$', ('Version: '+version).encode(), files[new_info+'/METADATA'], count=1)
    assert count == 1, 'Expected one wheel Version header'
    source = files['mcpywrap_core/_version.py'].decode()
    source, count = re.subn(r"__version__\s*=\s*['\"][^'\"]+['\"]", '__version__ = '+repr(version), source)
    assert count == 1
    files['mcpywrap_core/_version.py'] = source.encode()
    record = io.StringIO(newline='')
    writer = csv.writer(record)
    for name, content in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip('=')
        writer.writerow([name, 'sha256='+digest, len(content)])
    writer.writerow([new_info+'/RECORD', '', ''])
    files[new_info+'/RECORD'] = record.getvalue().encode()
    path = Path(output)/('mcpywrap_core-'+version+'-py3-none-any.whl')
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    return path, version


WORKER = '''
import hashlib,json,sys,tempfile,zipfile
from pathlib import Path
from mcpywrap_host import CoreStore
sys.path.insert(0, sys.argv[3])
from core_fixture import projects
result={}
def healthy(core):
    with tempfile.TemporaryDirectory() as temp:
        project=projects(Path(temp))
        result['dependencies']=len(core.execute('resolve',project)['dependencies'])
        output=Path(core.execute('build',project)['output'])
        result['files']={str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in output.rglob('*') if p.is_file()}
        package=core.execute('package',project)['artifact']
        with zipfile.ZipFile(package) as archive:
            result['archive']={n:hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist()}
store=CoreStore(sys.argv[1])
def configure(Core):
    from mcpywrap_core.host import HostServices
    return Core(HostServices(python_executable=None,allow_processes=False,lock_directory=Path(sys.argv[1])/'work-locks'))
core=store.activate(sys.argv[2],health_check=healthy,configure=configure) if sys.argv[2] else store.load_selected(health_check=healthy,configure=configure)
import mcpywrap_core
assert core.describe()['capabilities']['process_execution'] is False
result.update(version=core.describe()['version'],loadedFrom=mcpywrap_core.__file__,configuredHost=True)
print(json.dumps(result))
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('wheel')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    from mcpywrap_host import CoreStore
    wheel = Path(args.wheel).resolve()
    with tempfile.TemporaryDirectory(prefix='mcpy-release-') as temp:
        root = Path(temp)
        fixture, new_version = upgrade_fixture(wheel, root)
        store = CoreStore(root/'store')
        report = []
        for artifact, version in ((wheel, None), (fixture, new_version)):
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            if version is None:
                with zipfile.ZipFile(artifact) as archive:
                    name = next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))
                    version = BytesParser().parsebytes(archive.read(name))['Version']
            store.stage(artifact, expected_sha256=digest, expected_version=version)
            command = [sys.executable, '-c', WORKER, str(store.root), digest, str(Path(__file__).resolve().parents[1]/'tests')]
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            report.append(json.loads(result.stdout))
        store.rollback()
        command[4] = ''
        report.append(json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout))
        assert report[0]['version'] == report[2]['version'] != report[1]['version']
        assert all(item['files'] == report[0]['files'] and item['archive'] == report[0]['archive'] for item in report)
        Path(args.output).write_text(json.dumps({'ok': True, 'runs': report}, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Real wheel activation → update → rollback: same project outputs in all three fresh workers')


if __name__ == '__main__':
    main()

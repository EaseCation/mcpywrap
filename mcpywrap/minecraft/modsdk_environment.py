"""Explicit development-environment ModSDK installs, without importing the SDK.

The upstream pure-Python wheel is completion data tagged py2. Rebuild its wheel
metadata for Python 3; let pip own installation/RECORD/uninstall, never copy files
into a guessed site-packages directory. The selected interpreter need not have pip.
"""
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from email.parser import BytesParser
from ..utils.locks import directory_lock

PACKAGE = 'mc-netease-sdk'
MAX_WHEEL = 32 * 1024 * 1024

# -I prevents project/PYTHONPATH imports; metadata discovery never imports the SDK.
PROBE = r'''
import hashlib, importlib.metadata as m, json, os, sys, sysconfig
p = lambda x: os.path.normcase(os.path.abspath(x))
if sys.version_info < (3, 8):
    raise RuntimeError('Development environment requires Python 3.8+')
identity = [p(sys.executable), p(sys.prefix), p(sys.base_prefix), sys.version]
for path in (sys.argv[1], sys.prefix, os.path.join(sys.prefix, 'pyvenv.cfg')):
    try:
        s = os.stat(path)
        identity.append([s.st_dev, s.st_ino, s.st_mtime_ns] if os.path.isfile(path) else [s.st_dev, s.st_ino])
    except OSError:
        identity.append(None)
env = dict(invocation=sys.argv[1], executable=sys.executable, prefix=sys.prefix,
           base_prefix=sys.base_prefix, version=sys.version.split()[0],
           purelib=sysconfig.get_path('purelib'), platlib=sysconfig.get_path('platlib'),
           identity=hashlib.sha256(json.dumps(identity).encode()).hexdigest())
try:
    d = m.distribution('mc-netease-sdk')
    location = os.path.abspath(str(d.locate_file('')))
    inside = any(p(location) == p(env[k]) for k in ('purelib', 'platlib'))
    sdk = dict(version=d.version, location=location, in_environment=inside)
except m.PackageNotFoundError:
    sdk = None
print(json.dumps(dict(environment=env, installed=sdk), ensure_ascii=True))
'''


def _clean_env():
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(('PYTHON', 'PIP_'))}
    env['PIP_CONFIG_FILE'] = os.devnull
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def inspect_environment(python):
    """Preserve venv invocation symlinks; never fall back to PATH or tool Python."""
    if not os.path.isabs(python) or not Path(python).is_file():
        raise ValueError('请提供所选 Python 可执行文件的有效绝对路径')
    try:
        result = subprocess.run([python, '-I', '-c', PROBE, python], env=_clean_env(),
                                capture_output=True, timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise ValueError('检查所选 Python 环境超时；未安装任何内容') from exc
    if result.returncode:
        raise ValueError('无法检查所选 Python 环境: ' + result.stderr.decode('utf-8', 'replace')[-4000:])
    try:
        data = json.loads(result.stdout)
        assert data['environment']['invocation'] == python
        assert data['environment']['identity']
        return data
    except (ValueError, KeyError, AssertionError, TypeError) as exc:
        raise ValueError('所选 Python 返回了无效的环境信息') from exc


def _check_identity(data, expected):
    if expected and data['environment']['identity'] != expected:
        raise ValueError('Python 环境身份已改变；请重新检查并确认安装目标')


def _json_url(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def prepare_completion_wheel(version, directory):
    """Verify PyPI hash and accept only inert, pure-Python completion wheels."""
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*(?:[a-zA-Z0-9.+-]*)', version):
        raise ValueError('无效的 ModSDK 版本')
    data = _json_url('https://pypi.org/pypi/{}/{}/json'.format(PACKAGE, version))
    item = next((f for f in data.get('urls', []) if f.get('packagetype') == 'bdist_wheel'
                 and not f.get('yanked') and f['filename'].endswith('-none-any.whl')), None)
    if item is None:
        raise ValueError('此版本没有可用的纯 Python ModSDK wheel')
    url = item['url']
    if not url.startswith('https://files.pythonhosted.org/'):
        raise ValueError('拒绝非 PyPI 文件下载地址')
    with urllib.request.urlopen(url, timeout=60) as response:
        content = response.read(MAX_WHEEL + 1)
    if len(content) > MAX_WHEEL or hashlib.sha256(content).hexdigest() != item['digests']['sha256']:
        raise ValueError('ModSDK wheel 大小或 SHA-256 校验失败')
    return adapt_completion_wheel(content, version, directory)


def adapt_completion_wheel(content, version, directory):
    files = {}
    total = 0
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for member in archive.infolist():
            # ZipInfo normalizes OS separators on Windows; inspect the raw name.
            name = member.orig_filename
            path = PurePosixPath(name)
            if (path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name
                    or (str(path) + ('/' if member.is_dir() else '')) != name or not path.parts or name in files
                    or any(part.endswith('.data') for part in path.parts)
                    or path.name in ('sitecustomize.py', 'usercustomize.py') or member.external_attr >> 28 == 0xA):
                raise ValueError('ModSDK wheel 包含不安全路径')
            if member.is_dir():
                continue
            total += member.file_size
            if total > MAX_WHEEL or not name.endswith(('.py', '.pyi', '/METADATA', '/WHEEL', '/RECORD',
                                                      '/top_level.txt', '/LICENSE', '/LICENSE.txt')):
                raise ValueError('ModSDK wheel 包含非补全内容或超过大小限制')
            files[name] = archive.read(member)
    metadata = [n for n in files if n.endswith('.dist-info/METADATA')]
    if len(metadata) != 1:
        raise ValueError('ModSDK wheel 缺少唯一元数据')
    info = BytesParser().parsebytes(files[metadata[0]])
    if info['Name'] != PACKAGE or info['Version'] != version:
        raise ValueError('ModSDK wheel 名称或版本不匹配')
    dist = metadata[0].rsplit('/', 1)[0]
    if not all(name.startswith(dist + '/') or '.dist-info/' not in name for name in files):
        raise ValueError('ModSDK wheel 包含额外发行包')
    wheel = files.get(dist + '/WHEEL', b'').decode('utf-8')
    if 'Root-Is-Purelib: true' not in wheel:
        raise ValueError('ModSDK wheel 不是纯 Python 补全包')
    wheel = re.sub(r'^Tag:.*\n?', '', wheel, flags=re.MULTILINE).rstrip() + '\nTag: py3-none-any\n'
    files[dist + '/WHEEL'] = wheel.encode('utf-8')
    record_name = dist + '/RECORD'
    files.pop(record_name, None)
    record = io.StringIO(newline='')
    writer = csv.writer(record, lineterminator='\n')
    for name, body in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b'=').decode('ascii')
        writer.writerow([name, 'sha256=' + digest, len(body)])
    writer.writerow([record_name, '', ''])
    files[record_name] = record.getvalue().encode('utf-8')
    destination = Path(directory) / ('mc_netease_sdk-{}-py3-none-any.whl'.format(version))
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return destination


def installation_lock(environment):
    # Canonicalize only the prefix for locking, never the invocation executable.
    prefix = os.path.normcase(os.path.realpath(environment['prefix']))
    key = hashlib.sha256(prefix.encode('utf-8')).hexdigest()
    return directory_lock(Path.home() / '.cache' / 'mcpywrap' / 'modsdk-locks' / key)


def install_environment(version, python, expected=None):
    before = inspect_environment(python)
    _check_identity(before, expected)
    with installation_lock(before['environment']):
        return _install_locked(version, python, before)


def _install_locked(version, python, before):
    identity = before['environment']['identity']
    with tempfile.TemporaryDirectory(prefix='mcpy-modsdk-') as directory:
        wheel = prepare_completion_wheel(version, directory)
        # Downloads can take time; do not mutate an environment changed in between.
        _check_identity(inspect_environment(python), identity)
        cmd = [sys.executable, '-I', '-m', 'pip', '--python', python,
               '--disable-pip-version-check', '--no-input', 'install', '--no-user',
               '--no-compile', '--no-deps', '--no-index', '--no-cache-dir',
               '--force-reinstall', '--ignore-requires-python', str(wheel)]
        try:
            result = subprocess.run(cmd, env=_clean_env(), capture_output=True, timeout=180)
        except subprocess.TimeoutExpired as exc:
            raise ValueError('安装等待超时；结果未知，请检查原 Python 环境，不要自动重试') from exc
        if result.returncode:
            message = result.stderr.decode('utf-8', 'replace')[-6000:]
            raise ValueError('ModSDK 定向安装失败；未回退其他环境。请检查原环境状态。\n' + message)
    after = inspect_environment(python)
    _check_identity(after, identity)
    sdk = after['installed']
    if not sdk or sdk['version'] != version or not sdk['in_environment']:
        raise ValueError('安装命令已返回，但目标环境内的 ModSDK 版本/位置未通过核验')
    return after

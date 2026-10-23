"""Caller-side tool stages, never an alternative project builder or resident server."""
import base64
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


class LocalPreparation:
    def __init__(self, profile, core_version, cancel=None):
        self.profile, self.core_version = profile, core_version
        self.cancel = cancel
        self.root = Path(profile['workspace']).resolve()
        self.private = Path.home()/'.local/share/mcpywrap/hosts'/profile['installation_id']

    def local(self, value):
        if not isinstance(value, str): return value
        if value == 'host:python': return sys.executable
        for prefix in ('/sdcard/mcpy', '/storage/emulated/0/mcpy'):
            if value == prefix or value.startswith(prefix+'/'):
                path = (self.root/value[len(prefix):].lstrip('/')).resolve()
                if path != self.root and self.root not in path.parents: raise ValueError('宿主准备路径越界')
                return str(path)
        return value

    def host(self, value):
        if not isinstance(value, str): return value
        try: return '/sdcard/mcpy/'+Path(value).resolve().relative_to(self.root).as_posix()
        except (ValueError, OSError): return value

    def execute(self, step):
        from .. import __version__
        if step.get('core_version') != __version__ or self.core_version != __version__:
            return {'ok': False, 'code': 'preparation_version_mismatch', 'error': '准备辅助代码须与 App 核心版本一致；请更新 mcpywrap 后重新执行'}
        try:
            kind, options = step['kind'], step['options']
            if kind == 'distribution': result = self.distribution(options['name'])
            elif kind == 'environment': result = self.environment(options)
            elif kind == 'script': result = self.script(options)
            elif kind == 'git_source': result = self.git_source(options)
            elif kind == 'pip': result = self.pip(options)
            elif kind == 'script_recovery': result = self.script_recovery(options)
            elif kind == 'markers':
                from packaging.markers import default_environment
                result = default_environment()
            else: raise ValueError('未知准备阶段：'+kind)
            return {'ok': True, 'result': result}
        except Exception as error:
            return {'ok': False, 'error': str(error), 'code': getattr(error, 'code', 'preparation_failed'),
                    'hint': getattr(error, 'hint', None),
                    'details': {k:self.host(v) for k,v in (getattr(error, 'details', None) or {}).items()}}

    def script_recovery(self, options):
        from ..project_scripts import _active_process
        project = Path(self.local(options['project']))
        active = json.loads((project/'.mcpy/scripts/active.json').read_text())
        state_path = project/active['state_relative'] if active.get('state_relative') else Path(self.local(active['state_path']))
        if project.resolve() not in state_path.resolve().parents:
            raise ValueError('无法识别上次脚本结果位置；未开始新操作')
        state = json.loads(state_path.read_text())
        return _active_process(state) or state.get('state') == 'spawning'

    def environment(self, options):
        from ..prepare_environment import compatible
        project = self.local(options['project'])
        identity = hashlib.sha256(project.encode()).hexdigest()[:20]
        directory = self.private/'environments'/identity
        executable = directory/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        override = options.get('override')
        if override:
            executable = Path(project, override)
        if options.get('ensure') and not executable.is_file() and not override:
            directory.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([sys.executable, '-m', 'venv', str(directory)], check=True, timeout=120, stdout=sys.stderr)
        version = None
        if executable.is_file():
            result = subprocess.run([str(executable), '-c', 'import platform;print(platform.python_version())'], capture_output=True, text=True, timeout=10)
            if result.returncode == 0: version = result.stdout.strip()
        return {'state': 'ready' if compatible(version, options['requirements']) else ('missing' if version is None else 'incompatible'),
                'python': str(executable), 'version': version, 'requirements': options['requirements'], 'override': override,
                'identity': hashlib.sha256((str(executable)+str(version)+(str(executable.stat().st_mtime_ns) if executable.exists() else '')).encode()).hexdigest()}

    def script(self, options):
        from ..project_scripts import _execute_process
        from ..host import HostServices, host_scope
        project = Path(self.local(options['project']))
        if self.root not in project.parents: raise ValueError('脚本作品路径不在授权工作区')
        spec = dict(options['spec'])
        spec['command'] = [self.local(x) for x in spec['command']]
        spec['env'] = {k:self.local(v) for k,v in spec['env'].items()}
        package_root = self.local(options.get('package_root'))
        with host_scope(HostServices()):
            result = _execute_process(project, options['name'], spec, options['event'], tuple(options.get('extra', [])), package_root=package_root, cancel=self.cancel)
        return {k:self.host(v) for k,v in result.items()}

    def git_source(self, options):
        from ..git_cache import fetch_archive
        from ..host import HostServices, host_scope
        self.private.mkdir(parents=True,exist_ok=True)
        url=options['url']
        if url.startswith('file://'):
            from urllib.parse import urlsplit,unquote
            url=Path(self.local(unquote(urlsplit(url).path))).as_uri()
        with tempfile.TemporaryDirectory(prefix='git-',dir=self.private) as temporary, host_scope(HostServices()):
            commit,content=fetch_archive(url,options['ref'],Path(temporary)/'repo')
        result=self.command_result(subprocess.CompletedProcess([],0,content,b''))
        result['commit']=commit
        return result

    def pip(self, options):
        argv = options['argv']
        if len(argv)<5 or argv[:4] != ['host:python','-m','pip','install']: raise ValueError('无效依赖安装请求')
        executable=self.private/'packages'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        if not executable.is_file():
            executable.parent.parent.parent.mkdir(parents=True,exist_ok=True)
            subprocess.run([sys.executable,'-m','venv',str(executable.parent.parent)],check=True,timeout=120,stdout=sys.stderr)
        result = subprocess.run([str(executable), *[self.local(x) for x in argv[1:]]], capture_output=True, timeout=600)
        return self.command_result(result)

    def distribution(self, name):
        from packaging.requirements import Requirement
        from packaging.utils import canonicalize_name
        package_name=canonicalize_name(Requirement(name).name)
        sites=[self.private/'packages/Lib/site-packages'] if os.name=='nt' else list((self.private/'packages/lib').glob('python*/site-packages'))
        dist=next((d for d in metadata.distributions(path=[str(p) for p in sites]) if canonicalize_name(d.metadata['Name'])==package_name),None)
        if dist is None:
            try: dist = metadata.distribution(package_name)
            except metadata.PackageNotFoundError: return None
        direct = json.loads(dist.read_text('direct_url.json') or '{}')
        source = None
        if direct.get('url','').startswith('file:'):
            from urllib.parse import urlsplit,unquote
            source = Path(unquote(urlsplit(direct['url']).path)).resolve()
        if source is None or not source.is_dir():
            # Wheel data normally lives beside dist-info; only identify a real Addon root.
            roots = {Path(dist.locate_file(p)).parent for p in (dist.files or []) if str(p).endswith('pyproject.toml')}
            source = next((p for p in roots if p.is_dir()), None)
        record = {'name': dist.metadata['Name'], 'version': dist.version, 'root': None}
        if source is None: return record
        try:
            source.relative_to(self.root)
            record['root'] = self.host(str(source));return record
        except ValueError: pass
        from ..source_files import digest
        identity = digest(source)
        target = self.root/'cache/packages'/identity
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix='.package-',dir=target.parent))
            try:
                shutil.copytree(source, temporary/'content', symlinks=False,
                                ignore=shutil.ignore_patterns('.git','.venv','__pycache__','build','dist','.mcpy'))
                os.replace(temporary/'content',target)
            finally: shutil.rmtree(temporary,ignore_errors=True)
        record['root'] = self.host(str(target))
        return record

    def command_result(self,result):
        value={'returncode':result.returncode}
        for key,data in [('stdout',result.stdout),('stderr',result.stderr)]:
            if len(data)>65536:
                directory=self.root/'build/tool-results';directory.mkdir(parents=True,exist_ok=True)
                fd,name=tempfile.mkstemp(prefix='result-',dir=directory)
                with os.fdopen(fd,'wb') as stream:stream.write(data)
                value[key+'_path']=self.host(name)
            else:value[key+'_b64']=base64.b64encode(data).decode()
        return value

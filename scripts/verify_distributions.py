"""Real pip installs outside the checkout: core-only, legacy upgrade and uninstall.

Uses temporary environments and the default configured package index for third
party dependencies. Does not modify the developer's installed mcpy or publish.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv

from version import ROOT, release_version


def verify(dist, legacy=None):
    version = release_version()
    core = (Path(dist)/'core'/f'mcpywrap_core-{version}-py3-none-any.whl').resolve()
    full = (Path(dist)/'desktop'/f'mcpywrap-{version}-py3-none-any.whl').resolve()
    report = {'version': version, 'steps': []}
    with tempfile.TemporaryDirectory(prefix='mcpy-install-') as temporary:
        root = Path(temporary)
        environment = root/'environment'
        venv.EnvBuilder(with_pip=True).create(environment)
        executable = environment/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        command = environment/('Scripts/mcpy.exe' if os.name == 'nt' else 'bin/mcpy')
        alias = environment/('Scripts/mcpywrap.exe' if os.name == 'nt' else 'bin/mcpywrap')
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        env['PYTHONUTF8'] = '1'

        def run(*args):
            subprocess.run([str(executable), *map(str,args)], cwd=root, env=env, check=True)

        run('-m','pip','install',core)
        run('-c', "import importlib.util; from mcpywrap_core.api import Core; assert Core().describe()['version']=="+repr(version)+"; assert importlib.util.find_spec('mcpywrap') is None; assert importlib.util.find_spec('PySide6') is None")
        assert not command.exists() and not alias.exists()
        run('-c', "import sys,tempfile; from pathlib import Path; sys.path.insert(0,"+repr(str(ROOT/'tests'))+"); from core_fixture import projects; from mcpywrap_core.api import Core; t=tempfile.TemporaryDirectory(); p=projects(Path(t.name)); c=Core(); [c.execute(m,p) for m in ('resolve','build','package','sync')]")
        report['steps'].append('core-only: API runs without desktop modules or console scripts')
        if legacy:
            run('-m','pip','uninstall','-y','mcpywrap-core')
            run('-m','pip','install',Path(legacy).resolve())
            run('-c', "from importlib.metadata import version; assert version('mcpywrap')=='0.5.8'")
            report['steps'].append('installed real legacy 0.5.8')
        run('-m','pip','install','--upgrade','--find-links',core.parent,full)
        run('-m','pip','check')
        verification = (
            "import importlib.util; from importlib.metadata import version; from mcpywrap_core.api import Core; "
            "assert version('mcpywrap')==version('mcpywrap-core')=="+repr(version)+"; "
            "assert Core().describe()['version']=="+repr(version)+"; "
            "assert importlib.util.find_spec('mcpywrap') is None"
        )
        if sys.platform in ('win32', 'darwin'):
            verification += '; from PySide6 import QtCore'
        run('-c', verification)
        subprocess.run([str(command),'--help'],cwd=root,env=env,check=True)
        subprocess.run([str(alias),'--version'],cwd=root,env=env,check=True)
        run('-m','mcpywrap_core','--version')
        report['steps'].append('complete install: exact core dependency, canonical API, console commands, no legacy import package')
        run('-m','pip','uninstall','-y','mcpywrap')
        run('-c', "import importlib.util; from mcpywrap_core.api import Core; assert Core().describe()['version']=="+repr(version)+"; assert importlib.util.find_spec('mcpywrap') is None")
        assert not command.exists() and not alias.exists()
        report['steps'].append('uninstall complete package: core remains intact')
        run('-m','pip','install','--find-links',core.parent,full)
        run('-m','pip','check')
        subprocess.run([str(command),'--version'],cwd=root,env=env,check=True)
        subprocess.run([str(alias),'--version'],cwd=root,env=env,check=True)
        report['steps'].append('reinstall complete package: console restored')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist', default=str(ROOT/'dist'))
    parser.add_argument('--legacy-wheel')
    parser.add_argument('--output')
    args = parser.parse_args()
    result = verify(args.dist,args.legacy_wheel)
    if args.output:
        Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

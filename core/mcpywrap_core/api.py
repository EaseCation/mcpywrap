"""Versioned engineering API. All frontends call the same operation functions."""
from pathlib import Path
import click

from . import __version__
from .host import HOST_API, HostServices, host_scope, current_host

CORE_API = 1
from .operations.project import OPTIONS
OPERATIONS = ('resolve', 'build', 'package', 'sync', *OPTIONS)


class Core:
    def __init__(self, host=None):
        self.host = host or current_host()

    def describe(self):
        return {'core_api': CORE_API, 'host_api': HOST_API, 'version': __version__,
                'operations': list(OPERATIONS), 'capabilities': self.host.capabilities()}

    def execute(self, operation, project, **options):
        """Execute or raise the original structured error; never invoke another core."""
        if operation not in OPERATIONS:
            raise ValueError('未知工程操作：' + str(operation))
        allowed = OPTIONS[operation] if operation in OPTIONS else {'resolve': set(), 'build': {'merge'}, 'package': {'merge'},
                   'sync': {'install', 'migrate_windows_lock'}}[operation]
        if set(options) - allowed or (operation not in OPTIONS and any(type(value) is not bool for value in options.values())):
            raise ValueError('无效的工程操作参数')
        if operation in OPTIONS:
            for name,value in options.items():
                valid = (type(value) is bool if name=='effective' else
                         isinstance(value,(list,tuple)) and all(isinstance(item,str) for item in value) if name=='args' else
                         value is None or isinstance(value,str))
                if not valid: raise ValueError('无效的工程操作参数：'+name)
            if operation=='script.run' and not options.get('name'):
                raise ValueError('运行项目脚本需要 name')
        project = Path(project).expanduser().resolve()
        if not project.is_dir() or (operation != 'init' and not (project/'pyproject.toml').is_file()):
            raise ValueError('未找到项目 pyproject.toml：' + str(project))
        from .command_context import project_scope
        with host_scope(self.host), project_scope(project) as context:
            if operation in OPTIONS:
                from .operations.project import execute
                context.non_interactive = True
                result = execute(operation, project, options)
            elif operation == 'resolve':
                from .dependencies import DependencyService
                manager = DependencyService(project).resolve()
                result = {'project': str(project), 'dependencies': [
                    {'name': pack.pkg_name, 'path': str(pack.path)}
                    for pack in manager.get_all_dependencies().values()], 'warnings': manager.warnings}
            elif operation == 'build':
                from .operations.build import build_project
                result = build_project(project, **options)
            elif operation == 'package':
                from .operations.package import package_project
                result = package_project(project, **options)
            else:
                from .operations.sync import sync_project
                result = sync_project(project, **options)
            if context.warnings:
                result['warnings'] = list(dict.fromkeys([*result.get('warnings', []), *context.warnings]))
            return result

    def request(self, request):
        """Transport-neutral envelope. Authentication/path grants belong to the host.

        The host resolves an authorized project ID to a path before calling this
        method. Do not expose raw caller-supplied paths on an unauthenticated port.
        """
        try:
            if not isinstance(request, dict) or request.get('core_api') != CORE_API:
                raise ValueError('不兼容的核心协议')
            if request.get('operation') == 'describe':
                return {'ok': True, 'result': self.describe()}
            options = request.get('options', {})
            if not isinstance(options, dict) or not all(isinstance(key,str) for key in options) or not isinstance(request.get('project'), str):
                raise ValueError('无效的工程请求')
            result = self.execute(request.get('operation'), request['project'], **options)
            return {'ok': True, 'result': result, 'core': self.describe()}
        except (ValueError, OSError, click.ClickException) as error:
            return {'ok': False, 'error': error.format_message() if isinstance(error,click.ClickException) else str(error), 'code': getattr(error, 'code', 'operation_failed'),
                    'hint': getattr(error, 'hint', None), 'details': getattr(error, 'details', {})}

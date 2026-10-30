"""Frontend-neutral project operations built on the existing services."""
from pathlib import Path

OPTIONS = {
    'init': {'name','project_type','version','target_dir'},
    'mod': {'name','version','script_dir','server_system','client_system','framework','source'},
    'add': {'package','local_path','git_url','git_ref','dep_name','subdir','kind','target','framework','script_dir','source','unbundled'},
    'remove': {'package','local_path','library','git_name'},
    'script.list': {'effective'}, 'script.run': {'name','args'}, 'prepare_run': set(),
}


def execute(operation, project, options):
    if operation == 'init':
        from ..project_init import initialize_project
        return initialize_project(project, options.get('name'), options.get('project_type','addon'), options.get('version','0.1.0'), options.get('target_dir','./build'))
    if operation == 'mod':
        # The existing parameterized generator is the same one used by the desktop form.
        from ..commands.mod_cmd import mod_cmd
        args = dict(name=None,version='0.1.0',script_dir='myScript',server_system='ServerSystem',client_system='ClientSystem',gui=False,framework='native',qumod_source=None)
        args.update({('qumod_source' if k=='source' else k):v for k,v in options.items()})
        return mod_cmd.callback(**args)
    if operation in ('add','remove'):
        from ..dependencies import DependencyService, DependencyDeclaration
        service = DependencyService(project)
        if operation == 'remove':
            choices = [(key, kind) for key, kind in (('package','package'),('local_path','local'),('library','code'),('git_name','git')) if options.get(key)]
            if len(choices) != 1: raise ValueError('请明确指定一种要移除的依赖')
            key, kind = choices[0]
            declaration = DependencyDeclaration(kind, options[key])
            if kind == 'package' and declaration not in service.list():
                from packaging.requirements import Requirement
                from packaging.utils import canonicalize_name
                matches = [entry for entry in service.list() if entry.kind=='package' and canonicalize_name(Requirement(entry.value).name)==canonicalize_name(Requirement(options[key]).name)]
                if len(matches)==1: declaration=matches[0]
            service.remove(declaration)
            return {'dependency': declaration.value, 'source': declaration.kind}
        kinds = [k for k in ('package','local_path','git_url','framework') if options.get(k)]
        if len(kinds) != 1: raise ValueError('请选择一种依赖来源')
        if options.get('unbundled') is not None and kinds[0] not in ('local_path', 'git_url'):
            raise ValueError('unbundled 只用于本地或通用 Git 游戏依赖')
        if kinds[0] == 'git_url':
            result = service.add_git(options['git_url'], ref=options.get('git_ref'),name=options.get('dep_name'),
                                     subdir=options.get('subdir'),kind=options.get('kind'),target=options.get('target'),unbundled=options.get('unbundled'))
        elif kinds[0] == 'framework':
            result = service.add_framework(options['framework'],script_dir=options.get('script_dir'),source=options.get('source'))
        elif kinds[0] == 'local_path':
            changed, _ = service.add_local(options['local_path'], unbundled=options.get('unbundled'));result={'changed':changed}
        else:
            if options.get('unbundled') is not None:
                raise ValueError('Python 工具包不支持游戏依赖 unbundled')
            result={'changed':service.add_package(options['package'])}
        from ..consumer_prepare import guidance
        result['preparation'] = guidance(project)
        if kinds[0] == 'local_path':
            from ..dependencies import canonical_path, resolve_path, included_in_release
            entry = next(item for item in service.list() if item.kind == 'local' and canonical_path(resolve_path(project, item.value)) == canonical_path(resolve_path(project, options['local_path'])))
            result.update(unbundled=entry.unbundled, included_in_release=included_in_release(service.last_resolution, resolve_path(project, entry.value)))
        return result
    if operation == 'script.list':
        from ..project_scripts import describe_scripts
        return describe_scripts(project, effective=options.get('effective', False))
    if operation == 'script.run':
        from ..project_scripts import operation as script_operation
        with script_operation(project, task=options['name'], args=options.get('args',())) as results:
            return {'scripts':results}
    if operation == 'prepare_run':
        from .build import build_project
        return build_project(project, preparation_event='before_run')
    raise ValueError('Unsupported project operation')

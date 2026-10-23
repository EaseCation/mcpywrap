"""Route complete public commands before any local operation or project import."""
from pathlib import Path
import click
from . import profiles
from .client import Client


def route(ctx):
    from ..command_context import _context, project_dir
    command = []
    cursor = ctx
    while cursor.parent is not None:
        command.insert(0, cursor.info_name); cursor = cursor.parent
    if not command or command[0] in ('host','skill','modsdk'): return False, None
    profile = profiles.select(project_dir())
    if profile is None: return False, None
    context = _context.get()
    if context.local or (context.remote and context.remote.rstrip('/') != profile['endpoint']):
        raise click.UsageError('此工作区已绑定 mcpy App；--local/其他远端与绑定冲突，请先 mcpy host disconnect。')
    operation = '.'.join(command)
    params = dict(ctx.params)
    if params.get('clients', 1) != 1 or params.get('group'):
        raise click.UsageError('此宿主仅支持作品内的单游戏实例')
    if operation == 'status':
        if bool(params.get('session')) == bool(params.get('list_sessions')):
            raise click.UsageError('指定 --session 或 --list 中的一项')
    elif operation in ('logs','stop','restart','runtime.capabilities','runtime.watch','runtime.reload') and not params.get('session'):
        raise click.UsageError('请用 --session 指定目标会话')
    if operation == 'logs':
        if params.get('summary') and params.get('follow'): raise click.UsageError('--summary 不与 --follow 同用')
        if params.get('since_ms') is not None and params.get('until_ms') is not None and params['since_ms']>params['until_ms']:
            raise click.UsageError('--since-ms 不能大于 --until-ms')
        if params.get('source') not in ('game','engine','client','server','all'):
            raise click.UsageError('日志来源必须为 game、engine、client、server 或 all')
        if not params.get('follow') and (params.get('tail')==0 or params.get('output_format')!='text'):
            raise click.UsageError('--format jsonl 和 --tail 0 仅用于 --follow')
    if operation=='logs' and params.get('follow'):
        from ..command_context import json_output
        if json_output(): raise click.UsageError('持续命令不使用 --json')
        from .streams import follow_logs
        return True, follow_logs(profile,project_dir(),params)
    if operation == 'status': params['list'] = params.pop('list_sessions',False)
    if operation == 'mod':
        if params.pop('gui',False): raise click.UsageError('手机宿主不提供桌面 Qt 界面')
        params['source']=params.pop('qumod_source',None)
    if operation == 'add':
        if params.pop('qumod',False): params['framework']='qumod'
        params['source']=params.pop('preset_source',None)
    if operation == 'remove':
        for key in ('uninstall',):
            if params.pop(key,None): raise click.UsageError('当前宿主未提供该移除选项')
    if params.get('local_path'):
        path=Path(params['local_path']).expanduser()
        if path.is_absolute():
            try: params['local_path']='/sdcard/mcpy/'+path.resolve().relative_to(Path(profile['workspace'])).as_posix()
            except ValueError: raise click.UsageError('组件依赖必须位于共享 mcpy 目录') from None
    if operation == 'runtime.py':
        from ..commands.runtime_cmd import code_argument
        params['code'] = code_argument(params.get('code'), params.pop('filename', None))
    elif operation == 'runtime.reload' and params.get('filename'):
        source = Path(params['filename']).resolve()
        try: params['filename'] = source.relative_to(project_dir()).as_posix()
        except ValueError: raise click.UsageError('热更文件必须位于当前作品内') from None
    if operation == 'screenshot':
        from ..commands.desktop_cmd import output_path, save_image
        output = output_path(params.pop('output', None))
        client = Client(profile)
        result = client.operation(operation, project_dir(), params)
        content = client.request('GET', '/artifacts/'+result['artifact_id'], binary=True)
        if not content.startswith(b'\x89PNG\r\n\x1a\n'): raise ValueError('宿主未返回有效游戏 PNG')
        save_image(output, content)
        return True, dict(result, image=str(output))
    result=Client(profile).operation(operation, project_dir(), params)
    if operation=='logs':
        from ..command_context import json_output
        if not json_output():
            from ..mcstudio.log_query import show_snapshot
            show_snapshot(result,params.get('summary',False))
            return True,None
    return True,result

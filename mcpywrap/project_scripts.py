"""Finite root-project commands. No task graph, implicit hooks, or watch scheduler."""
from contextlib import contextmanager, nullcontext
from pathlib import Path
import codecs
import json
import math
import os
import shutil
import subprocess
import sys
import time
import uuid

import click

from .dependencies import read_project
from .runtime import storage
from .utils.locks import directory_lock

EVENTS = ('before_build', 'before_package', 'before_run')
CHAIN_ENV = '_MCPY_SCRIPT_CHAIN'


class ScriptError(ValueError):
    def __init__(self, message, code='script_failed', **details):
        super().__init__(message)
        self.code, self.details = code, details
        self.hint = '查看 script_log；脚本对源码的修改不会自动回滚。'


def _strings(value, label, nonempty=False):
    if not isinstance(value, list) or (nonempty and not value) or any(
            not isinstance(v, str) or '\0' in v for v in value):
        raise ScriptError(label + ' 必须是字符串数组', 'script_config_invalid')
    return value


def configuration(project):
    settings = read_project(project).get('tool', {}).get('mcpywrap', {})
    scripts, hooks = settings.get('scripts', {}), settings.get('hooks', {})
    if not isinstance(scripts, dict) or not isinstance(hooks, dict):
        raise ScriptError('scripts/hooks 必须是 TOML 表', 'script_config_invalid')
    if hooks.keys() - set(EVENTS):
        raise ScriptError('未知的 hook: ' + ', '.join(sorted(hooks.keys() - set(EVENTS))), 'script_config_invalid')
    result = {}
    for name, entry in scripts.items():
        if not name.strip() or not isinstance(entry, dict):
            raise ScriptError('脚本必须是有名称的 TOML 表', 'script_config_invalid')
        unknown = entry.keys() - {'python', 'cmd', 'args', 'env', 'timeout'}
        if unknown or ('python' in entry) == ('cmd' in entry):
            raise ScriptError(name + ': 仅支持 python 或 cmd，以及 args/env/timeout', 'script_config_invalid')
        if 'python' in entry:
            filename = entry['python']
            if not isinstance(filename, str) or not filename.strip() or '\0' in filename or Path(filename).is_absolute():
                raise ScriptError(name + ': python 必须是项目内相对文件路径', 'script_config_invalid')
            path = (Path(project)/filename).resolve()
            if not path.is_relative_to(Path(project).resolve()):
                raise ScriptError(name + ': python 路径越界', 'script_config_invalid')
            command = [sys.executable, '-u', str(path), *_strings(entry.get('args', []), name + '.args')]
        else:
            if 'args' in entry:
                raise ScriptError(name + ': cmd 已包含参数，不接受 args', 'script_config_invalid')
            command = list(_strings(entry['cmd'], name + '.cmd', True))
            if not command[0].strip():
                raise ScriptError(name + ': cmd 可执行程序不能为空', 'script_config_invalid')
        env = entry.get('env', {})
        if not isinstance(env, dict) or any(not isinstance(k, str) or not k or '=' in k or '\0' in k
                or k.upper().startswith(('MCPY_', '_MCPY_')) or not isinstance(v, str) or '\0' in v
                for k, v in env.items()):
            raise ScriptError(name + ': env 必须是字符串映射，不能覆盖 MCPY_* 上下文', 'script_config_invalid')
        timeout = entry.get('timeout', 120)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 86400:
            raise ScriptError(name + ': timeout 必须在 0–86400 秒之间', 'script_config_invalid')
        result[name] = {'command': command, 'env': env, 'timeout': timeout, 'python': 'python' in entry}
    for event, names in hooks.items():
        _strings(names, event)
        if len(names) != len(set(names)) or any(name not in result for name in names):
            raise ScriptError(event + ': 任务不存在或重复引用', 'script_config_invalid')
    return result, hooks


def reject_recursion():
    if os.environ.get(CHAIN_ENV):
        raise ScriptError('脚本不能递归启动 mcpy 写操作；请在脚本中组合处理逻辑。', 'script_recursion')


def configured(project):
    settings = read_project(project).get('tool', {}).get('mcpywrap', {})
    return bool(settings.get('scripts') or settings.get('hooks'))


def _active_process(record):
    from .mcstudio.processes import observed_process
    for key in ('supervisor', 'child'):
        if record.get(key) and observed_process(record[key]):
            return True
    if os.name != 'nt' and record.get('group'):
        import psutil
        for p in psutil.process_iter(['pid', 'status', 'create_time']):
            try:
                if (p.info['status'] != psutil.STATUS_ZOMBIE and os.getpgid(p.pid) == record['group']
                        and p.info['create_time'] >= record['started_at'] - 1):
                    return True
            except (ProcessLookupError, PermissionError, psutil.NoSuchProcess):
                pass
    return False


@contextmanager
def operation(project, event=None, *, task=None, args=(), cancel=None, progress=None, lock_held=False):
    """Hold the cooperative lock through the caller's consumption of generated files."""
    project = Path(project).resolve()
    reject_recursion()
    scripts, hooks = configuration(project)
    names = [task] if task is not None else hooks.get(event, [])
    if any(name not in scripts for name in names):
        raise ScriptError('未定义脚本: ' + str(task), 'script_not_found')
    directory = project/'.mcpy/scripts'
    # Existing active record is checked even after scripts are removed from config.
    if not scripts and not hooks and not (directory/'active.json').exists():
        yield []
        return
    with nullcontext() if lock_held else project_lock(project):
        results = []
        for name in names:
            if cancel and cancel():
                raise ScriptError('脚本执行已取消', 'script_cancelled', script=name, event=event)
            results.append(_execute(project, name, scripts[name], event or 'manual', args,
                                    cancel=cancel, progress=progress))
        if cancel and cancel():
            raise ScriptError('操作已取消', 'script_cancelled', event=event)
        yield results


@contextmanager
def project_lock(project):
    project = Path(project).resolve()
    reject_recursion()
    directory = project/'.mcpy/scripts'
    if not configured(project) and not (directory/'active.json').exists():
        yield
        return
    with directory_lock(directory/'lock'):
        active = storage.read(directory/'active.json', {})
        if active:
            state = storage.read(active['state_path'], {})
            if _active_process(state) or state.get('state') == 'spawning':
                raise ScriptError('上次脚本的进程尚未确认退出，未开始新操作。', 'script_recovery_required',
                                  script_log=active['log_path'], script_state=active['state_path'])
        yield


def startup_budget(project):
    scripts, hooks = configuration(project)
    return sum(scripts[name]['timeout'] for name in hooks.get('before_run', []))


def snapshot_digest(project):
    import hashlib
    return hashlib.sha256(repr(sorted(project_snapshot(project).items())).encode('utf-8')).hexdigest()


def startup_hooks(data, deployment):
    """Called only by local launchers while holding project/world/deployment locks."""
    from .mcstudio import sessions
    project = data['project']
    if data.get('script_config_digest') and snapshot_digest(project) != data['script_config_digest']:
        raise ScriptError('准备期间项目配置已变化，请重新运行。', 'script_config_changed')
    if not configured(project):
        return
    deployment.preflight()
    from .runtime.deployment import runtime_builder
    runtime_builder(project, deployment.target).initialize()
    def progress(task):
        data['script'] = task
        sessions.save(sessions.session_path(project, data['session'])/'session.json', data)
    stop = sessions.session_path(project, data['session'])/'stop'
    config_path = Path(data['config_path'])
    original_config = config_path.read_bytes() if config_path.exists() else None
    with before(project, 'before_run', cancel=stop.exists, progress=progress, lock_held=True) as results:
        if (config_path.read_bytes() if config_path.exists() else None) != original_config:
            raise ScriptError('前置脚本修改了世界配置，本次启动已停止。', 'script_config_changed')
        data['scripts'] = results


def _execute(project, name, spec, event, extra, *, cancel=None, progress=None):
    env = dict(os.environ)
    env.update({key.upper() if os.name == 'nt' else key: value for key, value in spec['env'].items()})
    env.update({CHAIN_ENV: '1', 'MCPY_PROJECT_ROOT': str(project), 'MCPY_EVENT': event,
                'MCPY_OPERATION': {'before_build': 'build', 'before_package': 'package',
                                   'before_run': 'run'}.get(event, 'script'),
                'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1'})
    command = list(spec['command']) + list(extra)
    if spec['python'] and not Path(command[2]).is_file():
        raise ScriptError('脚本文件不存在: ' + command[2], 'script_not_found', script=name, event=event)
    executable = command[0]
    if '/' in executable or '\\' in executable:
        executable = os.path.abspath(project/executable)
    else:
        executable = shutil.which(executable, path=env.get('PATH', ''))
    if not executable or not Path(executable).is_file():
        raise ScriptError('找不到可执行程序: ' + command[0], 'script_not_found', script=name, event=event, cwd=str(project))
    if os.name == 'nt' and Path(executable).suffix.lower() in ('.bat', '.cmd'):
        raise ScriptError('批处理请显式使用 cmd.exe /c 或 PowerShell 调用', 'script_config_invalid', script=name)
    command[0] = executable
    directory = project/'.mcpy/scripts'/uuid.uuid4().hex
    directory.mkdir(parents=True)
    log, state_path, stop = directory/'output.log', directory/'result.json', directory/'cancel'
    from .mcstudio.processes import identity, background_options
    details = {'script': name, 'event': event, 'script_log': str(log), 'script_state': str(state_path)}
    metadata = dict(details, cwd=str(project), executable=executable, started_at=time.time(), state='starting')
    storage.write(state_path, metadata)
    storage.write(directory.parent/'active.json', {'state_path': str(state_path), 'log_path': str(log)})
    click.echo('[script] ' + event + ' → ' + name, err=True)
    if progress:
        progress(dict(details, state='running'))
    worker = Path(__file__).with_name('_script_worker.py')
    process = None
    interrupted = False
    try:
        with log.open('wb') as output:
            process = subprocess.Popen([sys.executable, '-u', str(worker)], cwd=project,
                                       env=env, stdin=subprocess.PIPE, stdout=output, stderr=output,
                                       **background_options())
            payload = dict(metadata, command=command, timeout=spec['timeout'],
                           result=str(state_path), cancel=str(stop), parent=identity(os.getpid()))
            process.stdin.write(json.dumps(payload).encode('utf-8'))
            process.stdin.close()
            decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
            with log.open('rb') as reader:
                while True:
                    chunk = reader.read(65536)
                    if chunk:
                        click.echo(decoder.decode(chunk), nl=False, err=True)
                    if cancel and cancel():
                        stop.touch()
                    if process.poll() is not None:
                        # Drain in bounded chunks, including output without a newline.
                        while True:
                            chunk = reader.read(65536)
                            if not chunk: break
                            click.echo(decoder.decode(chunk), nl=False, err=True)
                        click.echo(decoder.decode(b'', final=True), nl=False, err=True)
                        break
                    time.sleep(.05)
    except KeyboardInterrupt:
        interrupted = True
        stop.touch()
        raise
    except OSError as exc:
        raise ScriptError('无法执行脚本: ' + str(exc), 'script_start_failed', **details) from exc
    finally:
        if process and process.poll() is None:
            stop.touch()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                if not interrupted:
                    raise ScriptError('脚本进程尚未确认退出，保留记录。', 'script_recovery_required', **details)
    result = storage.read(state_path, {})
    if result.get('state') != 'completed':
        if result.get('state') in ('starting', 'spawning', 'running'):
            result['code'] = 'script_recovery_required'
        raise ScriptError('脚本 %s 未完成：%s' % (name, result.get('error') or result.get('state')),
                          result.get('code', 'script_failed'), **details,
                          script_exit_code=result.get('exit_code'))
    if progress:
        progress(dict(details, state='completed'))
    return {**details, 'exit_code': result['exit_code'], 'duration': result['duration']}


def project_snapshot(project):
    """Protect operation config and pack identity, not arbitrary user source writes."""
    project = Path(project)
    files = {project/'pyproject.toml', project/'mcpy-git.lock.json', project/'mcpy-code-libraries.lock.json'}
    for path in project.iterdir():
        if path.is_dir() and path.name.startswith(('behavior_pack', 'resource_pack', 'BehaviorPack', 'ResourcePack')):
            files.update(path.rglob('manifest.json'))
            files.update(path.rglob('pack_manifest.json'))
    return {str(path.relative_to(project)): path.read_bytes() if path.is_file() else None for path in files}


@contextmanager
def before(project, event, *, cancel=None, progress=None, lock_held=False):
    snapshot = project_snapshot(project) if configured(project) else None
    with operation(project, event, cancel=cancel, progress=progress, lock_held=lock_held) as results:
        if snapshot is not None and snapshot != project_snapshot(project):
            raise ScriptError('前置脚本修改了项目配置、依赖锁或包身份；本次操作已停止。', 'script_config_changed')
        yield results


def validate_build(project, target):
    """Preflight destinations/structure without running hooks or publishing files."""
    from .runtime.deployment import check_build_target
    from .builders.project_builder import AddonProjectBuilder
    from .dependencies import DependencyService
    from .builders.assembly import validate_target, is_within
    from .utils.paths import is_link
    if is_link(target):
        raise ValueError('构建目标不能是目录链接')
    kind = read_project(project).get('tool', {}).get('mcpywrap', {}).get('project_type', 'addon')
    check_build_target(project, target)
    if kind == 'addon':
        AddonProjectBuilder(project, target).initialize()
    elif kind == 'map':
        manager = DependencyService(project).resolve()
        validate_target(target, project, list(manager.get_all_dependencies().values()) + [manager.root_node.addon_pack])
        if any(is_within(target, Path(project)/name) for name in ('behavior_packs', 'resource_packs', 'db')):
            raise ValueError('构建输出不能位于地图数据目录内')
    else:
        raise ValueError('当前仅支持 Addon 和 Map 项目')


def skipped_network(project):
    hooks = read_project(project).get('tool', {}).get('mcpywrap', {}).get('hooks', {})
    if isinstance(hooks, dict) and hooks.get('before_run'):
        from .command_context import report_warning
        report_warning('本次仅连接服务器，不执行本地 before_run 脚本。')

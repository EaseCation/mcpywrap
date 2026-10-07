"""Anonymous server launch using the shared cppconfig and session lifecycle."""
from dataclasses import asdict
from pathlib import Path
import uuid

import click
from . import install
from .host import EngineError, require_macos


def connect(target, *, project_dir=None, packs=(), engine_overrides=None, detach=False):
    from ..command_context import project_dir as current_project, json_output
    from ..mcstudio import sessions
    from ..remote.service import directory_lock
    from .macos import ensure_runtime, pinned_runtime
    require_macos()
    if json_output() and not detach:
        raise click.UsageError('网络运行 --json 需要 --detach；使用 status/logs/stop 管理返回的会话')
    overrides = engine_overrides or {}
    if target.auth != 'none' or overrides.get('game_executable_path') or overrides.get('mcs_download_path'):
        raise EngineError('macOS 服务器连接仅支持无认证模式；MC Studio 身份和 EXE 参数仅适用于 Windows。',
                          'unsupported_option')
    root = Path(project_dir or current_project()).resolve()
    with directory_lock(install.home()/'install-lock'):
        state = pinned_runtime({'installation': ensure_runtime()})
        if state.get('network_connect_protocol') != 1:
            raise EngineError('此 macOS 运行包尚不支持连接服务器。', 'runtime_incompatible',
                              '请执行 mcpy engine install --catalog ' + install.DEFAULT_CATALOG + '，再重试；已有世界保留原绑定。')
        version = state['profile']['apk']['version']
        requested = overrides.get('engine_version')
        if requested and requested != version:
            raise EngineError('当前资源版本为 ' + version, 'engine_version_mismatch',
                              '请使用匹配的资源，或省略 --engine-version。')
        session = uuid.uuid4().hex
        directory = sessions.session_path(root, session)
        plan = {'runtime': state['runtime'], 'game': state['game'],
                'data': str(directory/'native/data'), 'cache': str(directory/'native/cache'),
                'engine_version': version, 'compat_report': state.get('compat_report'),
                'cppconfig': str(directory/'runtime.cppconfig')}
        data = sessions.start(root, backend='macos-arm64', session_id=session, launch=plan,
                              network={'target': asdict(target), 'engine': {'version': version}})
    result = sessions.handoff(data)
    if detach:
        return result
    click.echo(f'连接 {target.host}:{target.port}（无认证）；不装配本地 Mod。')
    from .tui import watch_session
    return watch_session(root, session)

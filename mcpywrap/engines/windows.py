"""Adapter for the existing MC Studio implementation (including legacy GUI)."""
from .backend import GameBackend, LaunchedGame


class WindowsBackend(GameBackend):
    id = 'windows'
    label = 'Windows · MC Studio'
    capabilities = ('local-worlds', 'network-sessions', 'status', 'logs', 'stop', 'py',
                    'runtime', 'runtime-ui', 'runtime-player', 'reload', 'watch',
                    'screenshot', 'key', 'mouse', 'input-sequence', 'mcs-auth', 'serve', 'project-ui', 'editor')
    setup_description = '请在 MC Studio 下载游戏引擎；使用 mcpy doctor 检查资源，可用 --engine-version 选择版本。'

    def reload_restriction(self, data, kind):
        from pathlib import Path
        version = (data.get('launch') or {}).get('engine_version') or Path(
            data.get('game', {}).get('executable', '')).parent.name
        if kind == 'shader' and version in ('3.9.0.401155', '3.10.0.420447'):
            return '此引擎版本的 Shader 重载未经安全验证或曾阻塞游戏线程'
        return None

    def run(self, project, **options):
        from ..commands.run_cmd import _run_windows
        return _run_windows(project, **options)

    def instances(self, project):
        from ..commands.run_cmd import _get_all_instances
        return _get_all_instances(project)

    def delete_instances(self, project, identity=None):
        from ..commands.run_cmd import _delete_instance, _clean_all_instances
        from ..command_context import project_scope
        from ..mcstudio import sessions
        from ..mcstudio.processes import checked_process
        from pathlib import Path
        for path in (Path(project)/'.runtime/sessions').glob('*/session.json'):
            data = sessions.read(project, path.parent.name)
            if (identity is None or data.get('level_id') == identity) and (data['state'] in ('starting', 'running') or (data.get('game') and checked_process(data['game']))):
                from .host import EngineError
                raise EngineError('实例正在运行，请先保存退出。', 'busy')
        with project_scope(project):
            return _delete_instance(identity, True, project) if identity else _clean_all_instances(True, project)

    def deploy(self, project, data):
        from ..commands.run_cmd import _setup_dependencies
        from ..dependencies import read_project
        name = read_project(project).get('project', {}).get('name', 'project')
        _setup_dependencies(name, str(project), raise_errors=True)

    def connect(self, target, **options):
        from ..mcstudio.network import run_network
        return run_network(target, **options)

    def diagnose(self, project=None, overrides=None, mcs_auth=False, check_files=False):
        from ..mcstudio.diagnostics import diagnose
        data = diagnose(project, overrides, mcs_auth)
        data.update(backend=self.id, state='ready' if data['ok'] else 'setup_required')
        if not data['ok']: data.setdefault('hint', self.setup_description)
        return data

    def launch(self, data, receiver, auth_context=None):
        from ..mcstudio import sessions
        directory = sessions.session_path(data['project'], data['session'])
        if data.get('mode') == 'network':
            from ..mcstudio.network import launch_network, ServerTarget
            from ..mcstudio.discovery import Engine
            process = launch_network(Engine(**data['network']['engine']),
                                     ServerTarget(**data['network']['target']),
                                     directory/'runtime.cppconfig', receiver.port, auth_context)
        else:
            from ..commands.run_cmd import _run_game_with_instance
            from ..command_context import project_scope
            with project_scope(data['project']):
                success, process = _run_game_with_instance(
                    data['config_path'], data['level_id'], [], wait=False,
                    engine_overrides=data['engine_overrides'], no_gui=True, logging_port=receiver.port,
                    output_path=str(directory/'engine.log'), capture_output=True,
                    **({'auth_context': auth_context, 'auth_config_path': str(directory/'auth.cppconfig')} if auth_context else {}))
            if not success: process = None
        return LaunchedGame(process)

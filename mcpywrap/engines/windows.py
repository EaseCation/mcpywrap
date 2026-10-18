"""Adapter for the existing MC Studio implementation (including legacy GUI)."""
from .backend import GameBackend, LaunchedGame


class WindowsBackend(GameBackend):
    id = 'windows'
    label = 'Windows · MC Studio'
    capabilities = ('local-worlds', 'network-sessions', 'status', 'logs', 'stop', 'py',
                    'runtime', 'runtime-ui', 'runtime-player', 'reload', 'watch',
                    'screenshot', 'key', 'mouse', 'input-sequence', 'mcs-auth', 'serve', 'project-ui', 'editor',
                    'local-dual-client-manual')
    setup_description = '请在 MC Studio 下载游戏引擎；使用 mcpy doctor 检查资源，可用 --engine-version 选择版本。'

    def debug_channel(self, data, write_log):
        from ..mcstudio.runtime_debug import SafaiaChannel
        self._world_ready = False
        self._ready_log_cursors = {}
        data['world_ready'] = False
        return SafaiaChannel(write_log, ready=lambda: self._world_ready)

    def refresh(self, data, channel):
        if self._world_ready: return False
        from pathlib import Path
        import re
        for name in ('log_path', 'engine_log_path'):
            if not data.get(name): continue
            path = Path(data[name])
            offset, pending = self._ready_log_cursors.get(name, (0, b''))
            try:
                with path.open('rb') as stream:
                    stream.seek(offset)
                    chunk = stream.read(65536)
                    offset = stream.tell()
            except FileNotFoundError:
                continue
            text = pending + chunk
            # Both markers require a created gameplay HUD. The native layout
            # marker also works if the Python launch logging handler raises.
            hud = (b'OnHandlePushScreen hud_screen' in text if name == 'log_path' else
                   re.search(rb"\bINFO GUI [^\r\n]*\] Layout main thread: [^\r\n]*controls completed [^\r\n]*for screen 'hud\.hud_screen'\.", text))
            self._ready_log_cursors[name] = (offset, text[-1024:])
            if hud:
                self._world_ready = data['world_ready'] = True
                return True
        return False

    def reload_restriction(self, data, kind):
        from pathlib import Path
        version = (data.get('launch') or {}).get('engine_version') or Path(
            data.get('game', {}).get('executable', '')).parent.name
        if kind == 'shader' and version in ('3.9.0.401155', '3.10.0.420447'):
            return '此引擎版本的 Shader 重载未经安全验证或曾阻塞游戏线程'
        return None

    def run(self, project, **options):
        from ..runtime.windows import run
        return run(project, **options)

    def instances(self, project):
        from ..runtime.instances import list_instances
        return list_instances(project)

    def delete_instances(self, project, identity=None):
        return self.run(project, delete=identity, clean_all=identity is None, force=True)

    def deploy(self, project, data):
        from ..runtime.deployment import refresh
        refresh(project, data)

    def connect(self, target, **options):
        from ..mcstudio.network import run_network
        return run_network(target, **options)

    def prepare_guest(self, host):
        return None

    def start_guest(self, host, *, project_dir, session_id, group, role, player):
        from ..mcstudio import sessions
        from ..mcstudio.discovery import require_resources, Engine
        from ..runtime.deployment import Deployment
        from ..runtime import storage
        from .host import EngineError
        engine = host['launch']['engine']
        require_resources(Engine(**engine))
        target = (host.get('deployment') or {}).get('path')
        if not target:
            raise EngineError('无法确认主机加载的版本，请重启联调组。', 'deployment_unavailable')
        deployment = Deployment(project_dir, target)
        with deployment.lock():
            record = storage.read(deployment.record_path, {})
            version = record.get('fingerprint') if isinstance(record, dict) else None
            if not version:
                raise EngineError('无法确认主机加载的版本，请重启联调组。', 'deployment_unavailable')
        data = sessions.start(project_dir, session_id=session_id, group=group, role=role,
                              network={'target': None, 'engine': engine, 'player': player,
                                       'local_host': host['session'], 'join': 'manual',
                                       'deployment_fingerprint': version})
        return sessions.handoff(data)

    def diagnose(self, project=None, overrides=None, mcs_auth=False, check_files=False):
        from ..mcstudio.diagnostics import diagnose
        data = diagnose(project, overrides, mcs_auth)
        data.update(backend=self.id, state='ready' if data['ok'] else 'setup_required')
        if not data['ok']: data.setdefault('hint', self.setup_description)
        return data

    def launch(self, data, receiver, auth_context=None):
        from contextlib import ExitStack
        from ..mcstudio import sessions
        directory = sessions.session_path(data['project'], data['session'])
        if data.get('mode') != 'network':
            from ..runtime.windows import launch
            return launch(data, receiver, auth_context)
        guard = ExitStack()
        try:
            from ..mcstudio.discovery import Engine
            engine = Engine(**data['network']['engine'])
            environment = None
            if data.get('group'):
                from ..runtime.profiles import PlayerProfile
                profile = PlayerProfile(data)
                guard.enter_context(profile.lease())
                profile.prepare()
                environment = profile.windows_environment()
            sessions.require_launch_requested(data['project'], data['session'])
            data['phase'] = 'prepared'
            sessions.save(directory/'session.json', data)
            if data['network'].get('join') == 'manual':
                from ..runtime.groups import is_local_guest
                from ..mcstudio.game import open_game
                if not is_local_guest(data['project'], data):
                    raise ValueError('本地主机已退出或联调成员已变更，取消客机启动')
                process = open_game(None, engine=engine, logging_ip='127.0.0.1',
                                    logging_port=receiver.port, wait=False, use_system_color=False,
                                    capture_output=True, environment=environment)
            else:
                from ..mcstudio.network import launch_network, ServerTarget
                process = launch_network(engine, ServerTarget(**data['network']['target']),
                                         directory/'runtime.cppconfig', receiver.port, auth_context,
                                         player=data['network'].get('player'), environment=environment)
            return LaunchedGame(process, guard=guard)
        except BaseException:
            guard.close()
            raise

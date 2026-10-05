"""Local runtime boundary. Routing to a remote host happens before selection.

Commands own presentation; backends own installation, launch and engine-specific
transports. The worker owns process/log/control-server lifetime on every platform.
"""
from dataclasses import dataclass
from .host import EngineError, describe


@dataclass
class LaunchedGame:
    process: object
    capture_output: bool = True


class GameBackend:
    id = None
    label = '此平台'
    capabilities = ()
    setup_description = '本机运行支持 Windows 和 Apple Silicon macOS；也可配置 Windows 远程服务。'
    managed_install = False

    def unsupported(self, feature):
        raise EngineError(self.label + ' 暂不支持' + feature, 'unsupported_feature', self.setup_description)

    def run(self, project, **options):
        return self.unsupported('本地游戏运行')

    def instances(self, project):
        return []

    def delete_instances(self, project, identity=None):
        return self.run(project, delete=identity, clean_all=identity is None, force=True)

    def start_session(self, project, identity=None, auth_context=None, overrides=None, world_config=None):
        from ..command_context import project_scope
        with project_scope(project):
            return self.run(project, new=identity is None, instance_prefix=identity,
                            detach=True, no_gui=True, **({'auth_context': auth_context} if auth_context else {}),
                            **({'overrides': overrides} if overrides else {}),
                            **({'world_config': world_config} if world_config is not None else {}))

    def world_option_restrictions(self):
        """Unsupported cppconfig fields for presentation; adapters also validate."""
        return {}

    def watch_directory(self, project, data):
        from pathlib import Path
        return Path(project)/'.mcpy/runtime/watch'

    def deploy(self, project, data):
        """Refresh runtime files before resource reload; Windows uses existing links."""

    def reload_restriction(self, data, kind):
        """Return a verified engine-specific limitation before deploying/calling it."""
        return None

    def ui_reload_code(self):
        """Client Python entry point; the common reload flow owns validation/results."""
        return """import gui
_pressed = []
try:
    for _key in (17, 82):
        _pressed.append(_key)
        if not gui.simulate_keyboard_event(_key, True):
            raise ValueError('引擎拒绝 UI 重载快捷键')
finally:
    for _key in reversed(_pressed):
        gui.simulate_keyboard_event(_key, False)
_result = {'ok': True}
"""

    def reload_ui(self, project, session):
        from ..mcstudio.hot_reload import reload_ui
        return reload_ui(project, session)

    def connect(self, target, **options):
        return self.unsupported('连接服务器；可使用 --remote <Windows 服务地址>')

    def diagnose(self, project=None, overrides=None, mcs_auth=False, check_files=False):
        return {'ok': False, 'backend': self.id, 'state': 'unsupported_platform', 'hint': self.setup_description}

    def install(self, catalog=None, apk=None, progress=None):
        return self.unsupported('自动安装')

    def installation_choice(self):
        return None

    def launch(self, data, receiver, auth_context=None):
        return self.unsupported('启动会话')

    def debug_channel(self, data, write_log):
        from ..mcstudio.runtime_debug import SafaiaChannel
        return SafaiaChannel(write_log)

    def refresh(self, data, channel):
        """Return True only when session metadata changed; may raise on startup failure."""
        return False

    def handoff(self, data):
        return {'backend': self.id}


def get_backend(backend_id=None):
    """Explicit IDs resume recorded sessions; unknown IDs never silently fall back."""
    selected = backend_id if backend_id is not None else describe()['backend']
    if selected == 'windows':
        from .windows import WindowsBackend
        return WindowsBackend()
    if selected == 'macos-arm64':
        from .macos import MacOSBackend
        return MacOSBackend()
    if backend_id is not None:
        raise EngineError('未知运行后端：' + backend_id, 'unknown_backend')
    return GameBackend()

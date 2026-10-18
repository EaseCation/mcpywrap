"""只读会话契约：不执行游戏代码，不把可调用入口当作效果或加载成功。"""
import json
from . import sessions
from .processes import checked_process
from .hot_reload import KINDS
from ..engines.backend import get_backend


def inspect_session(project, session):
    data = sessions.read(project, session)
    backend = get_backend(data.get('backend', 'windows'))
    live = (data['state'] == 'running' and bool(data.get('game')) and
            bool(checked_process(data['game'])) and bool(data.get('worker')) and
            bool(checked_process(data['worker'])))
    control = {}
    path = sessions.session_path(project, session)/'control.json'
    if live and path.is_file():
        control = json.loads(path.read_text(encoding='utf-8'))
    from ..runtime.groups import is_local_guest
    guest = is_local_guest(project, data)
    local = data.get('mode') == 'local'
    available = live and bool(control)
    reloads = {}
    for kind in KINDS:
        reason = None
        if not local and not guest:
            reason = '资源和模块热更仅支持本地测试世界'
        else:
            reason = backend.reload_restriction(data, kind)
        if guest and kind != 'python':
            reason = '客机使用下载缓存，资源热更尚未验证；请重新运行联调组并从卡片加入'
        reloads[kind] = {
            'state': 'unsupported' if reason else 'available' if available else 'unavailable',
            'reason': reason or (None if available else '会话没有运行中的游戏及调试通道'),
            'effect_verified': False,
        }
    sides = ['client', 'server'] if local else ['client']
    from .screenshot import supported, UPGRADE_HINT
    screenshot_supported = supported(data)
    return {
        'schema_version': 1, 'session': session, 'backend': backend.id,
        'state': data['state'], 'mode': data.get('mode'),
        'control': {'available': available, 'gui_required': False, 'tui_required': False,
                    'display_required': True, 'game_window_required': True},
        'python': {'sides': sides if available else [],
                   'client_queue': control.get('client_python_queue') if available else False,
                   'reload_sides': [side for side in sides if side in control.get('python_reload_sides', [])]
                                   if available and (local or guest) else []},
        'reload': reloads,
        'screenshot': {'state': ('available' if live else 'unavailable') if screenshot_supported else 'unsupported',
                       'reason': None if screenshot_supported else UPGRADE_HINT},
        'verification': 'entrypoints_only',
        'hint': 'available 表示允许调用，不证明游戏已就绪、API 存在或效果生效；JSON UI 重载后须按 Mod 逻辑重新注册创建界面及绑定回调。',
    }

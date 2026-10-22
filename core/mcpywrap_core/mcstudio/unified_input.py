"""统一入口路由：游戏内复用 Python，Windows 特殊输入由会话 worker 持有。"""
import json
import uuid
from pathlib import Path
from ..input_plan import normalize_input_plan


def execute(project, session, action, parameters=None):
    from ..command_context import remote_url
    from ..remote.client import Client
    from .runtime_debug import control_request
    from .runtime_ui import execute as game_execute
    parameters = dict(parameters or {})
    if action == 'run':
        parameters['plan'] = normalize_input_plan(parameters['plan'])
        parameters['request_id'] = parameters.get('request_id') or uuid.uuid4().hex
    endpoint = remote_url()
    client = Client(endpoint, project) if endpoint else None
    if client:
        worker = 'unified-input' in client.request('GET', '/capabilities', timeout=15).get('capabilities', [])
    else:
        from .sessions import session_path
        path = session_path(project, session)/'control.json'
        metadata = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
        worker = metadata.get('unified_input_worker', False)
    windows = action == 'run' and parameters['plan']['backend'] == 'windows-sendinput'
    if windows and not worker:
        return {'ok': False, 'code': 'not_supported', 'error': '该会话 worker 未提供统一 Windows 输入；更新工具后重启会话，不改用游戏输入'}
    # 旧 worker 的 game 传输仍可复用；这不是输入后端降级。
    if not worker:
        return game_execute(project, session, action, parameters, family='input')
    try:
        response = (client.request('POST', '/sessions/'+session+'/input', {'method': action, 'parameters': parameters})
                    if client else control_request(project, session, 'input', method=action, parameters=parameters))
        return dict(response, session=session)
    except (ValueError, OSError) as error:
        return {'ok': False, 'state': 'unknown', 'error': str(error), 'session': session,
                'operation_id': parameters.get('request_id', parameters.get('operation')),
                'request_id': parameters.get('request_id'), 'hint': '查询原 operation_id，不重复提交或更换后端'}

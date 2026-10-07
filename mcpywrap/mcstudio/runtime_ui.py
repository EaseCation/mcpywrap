"""通过现有、按会话绑定的 Python 通道安装和调用 UI 控制层。"""
import base64
import hashlib
import io
import json
from pathlib import Path, PureWindowsPath
import uuid
import tokenize
import time
import zlib

from .runtime_debug import MAX_CODE


def compact_source(source):
    """删除注释以节省一次注入的空间，保留字符串内容、编码声明和行号。"""
    tokens = []
    for token in tokenize.tokenize(io.BytesIO(source).readline):
        if token.type == tokenize.COMMENT and token.start[0] != 1:
            token = token._replace(string='')
        tokens.append(token)
    return tokenize.untokenize(tokens)


def install_source(engine):
    source = (Path(__file__).with_name('runtime_ui_payload.py').read_bytes() + b'\n' +
              Path(__file__).with_name('runtime_ui_outline.py').read_bytes() + b'\n' +
              Path(__file__).parent.parent.joinpath('timeline.py').read_bytes() + b'\n' +
              Path(__file__).parent.parent.joinpath('input_plan.py').read_bytes().replace(b'from __future__ import unicode_literals', b'') + b'\n' +
              Path(__file__).parent.parent.joinpath('input_executor.py').read_bytes().replace(b'from __future__ import unicode_literals', b'') + b'\n' +
              Path(__file__).with_name('runtime_key_timeline_payload.py').read_bytes() + b'\n' +
              Path(__file__).with_name('runtime_player_payload.py').read_bytes() + b'\n' +
              Path(__file__).with_name('runtime_input_payload.py').read_bytes())
    digest = hashlib.sha256(source).hexdigest()
    encoded = base64.b64encode(zlib.compress(compact_source(source), 9)).decode('ascii')
    code = '''# coding: utf-8
import sys as _uisys, types as _uitypes, base64 as _uib64, zlib as _uiz
import mod.client.extraClientApi as _uiapi, gui as _uigui
_ui_old = globals().get('mcpy')
if _ui_old is not None and not getattr(_ui_old, '_mcpy_runtime', False):
    raise ValueError('全局 mcpy 已被其他脚本使用；请重命名该变量后安装')
_ui_module_name = '_mcpywrap_ui_runtime'
_ui_previous = _uisys.modules.get(_ui_module_name)
if (_ui_previous is not None and getattr(_ui_previous, 'source_hash', None) == %(digest)r
        and not _ui_previous.controller.closed and not _ui_previous.player.closed):
    _ui_module = _ui_previous
else:
    if _ui_previous is not None:
        _ui_previous.controller.close()
    # Python 2 回收旧 module 时会清空其 globals；已注册事件仍持有旧方法。
    # 必须在原 module 对象中更新，不能替换 sys.modules 后丢弃旧 module。
    _ui_module = _ui_previous if _ui_previous is not None else _uitypes.ModuleType(_ui_module_name)
    _uisys.modules[_ui_module_name] = _ui_module
    eval(compile(_uiz.decompress(_uib64.b64decode(%(encoded)r)), '<mcpy-ui>', 'exec'), _ui_module.__dict__)
    _ui_module.source_hash = %(digest)r
    _ui_module.controller = _ui_module.UIController(_uiapi, _uigui, %(engine)r)
    try:
        import localplayermodule as _uilp
    except ImportError:
        _uilp = None
    _ui_module.player = _ui_module.PlayerController(_ui_module.controller, _uilp)
    _ui_module.controller.player = _ui_module.player
    _ui_module.input = _ui_module.GameInputController(_ui_module.controller, _ui_module.player)
    _ui_module.controller.input = _ui_module.input
    try:
        _ui_module.attach_events(_ui_module.controller, _ui_module_name)
    except Exception:
        _ui_module.controller.close()
        raise
mcpy = _uitypes.ModuleType('mcpy')
mcpy._mcpy_runtime = True
mcpy.ui = _ui_module.controller
mcpy.player = _ui_module.player
mcpy.input = _ui_module.input
mcpy.api = _uiapi
_result = dict(mcpy.ui.capabilities(), source_hash=_ui_module.source_hash, alias='mcpy.ui',
               api_alias='mcpy.api', player_alias='mcpy.player', player_capabilities=mcpy.player.capabilities()['capabilities'],
               player_timeline=mcpy.player.capabilities()['timeline'], input_capabilities=mcpy.input.capabilities())
''' % {'digest': digest, 'encoded': encoded, 'engine': engine}
    return code


def install_sources(engine):
    """有界分段暂存，最后一段才安装；保持现有 32 KiB Python 传输契约。"""
    source = install_source(engine)
    if len(source.encode('utf-8')) <= MAX_CODE:
        return [source]
    # install_source 的编码参数只由本地源码生成，替换位置不涉及用户输入。
    start = source.index('_uib64.b64decode(') + len('_uib64.b64decode(')
    end = source.index(')', start)
    encoded = source[start:end][1:-1]
    name = '_mcpywrap_install_stage_' + uuid.uuid4().hex
    chunks = [encoded[index:index+24000] for index in range(0, len(encoded), 24000)]
    result = []
    for index, chunk in enumerate(chunks):
        initialize = '''
_stale = sorted(n for n in _stage_sys.modules if n.startswith('_mcpywrap_install_stage_'))
for _name in _stale[:-7]:
    _stage_sys.modules.pop(_name, None)
_stage = _stage_types.ModuleType(%r)
_stage.payload = ''
_stage_sys.modules[%r] = _stage
''' % (name, name) if index == 0 else ''
        result.append('''import sys as _stage_sys, types as _stage_types
%s
_stage_sys.modules[%r].payload += %r
_result = {'ok': True, 'stage': 'staged'}
''' % (initialize, name, chunk))
    source = source[:start] + '_ui_encoded' + source[end:]
    marker = 'import mod.client.extraClientApi as _uiapi, gui as _uigui'
    source = source.replace(marker, "_ui_encoded = _uisys.modules.pop(%r).payload\n" % name + marker, 1)
    result.append(source)
    if any(len(piece.encode('utf-8')) > MAX_CODE for piece in result):
        raise ValueError('UI 安装分段超过运行时传输上限')
    return result


def call_source(action, parameters, family='ui'):
    if family not in ('ui', 'player', 'input'):
        raise ValueError('未知运行时能力域')
    payload = json.dumps({'action': action, 'parameters': parameters, 'family': family}, ensure_ascii=True, allow_nan=False)
    encoded = base64.b64encode(payload.encode('ascii')).decode('ascii')
    # 参数只经过 JSON/Base64，不作为 Python 表达式插入，文本中可安全包含引号。
    return '''# coding: utf-8
import json as _uij, base64 as _uib
_ui_call = _uij.loads(_uib.b64decode(%r))
if globals().get('mcpy') is None or not getattr(mcpy, '_mcpy_runtime', False):
    _result = {'ok': False, 'code': 'not_installed', 'error': '请先执行 runtime install'}
else:
    _ui_controller = getattr(mcpy, _ui_call['family'], None)
    if _ui_controller is None:
        _result = {'ok': False, 'code': 'not_installed', 'error': '请重新执行 runtime install 更新控制层'}
    else:
        _result = _ui_controller.dispatch(_ui_call['action'], **_ui_call['parameters'])
''' % encoded


def execute(project, session, action, parameters=None, family='ui'):
    from ..command_context import remote_url
    from ..remote.client import Client
    from ..remote.service import identifier
    from . import sessions
    from .runtime_debug import control_request
    identifier(session)
    if family not in ('ui', 'player', 'input'):
        raise ValueError('未知运行时能力域')
    parameters = dict(parameters or {})
    mutation = (action in ('run', 'key') if family == 'input' else action in ('click', 'slide', 'scroll', 'set_control_value') if family=='ui' else
                action in ('move','look','look_at','select_slot','jump','sneak','key','attack','use_item','dig','eat','shoot','sequence','timeline'))
    if mutation:
        parameters.setdefault('request_id', uuid.uuid4().hex)
    endpoint = remote_url()
    client = Client(endpoint, project) if endpoint else None
    if client:
        client.require('py')
    if action == 'install':
        data = client.request('GET', '/sessions/' + session) if client else sessions.read(project, session)
        if data.get('state') != 'running' or not data.get('game'):
            raise ValueError('游戏会话尚未运行')
        engine = PureWindowsPath(data['game']['executable']).parent.name
        sources = install_sources(engine)
    else:
        sources = [call_source(action, parameters, family)]
    try:
        for index, source in enumerate(sources):
            response = (client.request('POST', '/sessions/' + session + '/py', {'code': source, 'side': 'client'})
                        if client else control_request(project, session, 'execute', code=source, side='client'))
            if index < len(sources)-1:
                # macOS 启动期可能返回排队请求；只查询原请求，不能重发源码或跳过暂存确认。
                deadline = time.monotonic()+12
                while (client is None and response.get('state') in ('queued', 'running') and
                       response.get('request_id') and time.monotonic() < deadline):
                    time.sleep(.1)
                    response = control_request(project, session, 'python-result', request_id=response['request_id'])
                value = response.get('value')
                if (response.get('state') != 'completed' or response.get('side') != 'client' or
                        not isinstance(value, dict) or not value.get('ok') or value.get('stage') != 'staged'):
                    return dict(response, ok=False, session=session, state='unknown',
                                error='安装源码暂存未确认；未提交后续安装阶段')
    except (ValueError, OSError) as exc:
        if mutation:
            if family == 'input':
                return {'ok': False, 'state': 'unknown', 'session': session, 'error': str(exc),
                        'operation_id': parameters['request_id'], 'request_id': parameters['request_id'],
                        'hint': '输入结果未知，用 runtime input status --operation 查询，不重发'}
            return {'ok': False, 'state': 'unknown', 'session': session, 'error': str(exc),
                    'operation': parameters['request_id'],
                    'hint': '结果未知，不要重复输入；用 runtime '+family+' status --operation 查询该动作'}
        raise
    context = {k: response[k] for k in ('endpoint', 'execution', 'remote_project', 'project') if k in response}
    context.update(session=session, runtime_state=response.get('state'), request_id=response.get('request_id'))
    if family == 'input':
        context.pop('request_id', None)
        context.pop('runtime_state', None)
        context['transport'] = {'state': response.get('state'), 'request_id': response.get('request_id')}
    if response.get('state') != 'completed' or response.get('side') != 'client':
        if family == 'input':
            return dict(context, ok=False, state='unknown', operation_id=parameters.get('request_id'),
                        request_id=parameters.get('request_id'), error=response.get('error') or '输入传输未确认',
                        hint='查询原 operation_id；传输请求编号保存在 transport，不重发动作')
        return dict(context, ok=False, state=response.get('state', 'unknown'),
                    error=response.get('error') or '执行端侧不匹配',
                    operation=parameters.get('request_id'),
                    hint='不要自动重试输入；连接未就绪时检查游戏加载及是否已被其他 Safaia 服务连接')
    value = response.get('value')
    if not isinstance(value, dict) or 'ok' not in value:
        return dict(context, ok=False, state='unknown', error='UI 控制层返回格式不兼容',
                    operation=parameters.get('request_id'))
    if action == 'install' and family == 'player':
        value = dict(value, capabilities=value.get('player_capabilities', {}),
                     timeline=value.get('player_timeline'), alias='mcpy.player')
    return dict(context, **value)

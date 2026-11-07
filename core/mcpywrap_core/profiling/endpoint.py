"""定位游戏内置 Tracy 端点并核对协议。

游戏只监听 127.0.0.1，从 8086 起顺延到 8105（多实例）。Tracy 同时只接受一个分析器连接；
握手成功会被视为一次短暂连接，随后断开，游戏回到等待状态。
"""
import socket
import struct

from ..engines.host import EngineError

HOST = '127.0.0.1'
PORTS = range(8086, 8106)
SHIBBOLETH = b'TracyPrf'
STATUS = {0: 'pending', 1: 'welcome', 2: 'protocol_mismatch', 3: 'not_available', 4: 'dropped'}
GAME_PREFIXES = ('mcpelauncher', 'minecraft.windows')
BUSY_HINT = 'Tracy 同时只接受一个连接；关闭已打开的分析器或正在进行的采集后重试。'


def handshake(port, protocol, timeout=2.0, host=HOST):
    """返回 welcome / protocol_mismatch / busy / closed 等状态；不读取分析数据。"""
    try:
        # Windows 对未监听的本机端口会重试 SYN 而非立即拒绝，连接阶段超时同样视为未监听
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError:
        return 'closed'
    try:
        with sock:
            sock.sendall(SHIBBOLETH + struct.pack('<I', protocol))
            reply = sock.recv(1)
    except socket.timeout:
        # 连接已建立但没有应答：游戏已有分析器连接，不再处理新的握手
        return 'busy'
    except OSError:
        return 'closed'
    return STATUS.get(reply[0], 'unknown') if reply else 'dropped'


def _connections(process):
    getter = getattr(process, 'net_connections', None) or process.connections
    return getter(kind='tcp')


def listening_ports(process):
    import psutil
    try:
        ports = {c.laddr.port for c in _connections(process)
                 if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port in PORTS}
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return []
    return sorted(ports)


def discover():
    """列出本机游戏进程的 Tracy 监听端口；只查询系统连接表，不建立连接。"""
    import psutil
    found = []
    for process in psutil.process_iter(['name', 'pid']):
        name = (process.info.get('name') or '').lower()
        if name.startswith(GAME_PREFIXES):
            for port in listening_ports(process):
                found.append({'pid': process.info['pid'], 'port': port, 'process': process.info.get('name')})
    return sorted(found, key=lambda item: item['port'])


def session_endpoint(project, session):
    from ..mcstudio import sessions
    from ..mcstudio.processes import checked_process
    try:
        data = sessions.read(project, session)
    except ValueError:
        from ..command_context import remote_url
        if remote_url():
            raise EngineError('本机没有该会话：' + session, 'session_unavailable',
                              '暂不支持远程会话的性能采集；请在 Windows 测试机本机运行 mcpy profile。') from None
        raise
    if data.get('state') not in ('starting', 'running') or not data.get('game'):
        raise EngineError('会话没有运行中的游戏进程', 'session_unavailable')
    process = checked_process(data['game'])
    if process is None:
        raise EngineError('会话的游戏进程已退出', 'session_unavailable')
    ports = listening_ports(process)
    if not ports:
        hint = '游戏启动后需要数秒才开始监听；稍后重试。'
        if data.get('backend') == 'macos-arm64':
            hint += 'macOS 需要运行包 0.4.7 及以上，旧实例请更新运行包后用 run --new 新建。'
        raise EngineError('游戏进程没有监听 Tracy 端口', 'profiler_unavailable', hint, session=session)
    return {'session': session, 'pid': process.pid, 'port': ports[0], 'backend': data.get('backend', 'windows')}


def resolve(project, protocol, session=None, port=None):
    """确定目标端口并用固定协议握手；协议不符时直接报错，不尝试其他版本。"""
    if session:
        target = session_endpoint(project, session)
    elif port:
        target = {'port': port}
    else:
        found = discover()
        if not found:
            raise EngineError('未发现监听 Tracy 的游戏进程', 'profiler_unavailable',
                              '先启动游戏（mcpy run），或用 --session / --port 指定目标。')
        if len(found) > 1:
            raise EngineError('发现多个游戏实例，请用 --session 或 --port 指定', 'ambiguous_target', endpoints=found)
        target = found[0]
    state = handshake(target['port'], protocol)
    if state == 'welcome':
        return dict(target, protocol=protocol)
    if state == 'protocol_mismatch':
        raise EngineError('游戏内置 Tracy 协议与固定版本（协议 %d）不一致' % protocol, 'protocol_mismatch',
                          '不要换用其他 Tracy 版本；请反馈游戏版本，等待 mcpywrap 更新固定的分析器版本。', port=target['port'])
    if state == 'busy':
        raise EngineError('Tracy 端口 %d 已有分析器连接' % target['port'], 'profiler_busy', BUSY_HINT, port=target['port'])
    raise EngineError('Tracy 端口 %d 不可用（%s）' % (target['port'], state), 'profiler_unavailable', port=target['port'])

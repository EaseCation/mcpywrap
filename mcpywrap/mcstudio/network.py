"""网络目标、可选 MCS 身份与前台运行；配置始终由本工具生成。"""
import codecs
import ipaddress
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import click

from ..dependencies import DependencyService, addon_directories, read_project
from .discovery import discover_engines, require_resources
from .game import open_game
from .mcs import is_windows
from .runtime_cppconfig import gen_runtime_config


@dataclass(frozen=True)
class ServerTarget:
    host: str
    port: int = 19132
    auth: str = 'none'

    def __post_init__(self):
        if not isinstance(self.host, str) or not self.host or self.host != self.host.strip():
            raise ValueError('server.host 必须是非空 IP 或主机名，不能包含首尾空白')
        try:
            ipaddress.ip_address(self.host)
        except ValueError:
            try:
                hostname = self.host.rstrip('.').encode('idna').decode('ascii')
            except UnicodeError as exc:
                raise ValueError('server.host 不是有效的主机名') from exc
            if len(hostname) > 253 or any(
                not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
                for label in hostname.split('.')
            ):
                raise ValueError('server.host 必须是 IP 或主机名；端口请单独配置')
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError('server.port 必须是 1–65535 的整数')
        if self.auth not in ('none', 'mcs'):
            raise ValueError('server.auth 只支持 none 或 mcs')


def configured_target(config):
    settings = config.get('tool', {}).get('mcpywrap', {})
    if 'server' not in settings:
        return None
    server = settings['server']
    if not isinstance(server, dict):
        raise ValueError('tool.mcpywrap.server 必须是 TOML 表')
    if 'auth' in server:
        raise ValueError('登录身份需要每次显式使用 --mcs-auth，请移除 server.auth 配置')
    unknown = server.keys() - {'host', 'port'}
    if unknown:
        raise ValueError('未知的 server 配置字段: ' + ', '.join(sorted(unknown)))
    return ServerTarget(server.get('host'), server.get('port', 19132))


def prepare_project(project_dir, config=None):
    """允许无根 Addon 的连接目录；出现包结构时仍严格校验。"""
    root = Path(project_dir)
    config = read_project(root) if config is None else config
    if config.get('tool', {}).get('mcpywrap', {}).get('project_type', 'addon') != 'addon':
        raise ValueError('网络运行暂时只支持 Addon 或纯连接目录，不支持 Map 项目')
    markers = {'level.dat', 'db', 'manifest.json', 'pack_manifest.json'}
    has_structure = any(p.name in markers or p.name.startswith(
        ('behavior_pack', 'BehaviorPack', 'resource_pack', 'ResourcePack')) for p in root.iterdir())
    folders = addon_directories(root) if has_structure else {}
    manager = DependencyService(root).resolve(config)
    from ..command_context import report_dependency_warnings
    report_dependency_warnings(manager)
    packs = list(manager.get_all_dependencies().values())
    if folders:
        pack = manager.root_node.addon_pack
        pack.behavior_pack_dir = folders.get('behavior')
        pack.resource_pack_dir = folders.get('resource')
        packs.append(pack)
    return packs


def unauthenticated_config(engine, target):
    """从本地模式的无身份默认值构造实验配置，不复制账号或伪造认证字段。"""
    config = gen_runtime_config(engine.version, '', '', engine.download_dir, '', [], [])
    config.update(world_info=None, client_type=1, render_engine=0,
                  misc={'multiplayer_game_type': 100})
    config['room_info'].update(ip=target.host, port=target.port)
    return config


def launch_network(engine, target, config_path, logging_port, auth_context=None):
    """由会话 worker 调用；监听、日志脱敏和进程回收由 worker 统一负责。"""
    require_resources(engine)
    config = unauthenticated_config(engine, target)
    if target.auth == 'mcs' and auth_context is None:
        raise ValueError('网络会话缺少本次请求的 MCS 身份，拒绝匿名回退')
    if auth_context:
        auth_context.apply(config)
        game_id = str(uuid.uuid4())
        config['misc']['game_id'] = game_id
        config['room_info']['item_ids'] = [game_id]
        config.update(vip_using_mod=[], isCloud=False, path=str(config_path))
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
    return open_game(str(config_path), engine=engine, logging_ip='127.0.0.1',
                     logging_port=logging_port, wait=False, use_system_color=False,
                     capture_output=True)


def prepare_network(target, project_dir=None, engine_overrides=None, interactive=None):
    """Preflight and optional identity acquisition, without terminal/UI output."""
    if not is_windows():
        raise ValueError('网络游戏启动仅支持 Windows')
    engine = discover_engines(project_dir, engine_overrides,
                              read_project_config=project_dir is not None).require_engine()
    require_resources(engine)
    identity = None
    if target.auth == 'mcs':
        from .mcs_auth import acquire_identity
        identity = acquire_identity() if interactive is None else acquire_identity(interactive=interactive)
    return engine, identity


def run_network(target, *, project_dir=None, packs=(), engine_overrides=None, detach=False):
    """预检后创建普通游戏会话；临时 connect 只用项目目录存会话，不读取其配置。"""
    from ..command_context import project_dir as current_project, json_output
    from . import sessions
    if json_output() and not detach:
        raise click.UsageError('网络运行 --json 需要 --detach；使用 status/logs/stop 管理返回的会话')
    engine, identity = prepare_network(target, project_dir, engine_overrides)
    click.echo('已提供 MCS 身份；仍需验证进服。' if identity else '未认证网络连接；服务器可能拒绝连接。')
    click.echo(f'本次仅连接服务器，工具未装配本地 Addon（已解析 {len(packs)} 个）。')
    root = Path(project_dir or current_project()).resolve()
    data = sessions.start(root, auth_context=identity,
                          network={'target': asdict(target), 'engine': asdict(engine)})
    result = sessions.handoff(data)
    if detach:
        return result
    click.echo(f"会话: {data['session']}；PID: {data['game']['pid']}（尚未确认连接）")
    click.echo(f"日志: {data['log_path']}\n引擎输出: {data['engine_log_path']}\nCtrl+C 结束本次游戏。")
    tails = []
    def relay(final=False):
        for stream, decoder in tails:
            click.echo(decoder.decode(stream.read(), final=final), nl=False)
    try:
        for key in ('log_path', 'engine_log_path'):
            path = Path(data[key])
            path.touch(exist_ok=True)
            tails.append((path.open('rb'), codecs.getincrementaldecoder('utf-8')(errors='replace')))
        while True:
            relay()
            final = sessions.read(root, data['session'])
            if final['state'] == 'failed':
                sessions.stop(root, data['session'])
            if final['state'] not in ('starting', 'running'):
                # read() may observe the game exiting just before the worker flushes logs.
                if final['state'] == 'exited' and 'exit_code' not in final:
                    time.sleep(0.2)
                    continue
                break
            time.sleep(0.2)
    except BaseException:
        sessions.stop(root, data['session'])
        raise
    finally:
        try:
            relay(final=True)
        finally:
            for stream, _ in tails:
                stream.close()
    if final['state'] == 'failed' or final.get('exit_code', 0):
        raise click.ClickException(final.get('error') or f"游戏退出码 {final['exit_code']}；日志: {data['log_path']}")
    result.update(state=final['state'], exit_code=final.get('exit_code', 0))
    return result

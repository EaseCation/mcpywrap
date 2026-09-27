"""网络目标、可选 MCS 身份与前台运行；配置始终由本工具生成。"""
import codecs
import ipaddress
import json
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import click

from ..dependencies import DependencyService, addon_directories, read_project
from .discovery import discover_engines, require_resources
from .file_logs import FileLogServer
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


def run_network(target, *, project_dir=None, packs=(), engine_overrides=None):
    """共用调度入口；packs 留待网络装配支持，本版只报告数量，不挂载。"""
    if not is_windows():
        raise ValueError('网络游戏启动仅支持 Windows')
    engine = discover_engines(project_dir, engine_overrides,
                              read_project_config=project_dir is not None).require_engine()
    require_resources(engine)
    config = unauthenticated_config(engine, target)
    identity = None
    secrets = []
    if target.auth == 'mcs':
        from .mcs_auth import acquire_identity
        identity = acquire_identity()
        identity.apply(config)
        # Match MCS's generated ID relationship for third-party servers without a numeric game ID.
        game_id = str(uuid.uuid4())
        config['misc']['game_id'] = game_id
        config['room_info']['item_ids'] = [game_id]
        config.update(vip_using_mod=[], isCloud=False)
        secrets = identity.secrets()
        click.echo('已读取 MCS 当前身份；连接结果仍以服务器响应为准。')
    else:
        click.echo('未认证网络连接：不使用账号/token，服务器可能拒绝连接。')
    click.echo(f'本次仅连接服务器，工具未装配本地 Addon（已解析 {len(packs)} 个）。')
    directory = Path(tempfile.mkdtemp(prefix='mcpy-network-'))
    config_path, log_path = directory / 'runtime.cppconfig', directory / 'game.log'
    engine_log = directory / 'engine.log'
    process, receiver, engine_capture = None, None, None
    tails = []

    def relay(final=False):
        for tail, decoder in tails:
            click.echo(decoder.decode(tail.read(), final=final), nl=False)

    try:
        if identity:
            config['path'] = str(config_path)
        config_path.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
        if identity:
            from .private_logs import RedactedDecoder, EngineLogCapture
            receiver = FileLogServer(log_path, decoder_factory=lambda: RedactedDecoder(secrets))
        else:
            receiver = FileLogServer(log_path)
        receiver.start()
        engine_log.touch()
        for path in (log_path, engine_log):
            tails.append((path.open('rb'), codecs.getincrementaldecoder('utf-8')(errors='replace')))
        click.echo(f'目标: {target.host}:{target.port}\n日志: {log_path}\n引擎输出: {engine_log}')
        process = open_game(str(config_path), engine=engine, logging_ip='127.0.0.1',
                            logging_port=receiver.port, wait=False, use_system_color=False,
                            **({'capture_output': True} if identity else {'output_path': str(engine_log)}))
        if not process:
            raise click.ClickException(f'游戏启动失败；日志目录: {directory}')
        if identity:
            engine_capture = EngineLogCapture(process.stdout, engine_log, secrets)
        click.echo(f'游戏进程已创建，PID: {process.pid}（尚未确认连接）；Ctrl+C 结束本次游戏。')
        while True:
            relay()
            try:
                code = process.wait(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        try:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        finally:
            try:
                try:
                    if engine_capture:
                        engine_capture.close()
                finally:
                    if receiver:
                        receiver.close()
                relay(final=True)
            finally:
                for tail, _ in tails:
                    tail.close()
                config_path.unlink(missing_ok=True)
    if code:
        error = click.ClickException(f'游戏退出码 {code}；日志: {log_path}；引擎输出: {engine_log}')
        error.exit_code = code if 0 < code < 256 else 1
        raise error
    return {'application': 'game', 'pid': process.pid, 'state': 'exited', 'exit_code': code,
            'authenticated': False, 'connection_verified': False, 'addons_assembled': False,
            'identity_source': target.auth, 'identity_provided': identity is not None,
            'host': target.host, 'port': target.port, 'log_path': str(log_path),
            'engine_log_path': str(engine_log), 'engine_version': engine.version}

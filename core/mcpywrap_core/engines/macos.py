"""macOS Addon backend. Reuses project builders, sessions and the shipped launcher helper."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

import click
from .host import EngineError, require_macos
from .backend import GameBackend, LaunchedGame
from . import install
from ..mcstudio.launcher_control import LauncherProcessMismatch


def instances(project):
    root = Path(project)/'.runtime/macos/instances'
    found = []
    for path in root.glob('*/instance.json'):
        item = install.read_json(path)
        from ..runtime.storage import read
        meta = read(Path(project)/'.runtime/instances'/(item['level_id'] + '.json'), {})
        saved = (path.parent/'data/minecraftWorlds'/item['level_id']/'level.dat').is_file()
        item['state'] = ('ready' if meta.get('last_ready_at') else 'legacy_existing' if saved and not meta
                         else meta.get('state', 'unverified'))
        item['config_path'] = str(path.with_name('world.cppconfig'))
        if Path(item['config_path']).is_file():
            from ..mcstudio.runtime_cppconfig import read_cppconfig
            item['name'] = read_cppconfig(item['config_path'])['world_info']['name']
        found.append(item)
    return sorted(found, key=lambda x: x['created_at'], reverse=True)


def active_session(project, level_id):
    from ..mcstudio import sessions
    from ..runtime import occupancy
    for record in occupancy.active(project):
        if record.get('backend') == 'macos-arm64' and record.get('level_id') == level_id:
            data = sessions.read(project, record['session'])
            if data['state'] in ('starting', 'running'):
                return data
            raise EngineError('旧会话尚未正常退出。', 'recovery_required',
                              '先 stop --session ' + data['session'] + '，确认退出后再启动。')
    return None


def _match(items, prefix):
    matches = [item for item in items if item['level_id'].startswith(prefix)]
    if len(matches) != 1:
        raise EngineError('实例 ID 前缀不存在或不唯一：' + prefix, 'instance_not_found')
    return matches[0]


def ensure_runtime():
    state = install.diagnose()
    if state['ok']:
        return state
    raise EngineError('macOS 本地运行资源尚未就绪。', 'setup_required',
                      '先执行 mcpy engine install --catalog <发布目录> [--apk <本地 APK>]，再重试 run。',
                      setup=state, next_commands=['mcpy engine doctor --json', 'mcpy engine install --help'])


def pinned_runtime(item):
    plan = item['installation']
    app = install.home()/'runtimes'/plan['runtime_id']/'McpyRuntime.app'
    game = install.home()/'engines'/plan['profile']['apk']['sha256']/'game'
    meta = install.verify_runtime(app, app.parent/'McpyRuntime.integrity.json', plan['profile'])
    if install._version(require_macos()['macos_version']) < install._version(meta['minimum_macos']):
        raise EngineError('当前系统低于此实例的最低 macOS 要求', 'os_too_old')
    install.verify_game(game, plan['profile'])
    compatibility = install.preflight_runtime(app, game, plan['profile'], meta, plan['runtime_id'])
    from .macos_icons import optional_runtime_application
    application = optional_runtime_application(app, game)
    return {'runtime': str(app), 'application': str(application), 'game': str(game), 'profile': plan['profile'], 'runtime_id': plan['runtime_id'],
            'compat_report': compatibility, 'cppconfig_protocol': meta.get('cppconfig_protocol'),
            'network_connect_protocol': meta.get('network_connect_protocol'),
            'developer_identity_protocol': meta.get('developer_identity_protocol')}


def run(project, *, new=False, listing=False, delete=None, clean_all=False, force=False,
        instance_prefix=None, detach=False, mcs_auth=False, overrides=None, world_config=None):
    require_macos()
    from ..dependencies import read_project
    from ..command_context import json_output, human_interaction
    from ..mcstudio import sessions
    from ..utils.locks import directory_lock
    from ..mcstudio.runtime_cppconfig import creation_settings
    if world_config is not None:
        if not new or instance_prefix or listing or delete or clean_all:
            raise EngineError('自定义世界配置仅用于新建实例', 'invalid_world_options')
        creation_settings(world_config)
    overrides = overrides or {}
    if mcs_auth or overrides.get('game_executable_path') or overrides.get('mcs_download_path'):
        raise EngineError('MC Studio 身份、EXE 和下载目录参数仅适用于 Windows。', 'unsupported_option',
                          'macOS 当前使用开发者 APK 的离线模式；资源由 mcpy engine 管理。')
    config = read_project(project)
    if not (listing or delete or clean_all):
        from ..mcstudio.network import configured_target, prepare_project
        target = configured_target(config)
        if target is not None:
            if new or instance_prefix or world_config is not None:
                raise click.UsageError('网络模式不支持 --new 或本地世界实例 ID')
            packs = prepare_project(project, config)
            from .macos_network import connect
            return connect(target, project_dir=project, packs=packs, engine_overrides=overrides, detach=detach)
    if config.get('tool', {}).get('mcpywrap', {}).get('project_type', 'addon') != 'addon':
        raise EngineError('macOS 首版支持 Addon 测试，Map 项目尚未接入。', 'unsupported_feature',
                          '地图项目请在 Windows 本机运行。')
    items = instances(project)
    if listing:
        return {'backend': 'macos-arm64', 'instances': items}
    if delete or clean_all:
        targets = [_match(items, delete)] if delete else items
        if not force:
            if not human_interaction() or not click.confirm('永久删除所选测试实例及其世界？', default=False):
                raise click.Abort()
        for item in targets:
            if active_session(project, item['level_id']):
                raise EngineError('实例正在运行，请先 stop。', 'busy')
        for item in targets:
            directory = Path(item['config_path']).parent
            if directory.is_symlink() or directory.parent != Path(project)/'.runtime/macos/instances':
                raise EngineError('实例路径无效', 'instance_invalid')
            shutil.rmtree(directory)
        return {'deleted': [item['level_id'] for item in targets], 'backend': 'macos-arm64'}
    if json_output() and not detach:
        raise click.UsageError('run --json 需要 --detach；通过 status/logs/stop 管理会话')
    with directory_lock(Path(project)/'.runtime/macos'):
        items = instances(project)
        available = [item for item in items if item['state'] in ('ready', 'legacy_existing')]
        if items and not new and not instance_prefix and not available:
            raise EngineError('没有成功进入过世界的可用实例。', 'instance_not_ready',
                              '使用 run ' + items[0]['level_id'] + ' 重试，或 --new 新建。')
        item = _match(items, instance_prefix) if instance_prefix else (available[0] if available and not new else None)
        if item:
            current = active_session(project, item['level_id'])
            if current:
                from ..runtime.deployment import matches_source
                if current['state'] == 'starting':
                    current = sessions.wait_started(project, current['session'])
                if overrides.get('engine_version') and overrides['engine_version'] != current['launch']['engine_version']:
                    raise EngineError('已有会话的引擎与请求不同。', 'session_conflict')
                return dict(sessions.handoff(current), already_running=True,
                            source_matches=matches_source(project, current),
                            hint='已复用运行中的实例；未执行预处理，修改 Mod 后请先 stop，再 run 以重新部署。')
            state = item['installation']
        else:
            state = ensure_runtime()
        with directory_lock(install.home()/'install-lock'):
            state = pinned_runtime({'installation': state})
            version = state['profile']['apk']['version']
            requested = overrides.get('engine_version') or config.get('tool', {}).get('mcpywrap', {}).get('macos', {}).get('engine_version')
            if requested and requested != version:
                raise EngineError('当前实例／资源固定为 ' + version, 'engine_version_mismatch',
                                  '选择匹配的运行包；旧实例不自动升级，需要升级时显式 --new。')
            supports_config = state.get('cppconfig_protocol') == 1
            if not supports_config and world_config is not None:
                raise EngineError('此运行包尚不支持 cppconfig 世界设置。', 'runtime_incompatible',
                                  '安装支持 cppconfig_protocol=1 的运行包，并创建新实例。')
            if item is None:
                identity = uuid.uuid4().hex
                directory = Path(project)/'.runtime/macos/instances'/identity
                directory.mkdir(parents=True)
                item = {'level_id': identity, 'name': config.get('project', {}).get('name', '开发测试'),
                        'created_at': time.time(), 'backend': 'macos-arm64',
                        'installation': {'runtime_id': state['runtime_id'], 'profile': state['profile']},
                        'config_path': str(directory/'world.cppconfig')}
                install.write_json(directory/'instance.json', {k: v for k, v in item.items() if k != 'config_path'})
            directory = Path(item['config_path']).parent
            plan = {'runtime': state['runtime'], 'game': state['game'], 'data': str(directory/'data'),
                    'application': state.get('application'),
                    'cache': str(directory/'cache'), 'engine_version': version,
                    'compat_report': state.get('compat_report'),
                    'prepare_world': {'supports_config': supports_config, 'name': item['name'],
                                      'settings': world_config, 'package': config.get('project', {}).get('name', 'project')}}
            config_path = directory/('world.cppconfig' if supports_config else 'instance.json')
            from ..runtime import instances as records
            records.attempt(project, dict(item, creation_time=item['created_at']), None, world_config)
            if world_config is None and not config_path.exists():
                from ..runtime.storage import read
                plan['prepare_world']['settings'] = read(records.record_path(project, item['level_id']), {}).get('creation_settings')
            data = sessions.start(project, str(config_path), item['level_id'],
                                  backend='macos-arm64', launch=plan)
    result = sessions.handoff(data)
    if detach: return result
    sessions.show_configuration(result)
    from .tui import watch_session
    return watch_session(project, data['session'])


def launch_session(data):
    plan = data['launch']
    if data.get('mode') == 'network':
        from types import SimpleNamespace
        from ..mcstudio.network import ServerTarget, unauthenticated_config
        config = unauthenticated_config(
            SimpleNamespace(version=plan['engine_version'], download_dir=plan['game']),
            ServerTarget(**data['network']['target']), data['network'].get('player'))
        install.write_json(Path(plan['cppconfig']), config)
    app = Path(plan['runtime'])
    helper = app/'Contents/Resources/launcher/run_netease_dev.py'
    if not helper.is_file():
        raise EngineError('运行包缺少启动适配器，请重新安装。', 'runtime_incompatible')
    display_app = plan.get('application') or app
    command = [sys.executable, str(helper), '--runtime', str(display_app), '--game-dir', plan['game'],
               '--data-dir', plan['data'], '--cache-dir', plan['cache'], '--angle-backend', 'metal',
               '--debug-loopback', '--exec-client', '--log', data['engine_log_path']]
    if plan.get('cppconfig'):
        command += ['--cppconfig', plan['cppconfig']]
    else:
        command += ['--world-id', plan['world_id'], '--world-name', plan['world_name'], '--source-addon', plan['packs']]
    if plan.get('compat_report'):
        command += ['--compat-report', plan['compat_report']]
    metadata = install.read_json(app/'Contents/Resources/runtime.json')
    if metadata.get('addon_link_protocol') == 1:
        command.append('--link-source-addons')
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, start_new_session=True)
    from ..mcstudio.processes import identity
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            error = process.stderr.read(8192).decode('utf-8', 'replace')
            raise EngineError('启动器准备失败：' + error, 'launch_failed')
        if Path(identity(process.pid)['executable']).name == 'mcpelauncher-client':
            return process
        time.sleep(.05)
    process.terminate()
    raise EngineError('启动器交接超时；已请求取消。', 'launch_timeout')


class MacOSBackend(GameBackend):
    id = 'macos-arm64'
    label = 'macOS · Apple Silicon · Metal'
    capabilities = ('local-worlds', 'macos-local-worlds', 'engine-install', 'macos-engine-install',
                    'status', 'logs', 'stop', 'py', 'runtime', 'runtime-ui', 'runtime-player',
                    'client-python-requests', 'project-ui', 'reload', 'watch', 'network-sessions')
    managed_install = True
    setup_description = ('在 Apple Silicon Mac 上运行本地 Addon 测试。\n'
                         '首次运行会自动下载原生启动器和网易开发者版资源，并在本机完成安装。\n'
                         '需下载约 2.3 GB，请预留至少 7 GB 可用空间。')

    def world_option_restrictions(self):
        return {'cheat_info.' + key: reason for key, reason in (
            ('experimental_holiday', '此后端尚未验证实验玩法配置。'),
            ('experimental_biomes', '此后端尚未验证实验玩法配置。'),
            ('fancy_bubbles', '此后端暂不支持此画面选项。'))}

    def run(self, project, **options):
        from ..mcstudio.runtime_cppconfig import creation_settings
        settings = creation_settings(options.get('world_config'))
        for field, reason in self.world_option_restrictions().items():
            group, key = field.split('.')
            if settings.get(group, {}).get(key):
                raise EngineError(reason, 'unsupported_world_option', field=field)
        options.pop('no_gui', None)
        return run(project, **options)

    def connect(self, target, **options):
        from .macos_network import connect
        return connect(target, **options)

    def prepare_guest(self, host):
        raise EngineError('当前 macOS 运行包尚未完成本地卡片加入适配，未启动联调组。',
                          'local_join_unavailable',
                          '单客户端和已支持的外部服务器连接仍可使用；需要具备本地菜单联机能力的运行包。')

    def watch_directory(self, project, data):
        return Path(data['config_path']).parent/'assembled'

    def instances(self, project):
        return [dict(item, creation_time=item['created_at']) for item in instances(project)]

    def deploy(self, project, data):
        from ..runtime.deployment import refresh
        pack = refresh(project, data)
        self.sync_runtime_packs(data, pack)

    def sync_runtime_packs(self, data, pack):
        # Older native runtimes copy packs instead of linking them. Preserve
        # that protocol while publishing files through one guarded entry point.
        for kind in ('behavior', 'resource'):
            source = Path(getattr(pack, kind + '_pack_dir'))
            if not source.is_dir(): continue
            from ..mcstudio.deployment_links import pack_uuid
            identity = pack_uuid(source)
            target = Path(data['launch']['data'])/'games/com.netease'/(kind + '_packs')/('dev_' + identity)
            if not target.is_dir():
                raise EngineError('包标识或运行包发生变化，请重新运行。', 'restart_required')
            if target.is_symlink():
                if target.resolve() != source.resolve():
                    raise EngineError('运行包链接发生变化，请重新运行。', 'restart_required')
                continue
            from ..runtime.deployment import inventory
            before, after = inventory(target), inventory(source)
            for name, digest in after.items():
                if name.endswith('/'):
                    (target/name).mkdir(parents=True, exist_ok=True)
                elif before.get(name) != digest:
                    dest = target/name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    temporary = dest.with_name('.mcpy-' + uuid.uuid4().hex)
                    try:
                        shutil.copy2(source/name, temporary); temporary.replace(dest)
                    finally:
                        temporary.unlink(missing_ok=True)
            for name in before.keys() - after.keys():
                if not name.endswith('/'): (target/name).unlink()

    def reload_restriction(self, data, kind):
        launch = data.get('launch') or {}
        if kind == 'ui':
            runtime = launch.get('runtime')
            try:
                metadata = install.read_json(Path(runtime)/'Contents/Resources/runtime.json') if runtime else {}
            except (OSError, ValueError):
                metadata = {}
            if metadata.get('json_ui_reload_protocol') != 1:
                return '此实例固定的运行包不支持 JSON UI 热更；可重新部署并重载世界，或安装新版运行包后启动新实例。'
            if (metadata.get('game_compatibility') or {}).get('elf_rules_schema') == 1:
                try:
                    report = install.read_json(launch['compat_report'])
                except (OSError, ValueError, KeyError, TypeError):
                    report = {}
                if not isinstance(report.get('ui'), dict):
                    return '此引擎的 JSON UI 接口未通过结构识别；请重新部署并重载世界，或反馈兼容性诊断。'
            return None
        # A new APK version does not establish support for unverified Metal APIs.
        return {
            'material': '当前材质热更包装接口缺失，底层入口尚未验证可用；请重新部署并重载世界。',
            'shader': '当前 Metal 运行路径尚未验证 Shader 热更；暂不调用动态重编译，请重新部署并重载世界。',
        }.get(kind)

    def ui_reload_code(self):
        return """try:
    import _mcpy_launcher
except ImportError:
    _result = {'ok': False, 'unsupported': True}
else:
    _reload_ui = getattr(_mcpy_launcher, 'reload_ui', None)
    _result = {'ok': bool(_reload_ui())} if callable(_reload_ui) else {'ok': False, 'unsupported': True}
"""

    def diagnose(self, project=None, overrides=None, mcs_auth=False, check_files=False):
        data = install.diagnose(check_files=check_files)
        if mcs_auth:
            data.update(ok=False, state='unsupported_option',
                        hint='macOS 当前使用离线开发模式。')
            data['mcs_auth'] = {'component_available': False, 'error': 'MC Studio 身份仅适用于 Windows'}
        return data

    def install(self, catalog=None, apk=None, progress=None):
        return install.install(catalog, apk, progress)

    def check_updates(self):
        from .official import check_updates
        return check_updates()

    def installation_choice(self):
        cat, _ = install.catalog()
        return cat['runtime']['id'] + ' / ' + cat['profile']['apk']['version']

    def launch(self, data, receiver, auth_context=None):
        from .preferences import NativePreferences
        if data.get('mode') == 'local':
            self.preferences = NativePreferences(data['project'], data['launch']['data'],
                                                 install.home()/'preferences/macos').prepare()
            from ..runtime.native import launch_world
            return launch_world(data, launch_session)
        from contextlib import ExitStack
        from ..mcstudio import sessions
        guard = ExitStack()
        try:
            if data.get('group'):
                from ..runtime.profiles import PlayerProfile
                profile = PlayerProfile(data)
                guard.enter_context(profile.lease())
                profile.prepare()
            self.preferences = NativePreferences(data['project'], data['launch']['data'],
                                                 install.home()/'preferences/macos').prepare()
            sessions.require_launch_requested(data['project'], data['session'])
            data['phase'] = 'prepared'
            sessions.save(sessions.session_path(data['project'], data['session'])/'session.json', data)
            return LaunchedGame(launch_session(data), capture_output=False, guard=guard)
        except BaseException:
            guard.close()
            raise

    def finish(self, data):
        if getattr(self, 'preferences', None):
            self.preferences.sync(force=True)

    def debug_channel(self, data, write_log):
        from ..mcstudio.launcher_python import LauncherPythonChannel
        from ..mcstudio.runtime_debug import SafaiaChannel
        # Safaia connects before server Python can accept commands. Client
        # startup requests still use the launcher's independent ready queue.
        data['world_ready'] = False
        safaia = SafaiaChannel(write_log, ready=lambda: data.get('world_ready') is True)
        return LauncherPythonChannel(safaia, data['launch']['data'])

    def refresh(self, data, channel):
        if getattr(self, 'preferences', None):
            try:
                self.preferences.sync()
            except (OSError, ValueError) as error:
                # A transient preferences error must not terminate the world.
                message = str(error)
                if message != getattr(self, '_preference_error', None):
                    print('偏好同步失败，将在保存退出时重试：' + message, file=sys.stderr, flush=True)
                self._preference_error = message
        if data.get('world_ready'): return False
        now = time.monotonic()
        if now < getattr(self, '_next_probe', 0): return False
        self._next_probe = now + 1
        if not hasattr(self, '_control_wait_started'):
            self._control_wait_started = now
        # Requests are queued by the runtime; a missing ID before registration is
        # not a startup failure. Server Python still uses the original Safaia channel.
        try:
            commands = install.read_json(Path(data['engine_log_path']).with_name('commands.json'))
            completed = True
            for index in range(len(commands)):
                request_id = 'startup-' + str(index)
                result = channel._rpc('result', {'request_id': request_id})
                self._control_seen = True
                matched = result.get('request_id') == request_id
                state = result.get('state') if matched else None
                if state in ('failed', 'cancelled'):
                    # Runtime 0.4.5 starts every startup deadline at enqueue.
                    # Its final read-only level probe may expire behind a slow
                    # successful world load. HUD remains our readiness proof;
                    # never replay or ignore failure of a preceding operation.
                    readiness_probe = commands[index] == {
                        'module_name': 'clientlevel', 'func_name': 'get_level_id',
                        'args': [], 'use_instance': False,
                        'wait_for': "__import__('clientlevel').get_level_id() not in (None, -1, '-1')"}
                    if (data.get('mode') == 'local' and completed and index == len(commands) - 1
                            and readiness_probe and state == 'failed'
                            and result.get('error') == 'Request expired before execution'):
                        if not hasattr(self, '_hud_wait_started'):
                            self._hud_wait_started = now
                            print('世界启动操作已完成，继续等待进入游戏（最长 15 分钟）。', file=sys.stderr, flush=True)
                        continue
                    raise EngineError(('服务器连接未完成：' if data.get('mode') == 'network' else '世界启动步骤失败：')
                                      + request_id + '：' + str(result.get('error', state)),
                                      'connection_failed' if data.get('mode') == 'network' else 'world_start_failed')
                completed = completed and state == 'completed'
        except LauncherProcessMismatch:
            # A retained world's metadata may still name its previous process
            # until the new launcher publishes its socket. Never send to it.
            if getattr(self, '_control_seen', False):
                raise
            if now - self._control_wait_started >= 90:
                raise EngineError('90 秒内启动器未发布当前游戏进程的控制记录。',
                                  'launcher_control_timeout',
                                  '保留 worker.log、engine.log 和控制记录，检查启动器初始化；不要手动删除控制文件。')
            return False
        except (OSError, ConnectionError):
            pass
        try:
            with open(data['engine_log_path'], 'rb') as stream:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - 65536))
                if b'"top_screen":"hud_screen"' in stream.read():
                    data['world_ready'] = True
                    if data.get('mode') == 'network': data['connection_verified'] = True
                    return True
        except OSError:
            pass
        if hasattr(self, '_hud_wait_started') and now - self._hud_wait_started >= 900:
            raise EngineError('世界加载在额外等待 15 分钟后仍未进入游戏。', 'world_start_timeout',
                              '请检查引擎日志和加载界面；本次未重放启动步骤，原世界与日志保留。')
        if data.get('mode') == 'network' and time.time() - data['created_at'] > 90:
            raise EngineError('90 秒内未进入服务器；请检查地址、端口、协议版本以及服务器是否允许无认证的中国版客户端。',
                              'connection_timeout')
        return False

    def handoff(self, data):
        return dict(super().handoff(data), engine_version=data['launch']['engine_version'],
                    instance=data['level_id'], client_python_transport='launcher-jni',
                    world_ready=data.get('world_ready', False))

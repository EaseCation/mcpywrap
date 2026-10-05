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


def instances(project):
    root = Path(project)/'.runtime/macos/instances'
    found = []
    for path in root.glob('*/instance.json'):
        item = install.read_json(path)
        item['config_path'] = str(path.with_name('world.cppconfig'))
        if Path(item['config_path']).is_file():
            from ..mcstudio.runtime_cppconfig import read_cppconfig
            item['name'] = read_cppconfig(item['config_path'])['world_info']['name']
        found.append(item)
    return sorted(found, key=lambda x: x['created_at'], reverse=True)


def active_session(project, level_id):
    from ..mcstudio import sessions
    for path in (Path(project)/'.runtime/sessions').glob('*/session.json'):
        data = sessions.read(project, path.parent.name)
        if data.get('backend') == 'macos-arm64' and data.get('level_id') == level_id:
            if data['state'] in ('starting', 'running'):
                return data
            from ..mcstudio.processes import checked_process
            if data.get('game') and checked_process(data['game']):
                raise EngineError('旧会话进程尚未退出。', 'busy', '先 stop --session ' + data['session'] + '，确认退出后再启动。')
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
    return {'runtime': str(app), 'game': str(game), 'profile': plan['profile'], 'runtime_id': plan['runtime_id'],
            'compat_report': compatibility, 'cppconfig_protocol': meta.get('cppconfig_protocol')}


def run(project, *, new=False, listing=False, delete=None, clean_all=False, force=False,
        instance_prefix=None, detach=False, mcs_auth=False, overrides=None, world_config=None):
    require_macos()
    from ..dependencies import read_project
    from ..command_context import json_output, human_interaction
    from ..mcstudio import sessions
    from ..remote.service import directory_lock
    from ..mcstudio.runtime_cppconfig import prepare_cppconfig, creation_settings, saved_world_settings
    if world_config is not None:
        if not new or instance_prefix or listing or delete or clean_all:
            raise EngineError('自定义世界配置仅用于新建实例', 'invalid_world_options')
        creation_settings(world_config)
    overrides = overrides or {}
    if mcs_auth or overrides.get('game_executable_path') or overrides.get('mcs_download_path'):
        raise EngineError('MC Studio 身份、EXE 和下载目录参数仅适用于 Windows。', 'unsupported_option',
                          'macOS 当前使用开发者 APK 的离线模式；资源由 mcpy engine 管理。')
    config = read_project(project)
    if config.get('tool', {}).get('mcpywrap', {}).get('server'):
        raise EngineError('macOS 本地后端当前只支持离线世界。', 'unsupported_feature',
                          '连接服务器请配置 --remote <Windows 服务地址>。')
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
    from ..builders.project_builder import AddonProjectBuilder
    with directory_lock(Path(project)/'.runtime/macos'):
        items = instances(project)
        item = _match(items, instance_prefix) if instance_prefix else (items[0] if items and not new else None)
        if item:
            current = active_session(project, item['level_id'])
            if current:
                return dict(sessions.handoff(current), already_running=True,
                            hint='已复用运行中的实例；修改 Mod 后请先 stop，再 run 以重新部署。')
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
            builder = AddonProjectBuilder(project, directory/'assembled')
            success, error = builder.build()
            if not success:
                raise EngineError(error, 'build_failed')
            # Normalize the builder's configured pack directory names for the existing
            # launcher helper; no second dependency resolver or Mod entry generator.
            import tempfile
            stage = Path(tempfile.mkdtemp(prefix='.packs-', dir=directory))
            try:
                for kind in ('behavior', 'resource'):
                    pack = Path(getattr(builder.target_addon, kind + '_pack_dir'))
                    if pack.is_dir(): (stage/(kind + '_pack')).symlink_to(pack.resolve(), target_is_directory=True)
                if (directory/'packs').exists(): shutil.rmtree(directory/'packs')
                stage.rename(directory/'packs')
            finally:
                if stage.exists(): shutil.rmtree(stage)
            plan = {'runtime': state['runtime'], 'game': state['game'], 'data': str(directory/'data'),
                    'cache': str(directory/'cache'), 'engine_version': version,
                    'compat_report': state.get('compat_report')}
            config_path = Path(item['config_path'])
            if supports_config:
                legacy = None
                if not config_path.exists() and world_config is None and (directory/'data').exists():
                    # Migrate the actual saved world, not today's tool defaults.
                    legacy = {'world_info': saved_world_settings(directory/'data/minecraftWorlds'/item['level_id']/'level.dat')}
                prepare_cppconfig(config_path, version, item['name'], item['level_id'], '',
                    config.get('project', {}).get('name', 'project'),
                    [str(directory/'packs/behavior_pack')] if (directory/'packs/behavior_pack').is_dir() else [],
                    [str(directory/'packs/resource_pack')] if (directory/'packs/resource_pack').is_dir() else [],
                    world_config if world_config is not None else legacy)
                plan['cppconfig'] = str(config_path)
            else:
                # Existing immutable runtimes still use the previous launch protocol.
                # Never pretend they can apply edited cppconfig settings.
                if config_path.exists():
                    raise EngineError('此运行包不能读取 cppconfig，请安装新版并新建实例。', 'runtime_incompatible')
                plan.update(packs=str(directory/'packs'), world_id=item['level_id'], world_name=item['name'])
                config_path = directory/'instance.json'
            data = sessions.start(project, str(config_path), item['level_id'],
                                  backend='macos-arm64', launch=plan)
    result = sessions.handoff(data)
    if detach: return result
    from .tui import watch_session
    return watch_session(project, data['session'])


def launch_session(data):
    plan = data['launch']
    app = Path(plan['runtime'])
    helper = app/'Contents/Resources/launcher/run_netease_dev.py'
    if not helper.is_file():
        raise EngineError('运行包缺少启动适配器，请重新安装。', 'runtime_incompatible')
    command = [sys.executable, str(helper), '--runtime', str(app), '--game-dir', plan['game'],
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
                    'client-python-requests', 'project-ui', 'reload', 'watch')
    managed_install = True
    setup_description = ('原生 Apple Silicon / Metal；离线 Addon 测试；世界设置由各实例 cppconfig 保存。\n'
                         '启动器从配置的发布源取得，开发者 APK 直接从网易下载。\n'
                         '首次下载 APK 约 2.21 GB，展开约 3.88 GB；无需 Homebrew、Wine 或 MC Studio。')

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

    def watch_directory(self, project, data):
        return Path(data['config_path']).parent/'assembled'

    def instances(self, project):
        return [dict(item, creation_time=item['created_at']) for item in instances(project)]

    def deploy(self, project, data):
        from ..builders.project_builder import AddonProjectBuilder
        from ..remote.service import directory_lock
        directory = Path(data['config_path']).parent
        with directory_lock(directory/'deploy-lock'):
            builder = AddonProjectBuilder(project, directory/'assembled')
            success, error = builder.build()
            if not success: raise EngineError(error, 'build_failed')
            for kind in ('behavior', 'resource'):
                source = Path(getattr(builder.target_addon, kind + '_pack_dir'))
                if not source.is_dir(): continue
                identity = str(uuid.UUID(install.read_json(source/'manifest.json')['header']['uuid']))
                target = Path(data['launch']['data'])/'games/com.netease'/(kind + '_packs')/('dev_' + identity)
                if not target.is_dir():
                    raise EngineError('包标识已变化，请保存退出后重新运行。', 'restart_required')
                if target.is_symlink():
                    if target.resolve() != source.resolve():
                        raise EngineError('运行包链接与组装目录不匹配，请重新运行实例。', 'restart_required')
                    continue
                # Compatibility for older runtimes: atomically update their copied packs.
                wanted = set()
                for path in source.rglob('*'):
                    if not path.is_file(): continue
                    relative = path.relative_to(source); wanted.add(relative)
                    dest = target/relative
                    if dest.is_file() and dest.read_bytes() == path.read_bytes(): continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    temporary = dest.with_name('.mcpy-' + uuid.uuid4().hex)
                    try:
                        shutil.copy2(path, temporary); temporary.replace(dest)
                    finally:
                        temporary.unlink(missing_ok=True)
                for path in target.rglob('*'):
                    if path.is_file() and path.relative_to(target) not in wanted: path.unlink()

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

    def installation_choice(self):
        cat, _ = install.catalog()
        return cat['runtime']['id'] + ' / ' + cat['profile']['apk']['version']

    def launch(self, data, receiver, auth_context=None):
        return LaunchedGame(launch_session(data), capture_output=False)

    def debug_channel(self, data, write_log):
        from ..mcstudio.launcher_python import LauncherPythonChannel
        return LauncherPythonChannel(super().debug_channel(data, write_log), data['launch']['data'])

    def refresh(self, data, channel):
        if data.get('world_ready'): return False
        now = time.monotonic()
        if now < getattr(self, '_next_probe', 0): return False
        self._next_probe = now + 1
        # Requests are queued by the runtime; a missing ID before registration is
        # not a startup failure. Server Python still uses the original Safaia channel.
        try:
            commands = install.read_json(Path(data['engine_log_path']).with_name('commands.json'))
            for index in range(len(commands)):
                request_id = 'startup-' + str(index)
                result = channel._rpc('result', {'request_id': request_id})
                if result.get('request_id') == request_id and result.get('state') in ('failed', 'cancelled'):
                    raise EngineError('世界启动步骤失败：' + str(result.get('error', result['state'])), 'world_start_failed')
        except (OSError, ConnectionError):
            pass
        try:
            with open(data['engine_log_path'], 'rb') as stream:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - 65536))
                if b'"top_screen":"hud_screen"' in stream.read():
                    data['world_ready'] = True
                    return True
        except OSError:
            pass
        return False

    def handoff(self, data):
        return dict(super().handoff(data), engine_version=data['launch']['engine_version'],
                    instance=data['level_id'], client_python_transport='launcher-jni',
                    world_ready=data.get('world_ready', False))

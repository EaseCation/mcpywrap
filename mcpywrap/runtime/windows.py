"""Windows local lifecycle; command and Qt callers share this entry point."""
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
import uuid

import click

from . import instances, occupancy, storage
from .deployment import Deployment, matches_source, reference
from ..dependencies import read_project
from ..engines.backend import LaunchedGame
from ..engines.host import EngineError
from ..mcstudio import sessions
from ..mcstudio.discovery import discover_engines, require_resources, Engine
from ..mcstudio.runtime_cppconfig import compose_cppconfig, write_cppconfig, for_saved_world
from ..utils.locks import directory_lock


def run(project, *, new=False, listing=False, delete=None, force=False, clean_all=False,
        instance_prefix=None, no_gui=False, detach=False, mcs_auth=False, overrides=None,
        auth_context=None, world_config=None):
    project = Path(project).resolve()
    config = read_project(project)
    if listing:
        return {'instances': instances.list_instances(project)}
    if delete or clean_all:
        with directory_lock(project/'.runtime/lifecycle-lock'):
            items = instances.list_instances(project)
            targets = [instances.match(items, delete)] if delete else items
            if not force and not click.confirm('永久删除所选世界？', default=False):
                raise click.Abort()
            return instances.delete(project, targets)
    from ..mcstudio.network import configured_target, prepare_project, run_network
    target = configured_target(config)
    if target:
        from dataclasses import replace
        if new or instance_prefix or world_config is not None:
            raise click.UsageError('网络模式不支持 --new 或世界实例 ID')
        return run_network(replace(target, auth='mcs') if mcs_auth else target, project_dir=project,
                           packs=prepare_project(project, config), engine_overrides=overrides, detach=detach)
    from ..command_context import json_output
    if json_output() and not detach:
        raise click.UsageError('run --json 需要 --detach')
    if config.get('tool', {}).get('mcpywrap', {}).get('project_type', 'addon') == 'addon':
        from ..dependencies import addon_directories
        # Reject an invalid local project before asking for an account or
        # starting a worker. Dependency resolution still belongs to deployment.
        addon_directories(project)
    with directory_lock(project/'.runtime/lifecycle-lock'):
        item = instances.select(project, new=new, prefix=instance_prefix,
                                name=config.get('project', {}).get('name', '开发测试'))
        current = next((r for r in occupancy.active(project) if r.get('mode') == 'local'
                        and r.get('level_id') == item['level_id']), None)
        if current:
            current = sessions.read(project, current['session'])
            if current['state'] == 'starting':
                current = sessions.wait_started(project, current['session'])
            if current['state'] != 'running':
                raise EngineError('原会话未正常结束，不能将其作为可用游戏复用。', 'recovery_required',
                                  '先执行 stop --session ' + current['session'] + '，确认退出后重新运行。',
                                  session=current['session'])
            requested = {k: v for k, v in (overrides or {}).items() if v is not None}
            selected_engine = (current.get('launch') or {}).get('engine', {})
            engine_fields = {'engine_version': 'version', 'game_executable_path': 'executable', 'mcs_download_path': 'download_dir'}
            def matches_override(key, value):
                selected = selected_engine.get(engine_fields.get(key)) or current.get('engine_overrides', {}).get(key)
                if key in ('game_executable_path', 'mcs_download_path'):
                    return bool(selected) and occupancy.path_key(selected) == occupancy.path_key(value)
                return selected == value
            if (mcs_auth != bool(current.get('mcs_auth')) or
                    any(not matches_override(k, v) for k, v in requested.items())):
                raise EngineError('已有会话的引擎或登录方式与请求不同。', 'session_conflict')
            result = dict(sessions.handoff(current), already_running=True)
            result['source_matches'] = matches_source(project, current)
            result['hint'] = '已复用运行中的世界；本次未重新准备或部署素材。应用素材修改请重启会话，或 stop 后重新 run。'
            return result
        recipe = storage.read(item['config_path'], {})
        engine = discover_engines(project, overrides, recipe.get('version')).require_engine()
        require_resources(engine)
        if mcs_auth and auth_context is None:
            from ..mcstudio.mcs_auth import acquire_identity
            auth_context = acquire_identity()
        session = uuid.uuid4().hex
        instances.attempt(project, item, session, world_config)
        settings = storage.read(instances.record_path(project, item['level_id']), {}).get('creation_settings')
        data = sessions.start(project, item['config_path'], item['level_id'], overrides,
                              auth_context=auth_context, session_id=session,
                              launch={'engine': asdict(engine), 'world_settings': settings})
    result = sessions.handoff(data)
    if detach:
        return result
    sessions.show_configuration(result)
    from ..engines.tui import watch_session
    return watch_session(project, data['session'])


def launch(data, receiver, auth_context=None):
    from ..mcstudio.game import open_game
    from ..mcstudio.mcs import get_mcs_game_engine_netease_data_path
    project = Path(data['project'])
    config = read_project(project)
    if 'server' in config.get('tool', {}).get('mcpywrap', {}):
        raise EngineError('服务器目标不能通过本地世界 worker 启动。', 'invalid_target')
    directory = sessions.session_path(project, data['session'])
    config_path = Path(data['config_path'])
    world = instances.world_path(project, data['level_id'])
    guard = ExitStack()
    deployment = Deployment(project)
    process = None
    script_guard = ExitStack()
    try:
        from ..project_scripts import project_lock, startup_hooks
        script_guard.enter_context(project_lock(data['project']))
        guard.enter_context(instances.world_lock(world, data))
        plan = data.get('launch') or {}
        engine = (Engine(**plan['engine']) if plan.get('engine') else
                  discover_engines(project, data.get('engine_overrides'), storage.read(config_path, {}).get('version')).require_engine())
        require_resources(engine)
        with deployment.lock():
            startup_hooks(data, deployment)
            pack = deployment.prepare(session=data['session'])
            data['warnings'] = deployment.warnings
            deployment.begin_launch()
            data['deployment'] = reference(deployment.record)
            data['phase'] = 'prepared'
            sessions.save(directory/'session.json', data)
            global_root = get_mcs_game_engine_netease_data_path() or str(world.parent.parent/'games/com.netease')
            packs = pack if isinstance(pack, list) else [pack]
            links = deployment.publish_links(global_root, packs, data['session'])
            if isinstance(pack, list):
                from ..builders.MapPack import MapPack
                world.mkdir(parents=True, exist_ok=True)
                MapPack('map', str(project)).copy_level_data_to(str(world))
            package_name = config.get('project', {}).get('name', 'project')
            recipe = compose_cppconfig(config_path, engine.version, config.get('project', {}).get('name', '开发测试'),
                                       data['level_id'], engine.download_dir, package_name,
                                       links['behavior'], links['resource'],
                                       plan.get('world_settings') if not config_path.exists() else None)
            deployment.publish_config(config_path, recipe)
            runtime = for_saved_world(recipe, world/'level.dat')
            data['world_name'] = runtime['world_info']['name']
            launch_path = directory/('auth.cppconfig' if auth_context else 'runtime.cppconfig')
            if auth_context:
                auth_context.apply(runtime)
            else:
                # Explicit offline developer identity, as used by ModPC's
                # local test configuration. This is not an authenticated ID.
                runtime['player_info'] = {'urs': '', 'user_id': 0,
                                          'user_name': 'mcpy_' + data['session'][:8]}
            write_cppconfig(launch_path, runtime)
            sessions.require_launch_requested(project, data['session'])
            deployment.spawning()
            process = open_game(str(launch_path), logging_port=receiver.port, wait=False,
                                engine=engine, capture_output=True, use_system_color=False)
            if not process:
                raise EngineError('引擎未创建游戏进程。', 'launch_failed')
            deployment.spawned(process)
        return LaunchedGame(process, deployment=deployment, guard=guard)
    except BaseException:
        if not process or process.poll() is not None:
            with deployment.lock():
                deployment.rollback()
        guard.close()
        raise
    finally:
        script_guard.close()

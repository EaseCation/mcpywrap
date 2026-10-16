"""Prepare an isolated native world inside its worker, using the shared deployment."""
from contextlib import ExitStack
from pathlib import Path

from . import instances
from .deployment import Deployment, reference
from ..engines.backend import LaunchedGame
from ..engines.host import EngineError
from ..mcstudio.runtime_cppconfig import compose_cppconfig, saved_world_settings
from ..mcstudio import sessions


def launch_world(data, launcher):
    plan = data['launch']
    directory = Path(data['config_path']).parent
    target = directory/'assembled'
    deployment = Deployment(data['project'], target)
    guard = ExitStack()
    process = None
    world = Path(plan['data'])/'minecraftWorlds'/data['level_id']
    try:
        guard.enter_context(instances.world_lock(world, data))
        with deployment.lock():
            pack = deployment.prepare(session=data['session'])
            data['warnings'] = deployment.warnings
            deployment.begin_launch()
            data['deployment'] = reference(deployment.record)
            options = plan.get('prepare_world', {})
            name = options.get('name', '开发测试')
            if options.get('supports_config', bool(plan.get('cppconfig'))):
                path = directory/'world.cppconfig'
                settings = options.get('settings')
                if settings is None and not path.exists() and world.exists():
                    settings = {'world_info': saved_world_settings(world/'level.dat')}
                recipe = compose_cppconfig(path, plan['engine_version'], name, data['level_id'], '',
                    options.get('package', pack.pkg_name),
                    [pack.behavior_pack_dir] if Path(pack.behavior_pack_dir).is_dir() else [],
                    [pack.resource_pack_dir] if Path(pack.resource_pack_dir).is_dir() else [],
                    settings if not path.exists() else None)
                deployment.publish_config(path, recipe)
                plan['cppconfig'] = str(path)
            else:
                if (directory/'world.cppconfig').exists():
                    raise EngineError('此旧运行包不能读取 cppconfig。', 'runtime_incompatible')
                plan.update(packs=str(target), world_id=data['level_id'], world_name=name)
            data['phase'] = 'prepared'
            sessions.save(sessions.session_path(data['project'], data['session'])/'session.json', data)
            sessions.require_launch_requested(data['project'], data['session'])
            deployment.spawning()
            process = launcher(data)
            deployment.spawned(process)
        return LaunchedGame(process, capture_output=False, deployment=deployment, guard=guard)
    except BaseException:
        if not process or process.poll() is not None:
            with deployment.lock():
                deployment.rollback()
        guard.close()
        raise

"""Test adapters for the deployment service, never a second production startup path."""
from mcpywrap.runtime.deployment import Deployment


def launch_world(project, config_path, level_id, overrides=None, auth_context=None):
    """Exercise the real worker launch service with only process start mocked by callers."""
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import patch
    import uuid
    from mcpywrap.runtime.windows import launch
    from mcpywrap.mcstudio.sessions import session_path
    from test_local_dependencies import addon
    project = Path(project)
    if not (project/'behavior_pack').exists():
        addon(project.parent, project.name)
    session = uuid.uuid4().hex
    directory = session_path(project, session)
    directory.mkdir(parents=True)
    data = {'session': session, 'project': str(project), 'config_path': str(config_path),
            'level_id': level_id, 'engine_overrides': overrides or {}, 'state': 'starting',
            'mode': 'local', 'backend': 'windows', 'game': None, 'worker': None,
            'log_path': str(directory/'game.log'), 'engine_log_path': str(directory/'engine.log')}
    with patch('mcpywrap.runtime.windows.instances.world_path', return_value=project/'.test-worlds'/level_id), \
         patch('mcpywrap.mcstudio.mcs.get_mcs_game_engine_netease_data_path', return_value=str(project/'.test-global')):
        result = launch(data, SimpleNamespace(port=12345), auth_context)
    if result.deployment:
        with result.deployment.lock():
            result.deployment.commit()
    if result.guard:
        # This adapter mocks the process launch and completes its fake session.
        # Leave the same terminal record a real worker would persist.
        from mcpywrap.mcstudio.sessions import save
        data.update(state='exited', game=None, worker=None)
        save(directory/'session.json', data)
        result.guard.close()
    return result


def prepare_packs(name, project, raise_errors=False, report=None):
    try:
        deployment = Deployment(project)
        with deployment.lock():
            result = deployment.prepare()
            deployment.commit()
        return result if isinstance(result, list) else [result]
    except (ValueError, OSError):
        if raise_errors:
            raise
        return None

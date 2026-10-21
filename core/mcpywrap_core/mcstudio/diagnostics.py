"""Read-only diagnostics shared by the CLI and HTTP service."""
from .discovery import discover_engines, resource_issues, studio_installation


def diagnose(project=None, overrides=None, mcs_auth=False, read_project_config=True):
    result = discover_engines(project, overrides=overrides, read_project_config=read_project_config)
    data = result.to_dict()
    data['resources'] = {'run': [], 'editor': [], 'safaia': []}
    if result.selected:
        data['resources']['run'] = resource_issues(result.selected)
        data['resources']['editor'] = resource_issues(result.selected, 'editor')
    for purpose in ('editor', 'safaia'):
        _, issues = studio_installation(purpose)
        data['resources'][purpose].extend(issues)
    data['ok'] = bool(result.selected and not result.error and not data['resources']['run'])
    if mcs_auth:
        from ..mcstudio.bridge_assets import inspect_bridge
        data['mcs_auth'] = inspect_bridge()
        if not data['mcs_auth']['component_available']:
            data.update(ok=False, error=data['mcs_auth']['error'], hint=data['mcs_auth']['hint'])
    return data

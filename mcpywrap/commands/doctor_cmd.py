"""不创建项目、不启动程序的本机诊断。"""
import click
from ..command_context import OperationCommand, project_dir as current_project, non_interactive, require_project

from ..mcstudio.discovery import (
    discover_engines, engine_options, resource_issues, studio_installation,
)


@click.command(cls=OperationCommand)
@engine_options
def doctor_cmd(**overrides):
    """诊断游戏发现和运行资源（只读，无需初始化项目）"""
    result = discover_engines(current_project(), overrides=overrides)
    data = result.to_dict()
    data['resources'] = {'run': [], 'editor': [], 'safaia': []}
    if result.selected:
        data['resources']['run'] = resource_issues(result.selected)
        data['resources']['editor'] = resource_issues(result.selected, 'editor')
    for purpose in ('editor', 'safaia'):
        _, issues = studio_installation(purpose)
        data['resources'][purpose].extend(issues)
    data['ok'] = bool(result.selected and not result.error and not data['resources']['run'])
    from ..command_context import json_output
    if not json_output():
        for candidate in result.candidates:
            click.echo(f'候选 [{candidate.source}] {candidate.version}: {candidate.executable}')
        for issue in result.diagnostics:
            click.echo(f'{issue["path"]}: {issue["message"]}')
        for kind, issues in data['resources'].items():
            for issue in issues:
                click.echo(f'资源 [{kind}]: {issue}')
    return data

"""不创建项目、不启动程序的本机诊断。"""
import json

import click

from ..mcstudio.discovery import (
    discover_engines, engine_options, resource_issues, studio_installation,
)


@click.command()
@engine_options
@click.option('--json', 'json_output', is_flag=True, help='输出可解析的 JSON')
def doctor_cmd(json_output, **overrides):
    """诊断游戏发现和运行资源（只读，无需初始化项目）"""
    result = discover_engines(overrides=overrides)
    data = result.to_dict()
    data['resources'] = {'run': [], 'editor': [], 'safaia': []}
    if result.selected:
        data['resources']['run'] = resource_issues(result.selected)
        data['resources']['editor'] = resource_issues(result.selected, 'editor')
    for purpose in ('editor', 'safaia'):
        _, issues = studio_installation(purpose)
        data['resources'][purpose].extend(issues)
    data['ok'] = bool(result.selected and not result.error and not data['resources']['run'])
    if json_output:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        if result.selected:
            click.echo(f'选中: {result.selected.version} [{result.selected.source}] {result.selected.executable}')
        for candidate in result.candidates:
            click.echo(f'候选: {candidate.version} [{candidate.source}] {candidate.executable}')
        for issue in result.diagnostics:
            click.echo(f'诊断 [{issue["source"]}] {issue["path"]}: {issue["message"]}')
        if result.error:
            click.echo(f'错误: {result.error}')
        for purpose, issues in data['resources'].items():
            for issue in issues:
                click.echo(f'资源 [{purpose}]: {issue}')
        click.echo('游戏启动资源就绪' if data['ok'] else '游戏发现或运行资源检查失败')
    if not data['ok']:
        raise click.exceptions.Exit(1)

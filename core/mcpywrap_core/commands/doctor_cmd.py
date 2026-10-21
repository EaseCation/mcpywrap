"""不创建项目、不启动程序的本机诊断。"""
import click
from ..command_context import OperationCommand, project_dir as current_project
from ..mcstudio.discovery import engine_options


@click.command(cls=OperationCommand)
@engine_options
@click.option('--mcs-auth', is_flag=True, help='同时只读检查登录组件；不读取身份或安装证书')
@click.option('--capabilities', is_flag=True, help='报告本机或远端能力，不启动游戏')
def doctor_cmd(mcs_auth=False, capabilities=False, **overrides):
    """诊断游戏发现和运行资源（只读，无需初始化项目）"""
    if capabilities:
        from ..remote.service import capabilities as inspect_capabilities
        return inspect_capabilities()
    from ..engines.backend import get_backend
    data = get_backend().diagnose(current_project(), overrides, mcs_auth, check_files=True)
    from ..command_context import json_output
    if not json_output():
        click.echo('本地运行: ' + data['state'])
        if data.get('hint'): click.echo(data['hint'])
        for candidate in data.get('candidates', []):
            click.echo(f"候选 [{candidate['source']}] {candidate['version']}: {candidate['executable']}")
        for issue in data.get('diagnostics', []):
            click.echo(f'{issue["path"]}: {issue["message"]}')
        for kind, issues in data.get('resources', {}).items():
            for issue in issues:
                click.echo(f'资源 [{kind}]: {issue}')
        if mcs_auth and data.get('mcs_auth'):
            click.echo('登录组件: ' + ('文件齐全，尚未验证登录和系统策略' if data['mcs_auth']['component_available']
                                     else data['mcs_auth']['error']))
    return data

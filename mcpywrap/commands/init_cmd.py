"""初始化项目：向导与显式参数使用同一服务。"""
import click
from ..command_context import OperationCommand, project_dir, non_interactive, report_dependency_warnings
from ..project_init import initialize_project, detect_project
from ..dependencies import DependencyService
from .dependency_prompt import prompt_dependency


@click.command(cls=OperationCommand)
@click.option('--name')
@click.option('--type', 'project_type', type=click.Choice(['addon', 'map']))
@click.option('--version', default='0.1.0', show_default=True)
@click.option('--target-dir', default='./build', show_default=True)
def init_cmd(name, project_type, version, target_dir):
    """初始化配置与目录，不自动安装项目、依赖或 SDK。"""
    if non_interactive() or name or project_type:
        if not project_type:
            if not detect_project(project_dir()):
                raise click.UsageError('请指定 --type addon 或 --type map')
        return initialize_project(project_dir(), name, project_type, version, target_dir)
    return init()


def init():
    if non_interactive():
        raise click.UsageError('请使用 init --name <名称> --type addon|map')
    name = click.prompt('项目名称', default=project_dir().name)
    version = click.prompt('项目版本', default='0.1.0')
    kind = click.prompt('项目类型', type=click.Choice(['addon', 'map']), default='addon')
    target = click.prompt('构建输出目录', default='./build')
    result = initialize_project(project_dir(), name, kind, version, target)
    service = DependencyService(project_dir())
    while click.confirm('是否添加依赖？', default=False):
        entry = prompt_dependency()
        if entry.kind == 'local':
            service.add_local(entry.value)
        else:
            service.add_package(entry.value)
        report_dependency_warnings(service.last_resolution)
    click.echo('项目已初始化；使用 mod 生成脚本、modsdk 安装 SDK、sync --install 安装项目。')
    return result

"""CLI presentation for the shared build operation."""
import click
from ..command_context import OperationCommand, project_dir, require_project
from ..api import Core
from ..operations.build import build


@click.command(cls=OperationCommand)
@click.option('--merge', '-m', is_flag=True, help='强制合并所有资源文件')
def build_cmd(merge):
    """构建为 MCStudio 工程"""
    require_project()
    result = Core().execute('build', project_dir(), merge=merge)
    from ..dependency_feedback import report_selection
    report_selection(result.get('dependency_selection'))
    click.secho('✅ 构建成功！项目已生成到目标目录。', fg='green')
    return result

"""CLI presentation for the shared package operation."""
import click
from ..command_context import OperationCommand, project_dir, require_project
from ..api import Core
# Compatibility imports for callers of the historical helpers.
from ..operations.package import _package_manifests, _zip_dir_keep_empty, AddonProjectBuilder, MapProjectBuilder


@click.command(cls=OperationCommand)
@click.option('--merge', '-m', is_flag=True, help='强制合并所有资源文件（仅地图项目）')
def package_cmd(merge):
    """组装 Addon/地图并生成分发 ZIP；游戏兼容性需实际测试。"""
    require_project()
    result = Core().execute('package', project_dir(), merge=merge)
    click.secho('✅ 打包成功！分发文件路径: ' + result['artifact'], fg='green')
    return result

"""安装指定 ModSDK 或列出可用版本。"""
import click
from ..command_context import OperationCommand, non_interactive
from ..minecraft.netease_modsdk import get_available_versions, download_and_install_package


@click.command(cls=OperationCommand)
@click.option('--list', 'list_versions', is_flag=True)
@click.option('--version', help='安装指定版本')
@click.option('--latest', is_flag=True, help='显式选择最新版本')
def modsdk_cmd(list_versions, version, latest):
    """管理网易 ModSDK；非交互必须指定操作。"""
    if sum((list_versions, bool(version), latest)) > 1:
        raise click.UsageError('--list、--version、--latest 不能同时使用')
    if not any((list_versions, version, latest)) and non_interactive():
        raise click.UsageError('请指定 --list、--version 或 --latest')
    versions = get_available_versions()
    if not versions:
        raise click.ClickException('无法获取 ModSDK 版本，请检查网络')
    if list_versions:
        return {'versions': versions}
    if not version:
        version = versions[-1] if latest else click.prompt('SDK 版本', type=click.Choice(versions), default=versions[-1])
    if not download_and_install_package(version, force=True):
        raise click.ClickException('ModSDK 安装失败，请检查网络和安装器输出')
    return {'version': version}

"""安装指定 ModSDK 或列出可用版本。"""
import click
from ..command_context import OperationCommand, non_interactive
from ..minecraft.netease_modsdk import get_available_versions, download_and_install_package


@click.command(cls=OperationCommand)
@click.option('--list', 'list_versions', is_flag=True)
@click.option('--version', help='安装指定版本')
@click.option('--latest', is_flag=True, help='显式选择最新版本')
@click.option('--inspect', 'inspect_only', is_flag=True, help='只读检查目标 Python 与已安装补全库，无网络')
@click.option('--python', 'python_path', type=click.Path(dir_okay=False), help='开发环境 Python 可执行文件绝对路径，不解析虚拟环境链接')
@click.option('--expected-environment', help='安装前后核验 --inspect 返回的环境 identity')
def modsdk_cmd(list_versions, version, latest, inspect_only, python_path, expected_environment):
    """管理开发环境 ModSDK 补全库；--python 定向安装，不安装到游戏。"""
    from ..minecraft.modsdk_environment import inspect_environment, install_environment
    if inspect_only:
        if list_versions or version or latest or expected_environment:
            raise click.UsageError('--inspect 不能与安装/版本列表选项同时使用')
        import sys
        return inspect_environment(python_path or sys.executable)
    if expected_environment and not python_path:
        raise click.UsageError('--expected-environment 必须与 --python 一起使用')
    if list_versions and (python_path or expected_environment):
        raise click.UsageError('--list 不接受目标 Python')
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
    if python_path:
        return install_environment(version, python_path, expected_environment)
    if not download_and_install_package(version, force=True):
        raise click.ClickException('ModSDK 安装失败，请检查网络和安装器输出')
    return {'version': version}

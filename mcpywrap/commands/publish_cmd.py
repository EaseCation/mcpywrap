"""通过标准 Python 构建协议发布本次生成的分发文件。"""
import subprocess
import sys
import tempfile
from pathlib import Path
import click
from ..command_context import OperationCommand, project_dir, non_interactive, require_project
from ..dependencies import read_project


def check_credentials():
    """复用 Twine 的环境变量、配置文件与非交互认证规则。"""
    import argparse
    from twine.settings import Settings
    parser = argparse.ArgumentParser(add_help=False)
    Settings.register_argparse_arguments(parser)
    settings = Settings.from_argparse(parser.parse_args(['--non-interactive']))
    try:
        if not settings.client_cert and not (settings.username and settings.password):
            raise ValueError('未配置认证信息')
    except Exception as exc:
        raise click.ClickException('发布凭据不可用；请配置 Twine 环境变量、.pypirc 或受支持的凭据提供者') from exc


@click.command(cls=OperationCommand)
@click.option('--yes', is_flag=True, help='明确确认上传本次构建的文件到 PyPI')
def publish_cmd(yes):
    """构建并发布 Python 包到 PyPI。凭据使用 Twine 标准配置。"""
    require_project()
    if not yes:
        if non_interactive():
            raise click.UsageError('发布需要显式指定 --yes；请先配置 Twine 凭据')
        if not click.confirm('确认构建并上传到 PyPI？', default=False):
            raise click.Abort()
    config = read_project(project_dir())
    if not config.get('project', {}).get('name'):
        raise click.ClickException('缺少 project.name')
    check_credentials()
    with tempfile.TemporaryDirectory(prefix='mcpy-publish-') as directory:
        proc = subprocess.run([sys.executable, '-m', 'build', '--outdir', directory, str(project_dir())],
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if proc.returncode:
            raise click.ClickException(proc.stderr or proc.stdout or '构建失败')
        files = sorted(str(p) for p in Path(directory).iterdir() if p.suffix == '.whl' or p.name.endswith('.tar.gz'))
        if not files:
            raise click.ClickException('构建未生成 wheel 或 sdist')
        proc = subprocess.run([sys.executable, '-m', 'twine', 'upload', '--non-interactive', *files],
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if proc.returncode:
            raise click.ClickException(proc.stderr or proc.stdout or '上传失败，请检查 Twine 凭据')
    return {'name': config['project']['name'], 'version': config['project'].get('version'), 'published': True}

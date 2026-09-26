"""添加 Python 包或本地 Addon 目录依赖。"""
import os
from pathlib import Path
import click
from ..dependencies import DependencyDeclaration, DependencyError, DependencyService
from .dependency_prompt import prompt_dependency, require_interactive


@click.command()
@click.argument('package', required=False)
@click.option('--path', 'local_path', help='直接引用本地 Addon 根目录，不安装目录')
def add_cmd(package, local_path):
    """添加依赖；不带参数时进入类型选择向导。"""
    if package is not None and local_path is not None:
        raise click.UsageError('包名与 --path 不能同时使用')
    if not (Path.cwd() / 'pyproject.toml').exists():
        raise click.ClickException('项目尚未初始化，请先运行 mcpy init')
    try:
        if package is None and local_path is None:
            require_interactive()
            entry = prompt_dependency()
        else:
            entry = DependencyDeclaration('local' if local_path is not None else 'package', local_path if local_path is not None else package)
        service = DependencyService(os.getcwd())
        if entry.kind == 'local':
            changed, warnings = service.add_local(entry.value)
            for warning in warnings:
                click.secho(warning, fg='yellow')
        else:
            click.echo(f'正在安装 {entry.value}...')
            changed = service.add_package(entry.value)
        click.secho('依赖已添加' if changed else '依赖已存在', fg='green')
    except (DependencyError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc

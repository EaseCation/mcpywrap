"""移除依赖声明；本地目录永不卸载或删除。"""
import os
import subprocess
import sys
from pathlib import Path
import click
from packaging.requirements import Requirement, InvalidRequirement
from packaging.utils import canonicalize_name
from ..dependencies import DependencyDeclaration, DependencyError, DependencyService
from .dependency_prompt import require_interactive


@click.command()
@click.argument('package', required=False)
@click.option('--path', 'local_path', help='移除本地目录引用，保留源目录')
@click.option('--uninstall', '-u', is_flag=True, help='同时卸载 Python 包')
def remove_cmd(package, local_path, uninstall):
    """移除直接依赖；不带参数时从列表选择。"""
    if package is not None and local_path is not None:
        raise click.UsageError('包名与 --path 不能同时使用')
    if not (Path.cwd() / 'pyproject.toml').exists():
        raise click.ClickException('项目尚未初始化，请先运行 mcpy init')
    service = DependencyService(os.getcwd())
    try:
        if package is None and local_path is None:
            require_interactive()
            entries = service.list()
            if not entries:
                raise DependencyError('项目没有直接依赖')
            for index, item in enumerate(entries, 1):
                click.echo(f'{index}. [{"本地" if item.kind == "local" else "包"}] {item.value}')
            entry = entries[click.prompt('选择要移除的依赖', type=click.IntRange(1, len(entries))) - 1]
        else:
            entry = DependencyDeclaration('local' if local_path is not None else 'package', local_path if local_path is not None else package)
        if entry.kind == 'local' and uninstall:
            raise click.UsageError('本地依赖不支持 --uninstall；移除引用不会删除源目录')
        if entry.kind == 'package' and entry not in service.list():
            matches = [item for item in service.list() if item.kind == 'package' and canonicalize_name(Requirement(item.value).name) == canonicalize_name(package)]
            if len(matches) == 1:
                entry = matches[0]
        service.remove(entry)
        if uninstall:
            subprocess.run([sys.executable, '-m', 'pip', 'uninstall', '-y', Requirement(entry.value).name], check=True)
        click.secho('依赖引用已移除，源目录保留' if entry.kind == 'local' else '依赖已移除', fg='green')
    except (DependencyError, InvalidRequirement, OSError, subprocess.CalledProcessError) as exc:
        raise click.ClickException(str(exc)) from exc

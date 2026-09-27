"""移除依赖声明；本地目录永不卸载或删除。"""
import os
import subprocess
import sys
from pathlib import Path
import click
from ..command_context import OperationCommand, project_dir as current_project, non_interactive, require_project
from packaging.requirements import Requirement, InvalidRequirement
from packaging.utils import canonicalize_name
from ..dependencies import DependencyDeclaration, DependencyError, DependencyService
from .dependency_prompt import require_interactive


@click.command(cls=OperationCommand)
@click.argument('package', required=False)
@click.option('--path', 'local_path', help='移除本地目录引用，保留源目录')
@click.option('--uninstall', '-u', is_flag=True, help='同时卸载 Python 包')
@click.option('--library', help='移除代码库声明；保留缓存和手写入口')
@click.option('--git', 'git_name', help='移除指定名称的Git项目依赖，保留缓存与入口')
def remove_cmd(package, local_path, uninstall, library, git_name):
    """移除直接依赖；不带参数时从列表选择。"""
    if sum((package is not None, local_path is not None, library is not None, git_name is not None)) > 1:
        raise click.UsageError('包名、--path、--library 不能同时使用')
    if not (current_project() / 'pyproject.toml').exists():
        raise click.ClickException('项目尚未初始化，请先运行 mcpy init')
    service = DependencyService(str(current_project()))
    try:
        if git_name is not None:
            entry = DependencyDeclaration('git', git_name)
        elif library is not None:
            entry = DependencyDeclaration('code', library)
        elif package is None and local_path is None:
            require_interactive()
            entries = service.list()
            if not entries:
                raise DependencyError('项目没有直接依赖')
            for index, item in enumerate(entries, 1):
                label = {'local': '本地', 'package': '包', 'code': '代码库', 'git': 'Git项目'}[item.kind]
                click.echo(f'{index}. [{label}] {item.value}')
            entry = entries[click.prompt('选择要移除的依赖', type=click.IntRange(1, len(entries))) - 1]
        else:
            entry = DependencyDeclaration('local' if local_path is not None else 'package', local_path if local_path is not None else package)
        if entry.kind != 'package' and uninstall:
            raise click.UsageError('仅 Python 包支持 --uninstall；移除引用不会删除源目录或缓存')
        if entry.kind == 'package' and entry not in service.list():
            matches = [item for item in service.list() if item.kind == 'package' and canonicalize_name(Requirement(item.value).name) == canonicalize_name(package)]
            if len(matches) == 1:
                entry = matches[0]
        if entry not in service.list():
            raise DependencyError('项目未声明此依赖')
        if uninstall:
            result = subprocess.run([sys.executable, '-m', 'pip', 'uninstall', '-y', Requirement(entry.value).name],
                                    capture_output=True, text=True)
            if result.returncode:
                raise click.ClickException(result.stderr or result.stdout or '卸载失败')
        service.remove(entry)
        if entry.kind in ('code', 'git'):
            click.echo('代码库声明已移除；缓存和入口保留，请检查业务代码中的导入。')
        click.secho('依赖引用已移除，源目录保留' if entry.kind == 'local' else '依赖已移除', fg='green')
        return {'dependency': entry.value, 'source': entry.kind}
    except (DependencyError, InvalidRequirement, OSError, subprocess.CalledProcessError) as exc:
        raise click.ClickException(str(exc)) from exc

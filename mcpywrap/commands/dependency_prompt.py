"""命令行依赖类型选择；显式参数路径不会进入向导。"""
import sys
import click
from ..command_context import non_interactive
from packaging.requirements import Requirement, InvalidRequirement
from ..dependencies import DependencyDeclaration, DependencyError


def require_interactive():
    if non_interactive():
        raise click.UsageError('请提供包名或 --path 目录；交互向导需要终端。')


def prompt_dependency():
    kind = click.prompt('依赖类型：1 Python 包，2 本地 Addon 目录', type=click.Choice(['1', '2']), default='1')
    value = click.prompt('包名/版本约束' if kind == '1' else 'Addon 目录').strip()
    if kind == '1':
        try:
            Requirement(value)
        except InvalidRequirement as exc:
            raise DependencyError(f'无效的 Python 包声明: {value}') from exc
    return DependencyDeclaration('package' if kind == '1' else 'local', value)

"""命令行依赖类型选择；显式参数路径不会进入向导。"""
import sys
import click
from dataclasses import dataclass, field
from ..command_context import non_interactive
from packaging.requirements import Requirement, InvalidRequirement
from ..dependencies import DependencyDeclaration, DependencyError


@dataclass
class PromptDependency:
    kind: str
    value: str
    options: dict = field(default_factory=dict)


def require_interactive():
    if non_interactive():
        raise click.UsageError('请提供包名、--path 目录或 --qumod；交互向导需要终端。')


def prompt_dependency():
    kind = click.prompt('添加依赖：1 Python 包，2 本地 Addon，3 常用Git依赖快捷添加，4 Git仓库', type=click.Choice(['1', '2', '3', '4']), default='1')
    if kind == '3':
        from ..framework_presets import FRAMEWORK_PRESETS
        choices = list(FRAMEWORK_PRESETS)
        preset = click.prompt('快捷项', type=click.Choice(choices), default=choices[0])
        value = click.prompt('所属脚本目录（留空自动识别；新目录生成入口）', default='', show_default=False)
        return PromptDependency('framework', preset, {'script_dir': value.strip() or None})
    if kind == '4':
        url = click.prompt('Git URL').strip()
        ref = click.prompt('提交／标签／分支', default='HEAD').strip()
        export = click.prompt('导出类型', type=click.Choice(['auto', 'addon', 'code']), default='auto')
        options = {'ref': ref, 'kind': export}
        if export == 'code':
            options['subdir'] = click.prompt('源码子目录', default='.').strip()
            options['target'] = click.prompt('行为包内安装目录').strip()
        return PromptDependency('git', url, options)
    value = click.prompt('包名/版本约束' if kind == '1' else 'Addon 目录').strip()
    if kind == '1':
        try:
            Requirement(value)
        except InvalidRequirement as exc:
            raise DependencyError(f'无效的 Python 包声明: {value}') from exc
    return DependencyDeclaration('package' if kind == '1' else 'local', value)

"""添加 Python 包或本地 Addon 目录依赖。"""
import click
from ..command_context import OperationCommand, project_dir as current_project, report_dependency_warnings
from ..dependencies import DependencyDeclaration, DependencyError, DependencyService
from .dependency_prompt import prompt_dependency, require_interactive, PromptDependency
from ..framework_presets import FRAMEWORK_PRESETS


@click.command(cls=OperationCommand)
@click.argument('package', required=False)
@click.option('--path', 'local_path', help='直接引用本地 Addon 根目录，不安装目录')
@click.option('--qumod', is_flag=True, help='添加并同步已验证版本的 QuMod 外部代码库')
@click.option('--framework', type=click.Choice(list(FRAMEWORK_PRESETS)), help='添加已注册框架预设')
@click.option('--git', 'git_url', help='将任意 Git 项目注册为依赖（读取导出描述或识别 Addon）')
@click.option('--ref', 'git_ref', help='Git分支、标签或完整提交；添加时解析并固定SHA')
@click.option('--dep-name', help='Git依赖名称，默认仓库名')
@click.option('--subdir', help='Git项目或源码子目录，新依赖默认 .；已有声明默认保留')
@click.option('--kind', type=click.Choice(['auto', 'addon', 'code']), help='项目导出类型，新依赖默认auto；已有声明默认保留')
@click.option('--target', help='代码依赖在行为包内的安装目录')
@click.option('--script-dir', help='框架所属脚本目录；唯一入口自动识别，无入口默认 MyScript')
@click.option('--source', '--qumod-source', 'preset_source', help='预设源码来源名称，例如 github/gitee')
def add_cmd(package, local_path, qumod, framework, git_url, git_ref, dep_name, subdir, kind, target, script_dir, preset_source):
    """添加依赖；包安装到 mcpy 工具环境，不安装到游戏。无参数进入向导。"""
    if sum((package is not None, local_path is not None, qumod, framework is not None, git_url is not None)) > 1:
        raise click.UsageError('请选择一种依赖来源：包名、--path、--git、--framework 或 --qumod')
    preset = 'qumod' if qumod else framework
    if (script_dir or preset_source) and not preset:
        raise click.UsageError('--script-dir/--source 需要框架预设')
    if (git_ref or dep_name or subdir is not None or kind is not None or target) and not git_url:
        raise click.UsageError('--ref/--dep-name/--subdir/--kind/--target 需要 --git')
    if not (current_project() / 'pyproject.toml').exists():
        raise click.ClickException('项目尚未初始化，请先运行 mcpy init')
    try:
        service = DependencyService(str(current_project()))
        if git_url:
            return service.add_git(git_url, ref=git_ref, name=dep_name, subdir=subdir, kind=kind, target=target)
        if preset:
            entry = PromptDependency('framework', preset, {'script_dir': script_dir, 'source': preset_source})
        elif package is None and local_path is None:
            require_interactive()
            entry = prompt_dependency()
        else:
            entry = DependencyDeclaration('local' if local_path is not None else 'package', local_path if local_path is not None else package)
        service = DependencyService(str(current_project()))
        if entry.kind == 'git':
            return service.add_git(entry.value, **entry.options)
        if entry.kind == 'framework':
            click.echo('正在准备框架外部依赖（固定提交，不安装到工具 Python 环境）...')
            result = service.add_framework(entry.value, **entry.options)
            for warning in result['warnings']:
                click.echo(warning, err=True)
            click.secho('框架已准备；其他开发者克隆后执行 mcpy sync 即可恢复。', fg='green')
            return result
        if entry.kind == 'local':
            changed, _ = service.add_local(entry.value)
        else:
            click.echo(f'正在向 mcpy 工具环境安装 {entry.value}（非游戏环境）...')
            changed = service.add_package(entry.value)
        manager = service.last_resolution
        report_dependency_warnings(manager)
        click.secho('依赖已添加' if changed else '依赖已存在', fg='green')
        return {'changed': changed, 'dependency': entry.value, 'source': entry.kind,
                'classification': 'addon' if entry.kind == 'local' else manager.status_for(current_project(), entry).state,
                'warnings': manager.warnings}
    except (DependencyError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc

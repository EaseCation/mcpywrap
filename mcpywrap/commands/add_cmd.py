"""添加 Python 包或本地 Addon 目录依赖。"""
import click
from ..command_context import OperationCommand, project_dir as current_project, report_dependency_warnings
from ..dependencies import DependencyDeclaration, DependencyError, DependencyService
from .dependency_prompt import prompt_dependency, require_interactive


@click.command(cls=OperationCommand)
@click.argument('package', required=False)
@click.option('--path', 'local_path', help='直接引用本地 Addon 根目录，不安装目录')
def add_cmd(package, local_path):
    """添加依赖；包安装到 mcpy 工具环境，不安装到游戏。无参数进入向导。"""
    if package is not None and local_path is not None:
        raise click.UsageError('包名与 --path 不能同时使用')
    if not (current_project() / 'pyproject.toml').exists():
        raise click.ClickException('项目尚未初始化，请先运行 mcpy init')
    try:
        if package is None and local_path is None:
            require_interactive()
            entry = prompt_dependency()
        else:
            entry = DependencyDeclaration('local' if local_path is not None else 'package', local_path if local_path is not None else package)
        service = DependencyService(str(current_project()))
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

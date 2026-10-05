"""用参数生成 Mod 脚本，GUI 向导仅用于人工交互。"""
import keyword
import os
import click
from ..command_context import OperationCommand, project_dir, non_interactive, require_project
from ..minecraft.addons import find_behavior_pack_dir
from ..minecraft.template.generate_mod_files import generate_mod_framework
from ..framework_presets import FRAMEWORK_PRESETS


@click.command(cls=OperationCommand)
@click.option('--name', help='Mod 名称，也是 Python 类名')
@click.option('--version', default='0.1.0', show_default=True)
@click.option('--script-dir', default='myScript', show_default=True)
@click.option('--server-system', default='ServerSystem', show_default=True)
@click.option('--client-system', default='ClientSystem', show_default=True)
@click.option('--gui', is_flag=True, help='打开人工使用的模板向导')
@click.option('--framework', type=click.Choice(['native'] + list(FRAMEWORK_PRESETS)), default='native', show_default=True)
@click.option('--source', '--qumod-source', 'qumod_source', help='框架预设的源码来源名称')
def mod_cmd(name, version, script_dir, server_system, client_system, gui, framework, qumod_source):
    """生成 Mod 模板；Agent 应使用参数，不操作 Qt 向导。"""
    require_project()
    if qumod_source and framework == 'native':
        raise click.UsageError('--source 需要选择框架预设')
    behavior = find_behavior_pack_dir(str(project_dir()))
    if not behavior:
        raise click.ClickException('未找到行为包，请先初始化 Addon')
    if gui or (not name and not non_interactive()):
        if framework != 'native':
            raise click.UsageError('请使用 mcpy ui → 添加依赖 → Git 依赖中的快捷添加按钮')
        from ..command_context import json_output
        if non_interactive() or json_output():
            raise click.UsageError('Qt 模板向导仅供人工使用；请提供 --name 等生成参数')
        from ..minecraft.template.mod_template import open_ui_crate_mod
        open_ui_crate_mod(behavior)
        return {'application': 'mod-wizard'}
    if not name:
        raise click.UsageError('非交互生成模板需要 --name')
    for label, value in [('name', name), ('script-dir', script_dir), ('server-system', server_system), ('client-system', client_system)]:
        if not value.isascii() or not value.isidentifier() or keyword.iskeyword(value):
            raise click.UsageError(label + ' 必须是有效的 ASCII Python 标识符')
    from packaging.version import Version
    Version(version)
    from pathlib import Path
    target = Path(behavior) / script_dir
    if target.exists():
        raise click.ClickException('脚本目录已存在，不覆盖: ' + str(target))
    if framework != 'native':
        from ..dependencies import DependencyService
        result = DependencyService(project_dir()).add_framework(framework, script_dir, qumod_source, require_new=True)
        result['name'] = name
        return result
    success, message = generate_mod_framework(behavior, name, version, server_system,
        f'{script_dir}.server.{server_system}.{server_system}', client_system,
        f'{script_dir}.client.{client_system}.{client_system}', script_dir)
    if not success:
        raise click.ClickException(message)
    return {'script_dir': str(target), 'name': name}

"""Inspect the selected dependency graph without installing or running hooks."""
import click
from ..command_context import OperationCommand, project_dir, require_project, json_output, report_dependency_warnings
from ..dependencies import DependencyService
from ..dependency_feedback import report_selection
from ..utils.console import echo


@click.command(cls=OperationCommand)
@click.option('--bundled-only', is_flag=True, help='预览 build/package 的正式依赖图；默认预览 dev/run')
def deps_cmd(bundled_only):
    """只读查看依赖用途、发布状态和引用链；不执行准备或安装。"""
    require_project()
    manager = DependencyService(project_dir()).resolve(purpose='release' if bundled_only else 'runtime')
    report_dependency_warnings(manager)
    return present_selection(manager.selection())


def present_selection(result):
    report_selection(result)
    for item in result['dependencies']:
        echo('%s [unbundled=%s / %s]' % (item['name'], str(item['unbundled']).lower(), '随发布' if item['included_in_release'] else '不随发布'))
        for chain in item['via']:
            echo('  ' + ' → '.join(chain))
    for item in result['excluded']:
        echo('%s [已排除：%s]' % (item['dependency'], '不进入发布' if item['reason'] == 'unbundled' else '依赖自身的 unbundled 引用不传递'))
    return result if json_output() else None

"""Explicit local project scripts, separate from game run and runtime Python."""
import click
from ..command_context import OperationCommand, project_dir, require_project
from ..project_scripts import configuration, operation


@click.group()
def script_cmd():
    """列出或执行当前项目的有限宿主脚本。"""


@script_cmd.command(name='list', cls=OperationCommand, local_only=True)
@click.option('--effective', is_flag=True, help='显示根任务和依赖消费者准备的有效计划、环境及诊断（只读）')
def list_cmd(effective=False):
    """只读列出脚本与生命周期绑定。"""
    require_project()
    scripts, hooks = configuration(project_dir())
    result = {'scripts': [{'name': name, 'command': spec['command'], 'timeout': spec['timeout'],
                         'hooks': [event for event, names in hooks.items() if name in names]}
                        for name, spec in scripts.items()]}
    from ..command_context import json_output
    if json_output() and not effective:
        return result
    from ..consumer_prepare import PreparationPlan, EVENTS
    plan = PreparationPlan(project_dir(), inspect_only=True)
    result.update(plan.inspect())
    result['execution_order'] = {event: [{'kind': 'root', 'name': name} for name in hooks.get(event, [])] +
                               [{'kind': 'consumer_prepare', 'provider': p['id'], 'name': p['name']}
                                for p in plan.enabled] for event in EVENTS}
    if json_output():
        return result
    for script in result['scripts']:
        click.echo('根任务 %s：%s' % (script['name'], ', '.join(script['hooks']) or '手动执行'))
    states = {'enabled': '自动准备', 'disabled': '已显式停用', 'not_transitive': '未开启传递执行', 'invalid': '声明无效'}
    for provider in result['consumer_prepare']:
        click.echo('依赖 %s：%s；来源 %s' % (provider['name'], states[provider['state']], provider['source']))
    if result['environment']['python']:
        click.echo('工具 Python：%s（%s）' % (result['environment']['python'], result['environment']['state']))
    for issue in result['diagnostics']:
        click.echo(issue['error'] + '\n' + issue.get('hint', ''), err=True)
    if not result['complete']:
        click.echo('计划不完整；请先恢复依赖并修复上述问题。', err=True)


@script_cmd.command(name='run', cls=OperationCommand, local_only=True)
@click.argument('name')
@click.argument('args', nargs=-1, type=click.UNPROCESSED)
def run_cmd(name, args):
    """执行一次脚本；在 -- 之后传递脚本参数。"""
    require_project()
    with operation(project_dir(), task=name, args=args) as results:
        return {'scripts': results}

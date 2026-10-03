"""游戏内 UI 控制命令；所有调用复用 Python 通道，包括远程执行。"""
import json
import click
from ..command_context import OperationCommand, project_dir, json_output


class UICommand(OperationCommand):
    def invoke(self, ctx):
        ctx.params.pop('json_output', None)
        # ui status/cancel 不使用同名顶层命令的远程路由。
        return click.Command.invoke(self, ctx)


def perform(session, action, **parameters):
    from ..mcstudio.runtime_ui import execute
    result = execute(project_dir(), session, action, parameters)
    if action == 'snapshot' and result.get('ok') and not json_output():
        click.echo('snapshot: ' + result['snapshot'])
        click.echo('screen: ' + result['top'])
        click.echo(result['tree'])
        if result['truncated']:
            click.echo('更多节点：--offset ' + str(result['next_offset']))
        return None
    return result


def session_option(function):
    return click.option('--session', required=True)(function)


def target_options(function):
    function = click.option('--request-id', help='动作幂等 ID；结果未知时使用 status 查询，不重复输入')(function)
    function = click.option('--snapshot', required=True, help='刚刚观察到的快照 ID')(function)
    function = click.argument('node', type=click.IntRange(1))(function)
    return session_option(function)


@click.group(name='ui')
def ui_cmd():
    """注入游戏内 UI API；文字树观察、节点操作与后台输入。"""


@ui_cmd.command(cls=UICommand, name='install')
@session_option
def install_cmd(session):
    """注入或更新 mcpy.ui / mcpy.api；重复安装同版本不重复监听。"""
    return perform(session, 'install')


@ui_cmd.command(cls=UICommand, name='snapshot')
@session_option
@click.option('--root', help='实际 UI 子树路径，默认识别标准界面根')
@click.option('--query', help='筛选文字或路径，不猜测未返回的节点 ID')
@click.option('--include-offscreen', is_flag=True)
@click.option('--limit', type=click.IntRange(1, 160), default=80, show_default=True)
@click.option('--offset', type=click.IntRange(0), default=0)
@click.option('--details', is_flag=True, help='附带完整控件路径和逻辑 UI 坐标')
def snapshot_cmd(session, **parameters):
    """读取文字树；每次观察生成新快照，旧编号作废。"""
    return perform(session, 'snapshot', **parameters)


@ui_cmd.command(cls=UICommand, name='click')
@target_options
def click_cmd(session, node, snapshot, request_id):
    """在游戏内点击按钮/开关/输入框；自动抬起，不移动系统鼠标。"""
    return perform(session, 'click', node=node, snapshot=snapshot, **({'request_id': request_id} if request_id else {}))


@ui_cmd.command(cls=UICommand, name='slide')
@target_options
@click.option('--fraction', required=True, type=click.FloatRange(0, 1), help='滑轨比例 0–1；业务值须刷新确认')
def slide_cmd(session, node, snapshot, request_id, fraction):
    """通过游戏内部交互设置滑轨位置，触发正常 UI 输入链。"""
    return perform(session, 'slide', node=node, snapshot=snapshot, fraction=fraction,
                   **({'request_id': request_id} if request_id else {}))


@ui_cmd.command(cls=UICommand, name='scroll')
@target_options
@click.option('--percent', required=True, type=click.IntRange(0, 100))
def scroll_cmd(session, node, snapshot, request_id, percent):
    """直接滚动容器到指定百分比，完成后刷新节点。"""
    return perform(session, 'scroll', node=node, snapshot=snapshot, percent=percent,
                   **({'request_id': request_id} if request_id else {}))


@ui_cmd.command(cls=UICommand, name='set-control-value')
@target_options
@click.option('--value', required=True, help='JSON 值：字符串、布尔值或数值；不是业务提交')
def set_value_cmd(session, node, snapshot, request_id, value):
    """仅修改控件状态；不保证原版业务回调执行。"""
    try:
        parsed = json.loads(value)
    except ValueError:
        raise click.UsageError('--value 必须是合法 JSON 值') from None
    return perform(session, 'set_control_value', node=node, snapshot=snapshot, value=parsed,
                   **({'request_id': request_id} if request_id else {}))


@ui_cmd.command(cls=UICommand, name='status')
@session_option
@click.option('--operation', help='查询返回的动作 id 或预先指定的 request-id')
def status_cmd(session, operation):
    """查询注入能力或动作的发送、释放状态；不重复输入。"""
    return perform(session, 'status', operation=operation)


@ui_cmd.command(cls=UICommand, name='cancel')
@session_option
@click.option('--operation', required=True)
def cancel_cmd(session, operation):
    """释放当前动作；已完成的动作不会再次执行。"""
    return perform(session, 'cancel', operation=operation)


@ui_cmd.command(cls=UICommand, name='uninstall')
@session_option
def uninstall_cmd(session):
    """释放输入、解绑本控制层监听；不停止游戏。"""
    return perform(session, 'close')

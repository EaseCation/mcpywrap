"""Pair a standard mcpy installation with a local application host."""
from pathlib import Path
import click
from ..command_context import OperationCommand, project_dir
from ..mobile_host import profiles
from ..mobile_host.client import Client, pair

@click.group()
def host_cmd():
    """管理本机 App 连接和共享工作区。"""

@host_cmd.command('pair', cls=OperationCommand, local_only=True)
@click.option('--url', default='http://127.0.0.1:17653', show_default=True)
@click.option('--code', required=True, help='App 中短时有效的配对码')
@click.option('--workspace', required=True, type=click.Path(exists=True, file_okay=False))
@click.option('--label', default='mcpy CLI')
def pair_cmd(url, code, workspace, label):
    return pair(url, code, workspace, label)

@host_cmd.command('status', cls=OperationCommand, local_only=True)
@click.option("--operation",help="查询原任务，避免重复发送修改操作")
@click.option('--recent', is_flag=True, help='列出本客户端保存的请求 ID（App 离线也可用）')
@click.option('--binding-only',is_flag=True,help='只读当前工作区的本地绑定，不访问任何宿主')
def status_cmd(operation, recent, binding_only=False):
    records=profiles.read()
    selected=profiles.select(project_dir())
    if binding_only:
        if operation or recent: raise click.UsageError('--binding-only 不与 --operation 或 --recent 同用')
        return dict(paired=selected is not None,bound_for_project=selected is not None,
                    **({'endpoint':selected['endpoint'],'workspace':selected['workspace']} if selected else {}))
    record = selected or (records[0] if len(records)==1 else None)
    if not record: return {'paired': False, 'hint': '在 App 的开发工具页面开始连接'}
    if recent:
        from ..mobile_host.receipts import Receipts
        return {'operations': Receipts(record).recent()}
    if operation:
        if len(operation)!=64 or any(c not in '0123456789abcdef' for c in operation): raise ValueError('无效操作 ID')
        return Client(record).request('GET','/operations/'+operation)
    from ..remote.protocol import RemoteError
    binding = dict(paired=True, bound_for_project=profiles.select(project_dir()) is not None,
                   endpoint=record['endpoint'], workspace=record['workspace'])
    try:
        return dict(Client(record).capabilities(), **binding)
    except RemoteError as error:
        error.details = dict(getattr(error, 'details', {}) or {}, **binding)
        raise

@host_cmd.command('disconnect', cls=OperationCommand, local_only=True)
@click.option('--offline', is_flag=True, help='App 不可达时仅删除本地连接；仍需在 App 撤销授权')
def disconnect_cmd(offline):
    records = profiles.read()
    record = profiles.select(project_dir()) or (records[0] if len(records)==1 else None)
    if not record:
        if records: raise ValueError('有多个连接，请用 --project 指定要断开的工作区')
        return {'paired': False}
    if not offline: Client(record).request('POST', '/clients/revoke', {})
    profiles.unbind(record['workspace'])
    return {'paired': False, 'revoked': not offline}


@host_cmd.command('resume', cls=OperationCommand, local_only=True)
@click.option('--operation', required=True, help='原操作 ID；仅恢复等待和提交已有准备结果')
def resume_cmd(operation):
    records = profiles.read()
    record = profiles.select(project_dir()) or (records[0] if len(records) == 1 else None)
    if not record:
        raise ValueError('请先选择已配对的工作区')
    return Client(record).resume(operation)

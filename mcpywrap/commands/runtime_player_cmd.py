"""统一玩家动作，不向桌面发送键鼠。"""
import click
import json
from pathlib import Path
from ..command_context import project_dir
from .runtime_ui_cmd import UICommand, session_option


def perform(session, action, **parameters):
    from ..mcstudio.runtime_ui import execute
    parameters = {k:v for k,v in parameters.items() if v is not None}
    return execute(project_dir(), session, action, parameters, family='player')


def action_options(function):
    return session_option(click.option('--request-id', help='动作幂等 ID；未知结果先查询，不重发')(function))


@click.group(name='player')
def player_cmd():
    """玩家状态、移动、朝向、快捷栏、攻击与物品使用。"""


@player_cmd.command(cls=UICommand, name='install')
@session_option
def install_cmd(session):
    """一次注入 mcpy.ui、mcpy.player、mcpy.api。"""
    return perform(session, 'install')


@player_cmd.command(cls=UICommand, name='snapshot')
@session_option
def snapshot_cmd(session):
    """读取位置、朝向、快捷栏、手持物品、瞄准目标及距离。"""
    return perform(session, 'snapshot')


@player_cmd.command(cls=UICommand, name='move')
@action_options
@click.option('--forward', type=click.FloatRange(-1,1), default=0., help='正值向前，负值向后；方向量不是速度')
@click.option('--right', type=click.FloatRange(-1,1), default=0., help='正值向右，负值向左')
@click.option('--duration-ms', type=click.IntRange(20,10000), default=500)
@click.option('--sprint', is_flag=True)
def move_cmd(session, **parameters):
    """按当前朝向移动一段时间，随后自动解锁。"""
    return perform(session, 'move', **parameters)


@player_cmd.command(cls=UICommand, name='look')
@action_options
@click.option('--pitch', required=True, type=click.FloatRange(-90,90), help='负值向上，正值向下')
@click.option('--yaw', required=True, type=float, help='0 南/+Z，90 西/-X，-90 东/+X')
def look_cmd(session, **parameters):
    """设置玩家俯仰角与水平朝向（角度）。"""
    return perform(session, 'look', **parameters)


@player_cmd.command(cls=UICommand, name='look-at', context_settings={'ignore_unknown_options':True})
@action_options
@click.argument('position', nargs=3, type=float)
def look_at_cmd(session, position, request_id):
    """看向世界坐标 X Y Z；看方块中心时各轴加 0.5。"""
    return perform(session, 'look_at', x=position[0], y=position[1], z=position[2], request_id=request_id)


@player_cmd.command(cls=UICommand, name='select-slot')
@action_options
@click.argument('slot', type=click.IntRange(1,9))
def select_slot_cmd(session, slot, request_id):
    """选择快捷栏第 1–9 格，不依赖数字键绑定。"""
    return perform(session, 'select_slot', slot=slot, request_id=request_id)


@player_cmd.command(cls=UICommand, name='key')
@action_options
@click.argument('keys')
@click.option('--hold-ms', type=click.IntRange(20,10000), default=80)
def key_cmd(session, **parameters):
    """游戏内按键/组合键，例如 W、SPACE、CTRL+W；自动释放。"""
    return perform(session, 'key', **parameters)


@player_cmd.command(cls=UICommand, name='jump')
@action_options
def jump_cmd(session, request_id):
    """调用客户端跳跃动作。"""
    return perform(session, 'jump', request_id=request_id)


@player_cmd.command(cls=UICommand, name='sneak')
@action_options
@click.option('--duration-ms', type=click.IntRange(20,10000), default=500)
def sneak_cmd(session, **parameters):
    """限时潜行，结束后恢复之前的潜行状态。"""
    return perform(session, 'sneak', **parameters)


@player_cmd.command(cls=UICommand, name='attack')
@action_options
@click.option('--snapshot', required=True)
def attack_cmd(session, **parameters):
    """使用手持物品攻击快照中准星瞄准的实体一次。"""
    return perform(session, 'attack', **parameters)


@player_cmd.command(cls=UICommand, name='use-item')
@action_options
@click.option('--snapshot', required=True)
@click.option('--mode', type=click.Choice(['auto','air','block']), default='auto')
@click.option('--hold-ms', type=click.IntRange(20,10000), default=200, help='对空使用/蓄力时间；方块交互只执行一次')
def use_item_cmd(session, **parameters):
    """使用手持物品：对方块交互/放置，或对空使用并自动松开。"""
    return perform(session, 'use_item', **parameters)


@player_cmd.command(cls=UICommand, name='dig')
@action_options
@click.option('--snapshot', required=True)
@click.option('--duration-ms', type=click.IntRange(20,10000), default=1500)
def dig_cmd(session, **parameters):
    """限时挖掘快照中的瞄准方块；破坏、失去目标或超时后停止。"""
    return perform(session, 'dig', **parameters)


@player_cmd.command(cls=UICommand, name='eat')
@action_options
@click.option('--snapshot', required=True)
@click.option('--hold-ms', type=click.IntRange(20,10000), default=2000)
def eat_cmd(session, **parameters):
    """使用引擎识别的手持食物，默认持续 2 秒并自动释放。"""
    return perform(session,'eat',**parameters)


@player_cmd.command(cls=UICommand, name='shoot')
@action_options
@click.option('--snapshot', required=True)
@click.option('--hold-ms', type=click.IntRange(20,10000), default=1200)
def shoot_cmd(session, **parameters):
    """普通弓蓄力后松开发射；弩暂不支持。"""
    return perform(session,'shoot',**parameters)


@player_cmd.command(cls=UICommand, name='sequence')
@action_options
@click.option('--steps', help='JSON 步骤列表，与 --file 二选一')
@click.option('--file', 'filename', type=click.Path(exists=True,dir_okay=False), help='调用端 UTF-8 JSON 文件')
def sequence_cmd(session, request_id, steps, filename):
    """一次提交最多 32 步；支持 delay_ms/wait、执行前断言、失败停止与取消。"""
    if (steps is None)==(filename is None):
        raise click.UsageError('必须且只能指定 --steps 或 --file')
    try:
        plan=json.loads(Path(filename).read_text(encoding='utf-8-sig') if filename else steps)
    except ValueError:
        raise click.UsageError('步骤必须是有效 JSON') from None
    return perform(session,'sequence',steps=plan,request_id=request_id)


@player_cmd.command(cls=UICommand, name='status')
@session_option
@click.option('--operation')
@click.option('--details', is_flag=True, help='保留完整前后观察；默认只返回步骤变化，减少输出')
def status_cmd(session, operation, details):
    """查询能力、活动动作或动作结果。"""
    return perform(session, 'status', operation=operation, details=details)


@player_cmd.command(cls=UICommand, name='cancel')
@session_option
@click.option('--operation', required=True)
def cancel_cmd(session, operation):
    """取消指定的本控制层玩家动作并释放输入。"""
    return perform(session, 'cancel', operation=operation)


@player_cmd.command(cls=UICommand, name='stop')
@session_option
def stop_cmd(session):
    """释放本控制层的玩家输入，不停止游戏。"""
    return perform(session, 'stop')

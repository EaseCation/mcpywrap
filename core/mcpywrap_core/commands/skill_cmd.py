"""Install the same skill tree into any Agent's user-selected skill directory."""
from pathlib import Path
import shutil
import tempfile
import os
import click
from ..command_context import OperationCommand

@click.group()
def skill_cmd():
    """安装与当前 CLI 同版本的完整标准 skill。"""

@skill_cmd.command('install', cls=OperationCommand, local_only=True)
@click.option('--directory',required=True,type=click.Path(file_okay=False),help='目标 Agent 的 skill 文件夹')
@click.option('--replace',is_flag=True,help='更新已经安装的 mcpywrap skill')
def install(directory,replace):
    source=Path(__file__).resolve().parents[1]/'skill'
    if not source.is_dir(): source=Path(__file__).resolve().parents[3]/'skills/mcpywrap'
    if not (source/'SKILL.md').is_file(): raise ValueError('当前发行包缺少完整 skill，请升级 mcpywrap')
    target=Path(directory).expanduser().absolute()
    if target.is_symlink(): raise ValueError('技能目标不能是符号链接')
    if target.exists() and not replace: raise ValueError('技能目录已存在；确认后使用 --replace')
    if target.exists() and not (target/'SKILL.md').is_file(): raise ValueError('目标不是已有技能目录，不覆盖')
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.mcpy-skill-',dir=target.parent) as temp:
        stage=Path(temp)/'skill';shutil.copytree(source,stage,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        previous=Path(temp)/'previous'
        if target.exists(): os.replace(target,previous)
        try: os.replace(stage,target)
        except BaseException:
            if previous.exists(): os.replace(previous,target)
            raise
    from .. import __version__
    return {'directory':str(target),'version':__version__,'files':sum(1 for p in target.rglob('*') if p.is_file())}

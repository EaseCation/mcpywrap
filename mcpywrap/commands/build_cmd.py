"""
构建命令模块
"""
import os
import click
from ..config import config_exists, get_mcpywrap_config
from ..builders.project_builder import build_project

@click.command()
def build_cmd():
    """构建为 MCStudio 工程"""
    if not config_exists():
        click.secho('❌ 错误: 未找到配置文件。请先运行 `mcpywrap init` 初始化项目。', fg="red")
        return False
    
    # 获取mcpywrap特定配置
    mcpywrap_config = get_mcpywrap_config()
    # 源代码目录固定为当前目录
    source_dir = os.getcwd()
    # 目标目录从配置中读取behavior_pack_dir
    target_dir = mcpywrap_config.get('target_dir')
    
    if not target_dir:
        click.secho('❌ 错误: 配置文件中未找到target_dir。请手动添加。', fg="red")
        return False
    
    # 转换为绝对路径
    target_dir = os.path.normpath(os.path.join(source_dir, target_dir))
    # 实际构建
    build(source_dir, target_dir)
    
def build(source_dir, target_dir):
    if target_dir is None:
        click.secho('❌ 错误: 未指定目标目录。', fg="red")
        return False
    if not os.path.exists(target_dir):
        # 创建目录
        os.makedirs(target_dir)
        click.secho(f'🔧 创建目标目录: ', fg="yellow", nl=False)
    
    click.secho(f'📂 正在将源代码从 ', fg="bright_blue", nl=False)
    click.secho(f'{source_dir}', fg="bright_cyan", nl=False)
    click.secho(' 复制到 ', fg="bright_blue", nl=False)
    click.secho(f'{target_dir}', fg="bright_cyan", nl=False)
    click.secho('...', fg="bright_blue")
    
    click.secho('🔄 正在构建项目与代码...', fg="yellow")
    success, output = build_project(source_dir, target_dir)
    
    if success:
        click.secho('✅ 构建成功！项目已生成到目标目录。', fg="green")
        return True
    else:
        click.secho(f'❌ 构建失败: ', fg="red", nl=False)
        click.secho(f'{output}', fg="bright_red")
        return False


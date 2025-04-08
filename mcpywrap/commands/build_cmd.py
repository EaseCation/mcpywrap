# -*- coding: utf-8 -*-
"""
构建命令模块
"""
import os
import click
from ..config import config_exists, get_mcpywrap_config, get_project_type
from ..builders.project_builder import ProjectBuilder


base_dir = os.getcwd()

@click.command()
def build_cmd():
    """构建为 MCStudio 工程"""
    if not config_exists():
        click.secho('❌ 错误: 未找到配置文件。请先运行 `mcpywrap init` 初始化项目。', fg="red")
        return False
    
    # 获取mcpywrap特定配置
    mcpywrap_config = get_mcpywrap_config()

    if get_project_type() == "addon":
        # 源代码目录固定为当前目录
        source_dir = base_dir
        # 目标目录从配置中读取behavior_pack_dir
        target_dir = mcpywrap_config.get('target_dir')
        
        if not target_dir:
            click.secho('❌ 错误: 配置文件中未找到target_dir。请手动添加。', fg="red")
            return False
        
        # 转换为绝对路径
        target_dir = os.path.normpath(os.path.join(source_dir, target_dir))
        # 实际构建
        build(source_dir, target_dir)
    else:
        click.secho('❌ 暂未支持: 当前仅支持Addons项目的构建', fg="red")
        return False
    
def build(source_dir, target_dir):
    """
    执行项目构建
    
    Args:
        source_dir: 源代码目录
        target_dir: 目标目录
        
    Returns:
        bool: 是否构建成功
    """
    if target_dir is None:
        click.secho('❌ 错误: 未指定目标目录。', fg="red")
        return False
        
    # 使用项目构建器
    builder = ProjectBuilder(source_dir, target_dir)
    success, error = builder.build()
    
    if success:
        click.secho('✅ 构建成功！项目已生成到目标目录。', fg="green")
        return True
    else:
        click.secho(f'❌ 构建失败: ', fg="red", nl=False)
        click.secho(f'{error}', fg="bright_red")
        return False


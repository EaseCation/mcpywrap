# -*- coding: utf-8 -*-
"""
构建命令模块
"""
import os
import click
from ..config import config_exists, get_mcpywrap_config, get_project_type, ensure_map_setuptools_sync
from ..builders.project_builder import AddonProjectBuilder, MapProjectBuilder


base_dir = os.getcwd()

@click.command()
@click.option('--merge', '-m', is_flag=True, help='强制合并所有资源文件')
def build_cmd(merge):
    """构建为 MCStudio 工程"""
    if not config_exists():
        click.secho('❌ 错误: 未找到配置文件。请先运行 `mcpywrap init` 初始化项目。', fg="red")
        return False
    
    # 确保 map 项目的 setuptools 配置同步
    ensure_map_setuptools_sync(interactive=True)
    
    # 获取mcpywrap特定配置
    mcpywrap_config = get_mcpywrap_config()
    
    target_dir = mcpywrap_config.get('target_dir')

    if not target_dir:
            click.secho('❌ 错误: 配置文件中未找到target_dir。请手动添加。', fg="red")
            return False
    
    # 转换为绝对路径
    target_dir = os.path.normpath(os.path.join(base_dir, target_dir))

    # 实际构建
    build(base_dir, target_dir, force_merge=merge)

    
def build(source_dir, target_dir, force_merge: bool = False):
    """
    执行项目构建
    
    Args:
        source_dir: 源代码目录
        target_dir: 目标目录
        force_merge: 是否强制合并资源文件
        
    Returns:
        bool: 是否构建成功
    """
    if target_dir is None:
        click.secho('❌ 错误: 未指定目标目录。', fg="red")
        return False
    
    project_type = get_project_type()


    if project_type == "addon":
        builder = AddonProjectBuilder(source_dir, target_dir)
        success, error = builder.build()
    elif project_type == "map":
        builder = MapProjectBuilder(source_dir, target_dir, force_merge)
        success, error = builder.build()
    else:
        click.secho('❌ 暂未支持: 当前仅支持Addons和Map项目的构建', fg="red")
        return False
    
    if success:
        click.secho('✅ 构建成功！项目已生成到目标目录。', fg="green")
        return True
    else:
        click.secho(f'❌ 构建失败: ', fg="red", nl=False)
        click.secho(f'{error}', fg="bright_red")
        return False


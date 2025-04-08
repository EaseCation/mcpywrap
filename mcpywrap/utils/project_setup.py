# -*- coding: utf-8 -*-

"""
项目设置工具模块 - 提供项目配置和安装的通用功能
"""
import os
import sys
import click
import subprocess
import getpass
from ..utils.utils import ensure_dir
from ..minecraft.addons import find_behavior_pack_dir, is_minecraft_addon_project

base_dir = os.getcwd()


def get_git_config_value(key):
    """尝试从git配置获取值"""
    try:
        result = subprocess.run(
            ["git", "config", "--get", key],
            capture_output=True,
            text=True,
            check=False
        )
        value = result.stdout.strip()
        return value if value else None
    except FileNotFoundError:
        return None

def get_default_author():
    """获取默认作者名"""
    # 优先使用git配置
    git_author = get_git_config_value("user.name")
    if git_author:
        return git_author
    
    # 使用系统用户名
    return getpass.getuser()

def get_default_email():
    """获取默认邮箱"""
    return get_git_config_value("user.email") or ""

def get_default_project_name():
    """获取默认项目名称（当前目录名）"""
    return os.path.basename(base_dir)

def update_behavior_pack_config(config, base_dir, behavior_pack_dir, target_dir=None):
    """更新配置中的行为包信息"""
    if behavior_pack_dir:
        rel_path = os.path.relpath(behavior_pack_dir, base_dir)
        click.echo(click.style(f'📦 更新包路径: {rel_path}', fg='blue'))
        
        if not config.get('tool'):
            config['tool'] = {}
            
        config['tool']['setuptools'] = {
            'package-dir': {"": rel_path},
            'packages': {'find': {'where': [rel_path], 'include': ["*"]}}
        }
        
        # 设置或保留target_dir配置
        if target_dir:
            config['tool'].setdefault('mcpywrap', {})['target_dir'] = target_dir
            click.echo(click.style(f'📂 目标目录设置为: {target_dir}', fg='green'))
        elif config.get('tool', {}).get('mcpywrap', {}).get('target_dir'):
            target_dir = config['tool']['mcpywrap']['target_dir']
            click.echo(click.style(f'📂 保留目标目录: {target_dir}', fg='blue'))
        else:
            config.setdefault('tool', {}).setdefault('mcpywrap', {})['target_dir'] = ""
            
        return rel_path
    else:
        # 如果没有找到behavior_pack目录，则默认使用当前目录
        return "."

def find_and_configure_behavior_pack(base_dir, config, ask_for_target=False):
    """查找行为包并更新配置"""
    behavior_pack_dir = None
    target_dir = None
    
    # 检查是否为Minecraft addon项目并查找行为包
    if is_minecraft_addon_project(base_dir):
        click.echo(click.style('🔍 检测到Minecraft addon项目结构', fg='magenta'))
        behavior_pack_dir = find_behavior_pack_dir(base_dir)
        
        if behavior_pack_dir:
            click.echo(click.style(f'✅ 找到行为包目录: {behavior_pack_dir}', fg='green'))
            
            # 询问目标目录（如果需要）
            if ask_for_target and click.confirm(click.style('❓ 是否配置构建目标目录？（指定生成的脚本文件应安装到的位置）', fg='magenta'), default=False):
                target_dir = click.prompt(click.style('📂 请输入目标目录', fg='cyan'), default=behavior_pack_dir, type=str)
                ensure_dir(target_dir)
            
            # 更新配置
            rel_path = update_behavior_pack_config(config, base_dir, behavior_pack_dir, target_dir)
            return behavior_pack_dir, rel_path
        else:
            click.echo(click.style('⚠️ 无法找到行为包目录', fg='yellow'))
    else:
        click.echo(click.style('⚠️ 未检测到标准的Minecraft addon项目结构', fg='yellow'))
    
    return None, "."

def install_project_dev_mode():
    """使用pip在开发模式下安装项目"""
    click.echo(click.style('⚙️ 正在安装项目（pip install -e .）...', fg='blue'))
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-e", "."])
        click.echo(click.style('✅ 项目已成功安装！', fg='green'))
        return True
    except subprocess.CalledProcessError:
        click.echo(click.style('🚫 项目安装失败，请手动运行 pip install -e .', fg='red'))
        return False

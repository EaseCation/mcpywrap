# -*- coding: utf-8 -*-

"""
安装依赖命令模块
"""
import click
import subprocess
import sys
from ..config import config_exists, add_dependency, get_project_dependencies

@click.command()
@click.argument('package', required=True)
def add_cmd(package):
    """安装依赖并添加到项目配置中"""
    # 检查项目是否已初始化
    if not config_exists():
        click.echo(click.style('❌ 项目尚未初始化，请先运行 mcpy init', fg='red', bold=True))
        return
    
    # 检查依赖是否已存在
    dependencies = get_project_dependencies()
    
    if package in dependencies:
        click.echo(click.style(f'ℹ️  依赖 {package} 已存在于项目配置中', fg='blue'))
    else:
        # 添加依赖到配置
        if add_dependency(package):
            click.echo(click.style(f'✅ 依赖 {package} 已添加到项目配置', fg='green'))
        else:
            click.echo(click.style(f'❌ 添加依赖 {package} 失败', fg='red'))
    
    # 实际安装依赖
    click.echo(click.style(f'📦 正在安装 {package}...', fg='cyan'))
    
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
        click.echo(click.style(f'✅ {package} 安装成功！', fg='green', bold=True))
    except subprocess.CalledProcessError:
        click.echo(click.style(f'❌ {package} 安装失败，请检查包名是否正确或网络连接', fg='red', bold=True))

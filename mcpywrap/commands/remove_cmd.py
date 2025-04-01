# -*- coding: utf-8 -*-

"""
删除依赖命令模块
"""
import click
import subprocess
import sys
from ..config import config_exists, remove_dependency, get_project_dependencies

@click.command()
@click.argument('package', required=True)
@click.option('--uninstall', '-u', is_flag=True, help='同时卸载依赖包')
def remove_cmd(package, uninstall):
    """从项目配置中删除依赖并可选择卸载"""
    # 检查项目是否已初始化
    if not config_exists():
        click.echo(click.style('❌ 项目尚未初始化，请先运行 mcpy init', fg='red', bold=True))
        return
    
    # 检查依赖是否存在
    dependencies = get_project_dependencies()
    
    if package not in dependencies:
        click.echo(click.style(f'❌ 依赖 {package} 不存在于项目配置中', fg='red'))
        return
        
    # 从配置中删除依赖
    if remove_dependency(package):
        click.echo(click.style(f'✅ 依赖 {package} 已从项目配置中移除', fg='green'))
    else:
        click.echo(click.style(f'❌ 移除依赖 {package} 失败', fg='red'))
        return
    
    # 如果指定了卸载选项，则卸载包
    if uninstall:
        click.echo(click.style(f'🗑️  正在卸载 {package}...', fg='cyan'))
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'uninstall', '-y', package])
            click.echo(click.style(f'✅ {package} 卸载成功！', fg='green', bold=True))
        except subprocess.CalledProcessError:
            click.echo(click.style(f'❌ {package} 卸载失败', fg='red', bold=True))

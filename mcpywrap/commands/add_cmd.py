# -*- coding: utf-8 -*-

"""
安装依赖命令模块
"""
import click
import subprocess
import sys
from ..config import config_exists, add_dependency, get_project_dependencies
from ..utils.pip_error_parser import display_pip_error, suggest_common_fixes

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
        # 捕获pip输出以便进行错误分析
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', package],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        )
        click.echo(click.style(f'✅ {package} 安装成功！', fg='green', bold=True))
    except subprocess.CalledProcessError as e:
        click.echo(click.style(f'❌ 依赖包 {package} 安装失败', fg='red', bold=True))
        
        # 显示友好的错误信息
        error_output = e.stderr if e.stderr else e.stdout
        display_pip_error(error_output, show_raw_output=False)
        
        # 询问是否显示详细错误信息
        if click.confirm(click.style("❓ 是否查看详细错误信息以便调试？", fg="magenta"), default=False):
            click.echo()
            click.echo(click.style("📋 完整错误输出:", fg='cyan', bold=True))
            click.echo(click.style("-" * 40, fg='cyan'))
            if e.stderr:
                click.echo("STDERR:")
                click.echo(e.stderr)
            if e.stdout:
                click.echo("STDOUT:")
                click.echo(e.stdout)
            click.echo(click.style("-" * 40, fg='cyan'))
        
        # 显示通用解决建议
        suggest_common_fixes()
        
        click.echo(click.style(f'💡 您可以尝试手动运行: pip install {package}', fg='yellow'))

# -*- coding: utf-8 -*-

"""
删除依赖命令模块
"""
import click
import subprocess
import sys
from ..config import config_exists, remove_dependency, get_project_dependencies
from ..utils.pip_error_parser import display_pip_error, suggest_common_fixes

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
            # 捕获pip输出以便进行错误分析
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'uninstall', '-y', package],
                capture_output=True,
                text=True,
                encoding='utf-8',
                check=True
            )
            click.echo(click.style(f'✅ {package} 卸载成功！', fg='green', bold=True))
        except subprocess.CalledProcessError as e:
            click.echo(click.style(f'❌ 依赖包 {package} 卸载失败', fg='red', bold=True))
            
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
            
            click.echo(click.style(f'💡 您可以尝试手动运行: pip uninstall {package}', fg='yellow'))

# -*- coding: utf-8 -*-

"""
发布命令模块
"""
import click
from ..config import read_config, config_exists
from ..utils.utils import run_command

@click.command()
def publish_cmd():
    """发布项目到 PyPI"""
    if not config_exists():
        click.echo('错误: 未找到配置文件。请先运行 `mcpywrap init` 初始化项目。')
        return
    
    config = read_config()
    project_name = config.get('project_name')
    
    if not project_name:
        click.echo('错误: 配置文件中缺少项目名称。请重新运行 `mcpywrap init`。')
        return
    
    click.echo('准备发布项目到 PyPI...')
    
    # 构建分发包
    click.echo('正在构建分发包...')
    success, output = run_command(['python', 'setup.py', 'sdist', 'bdist_wheel'])
    
    if not success:
        click.echo(f'构建分发包失败: {output}')
        return
    
    # 使用 twine 上传到 PyPI
    if click.confirm('是否上传到 PyPI？', default=True):
        click.echo('正在上传到 PyPI...')
        success, output = run_command(['twine', 'upload', 'dist/*'])
        
        if success:
            click.echo(f'发布成功！项目 {project_name} 已上传到 PyPI。')
        else:
            click.echo(f'上传失败: {output}')
            click.echo('提示: 确保你已经注册了 PyPI 账户，并正确配置了 ~/.pypirc 文件。')
    else:
        click.echo('已取消上传。')

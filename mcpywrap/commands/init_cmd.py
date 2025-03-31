# -- coding: utf-8 -*-

"""
初始化命令模块
"""
import os
import click
from ..config import update_config, config_exists
from ..utils.utils import ensure_dir
from ..minecraft.addons import setup_minecraft_addon, is_minecraft_addon_project
from ..utils.project_setup import (
    get_default_author, get_default_email, get_default_project_name, find_behavior_pack_dir,
    update_behavior_pack_config, install_project_dev_mode
)


@click.command()
def init_cmd():
    """交互式初始化项目，创建基础的包信息及配置"""
    init()

def init():
    if config_exists():
        if not click.confirm(click.style('⚠️  配置文件已存在，是否覆盖？', fg='yellow', bold=True), default=False):
            click.echo(click.style('🚫 初始化已取消', fg='red'))
            return

    click.echo(click.style('🎉 欢迎使用 mcpywrap 初始化向导！', fg='bright_green', bold=True))

    # 获取项目信息（仅提示必要信息）
    default_project_name = get_default_project_name()
    project_name = click.prompt(click.style('📦 请输入项目名称', fg='cyan'), default=default_project_name, type=str, show_default=True)
    project_version = click.prompt(click.style('🔢 请输入项目版本', fg='cyan'), default='0.1.0', type=str)
    project_description = click.prompt(click.style('📝 请输入项目描述', fg='cyan'), default='', type=str)
    
    # 自动获取作者信息
    default_author = get_default_author()
    author = click.prompt(click.style('👤 请输入作者名称', fg='cyan'), default=default_author, type=str, show_default=True)
    
    # 显示高级选项标题
    if click.confirm(click.style('❓ 是否配置高级项目设置？（包括邮箱、URL、许可证、Python版本要求等）', fg='magenta'), default=False):
        default_email = get_default_email()
        author_email = click.prompt(click.style('📧 请输入作者邮箱', fg='cyan'), default=default_email, type=str, show_default=True)
        project_url = click.prompt(click.style('🔗 请输入项目URL', fg='cyan'), default='', type=str)
        license_name = click.prompt(click.style('📜 请输入许可证类型', fg='cyan'), default='MIT', type=str)
        python_requires = click.prompt(click.style('🐍 请输入Python版本要求', fg='cyan'), default='>=3.6', type=str)
        
        # 获取依赖列表
        dependencies = []
        click.echo(click.style('📚 请输入项目依赖包（其他需要打包到入此项目的mcpywrap项目），每行一个（输入空行结束）:', fg='cyan'))
        while True:
            dep = click.prompt(click.style('➕ 依赖', fg='bright_blue'), default='', show_default=False)
            if not dep:
                break
            dependencies.append(dep)
    else:
        # 设置默认值
        author_email = get_default_email()
        project_url = ''
        license_name = 'MIT'
        python_requires = '>=3.6'
        dependencies = []
    
    base_dir = os.getcwd()
    behavior_pack_dir = None
    minecraft_addon_info = {}
    target_dir = None
    
    # 检查是否为Minecraft addon项目
    if is_minecraft_addon_project(base_dir):
        click.echo(click.style('🔍 检测到已有Minecraft addon项目结构', fg='magenta'))
        behavior_pack_dir = find_behavior_pack_dir(base_dir)
        if behavior_pack_dir:
            click.echo(click.style(f'✅ 找到行为包目录: {behavior_pack_dir}', fg='green'))
        else:
            click.echo(click.style('⚠️ 无法找到行为包目录', fg='yellow'))
    else:
        if click.confirm(click.style('❓ 是否创建Minecraft addon 基础框架？', fg='magenta'), default=True):
            click.echo(click.style('🧱 正在创建Minecraft addon 基础框架...', fg='magenta'))
            minecraft_addon_info = setup_minecraft_addon(
                base_dir, 
                project_name, 
                project_description, 
                project_version
            )
            click.echo(click.style('✅ Minecraft Addon 基础框架创建成功！', fg='green'))
            click.echo(click.style(f'📂 资源包: {minecraft_addon_info["resource_pack"]["path"]}', fg='green'))
            click.echo(click.style(f'📂 行为包: {minecraft_addon_info["behavior_pack"]["path"]}', fg='green'))
            behavior_pack_dir = minecraft_addon_info["behavior_pack"]["path"]

    if behavior_pack_dir and click.confirm(click.style('❓ 是否配置构建目标目录？（指定生成的脚本文件应安装到的位置）', fg='magenta'), default=False):
        target_dir = click.prompt(click.style('📂 请输入目标目录', fg='cyan'), default=behavior_pack_dir, type=str)
        ensure_dir(target_dir)
    
    # 构建符合 PEP 621 标准的配置
    config = {
        'build-system': {
            'requires': ["setuptools>=42", "wheel"],
            'build-backend': "setuptools.build_meta"
        },
        'project': {
            'name': project_name,
            'version': project_version,
            'description': project_description,
            'authors': [{'name': author}],
            'readme': "README.md",
            'requires-python': python_requires,
            'license': {'text': license_name},
            'classifiers': [
                f"License :: OSI Approved :: {license_name} License",
                "Programming Language :: Python",
                "Programming Language :: Python :: 3",
            ]
        }
    }
    
    if author_email:
        if not config['project'].get('authors'):
            config['project']['authors'] = []
        if not config['project']['authors']:
            config['project']['authors'].append({'name': author, 'email': author_email})
        else:
            config['project']['authors'][0]['email'] = author_email
    
    if project_url:
        config['project']['urls'] = {'Homepage': project_url}
    
    if dependencies:
        config['project']['dependencies'] = dependencies
    
    # 更新行为包配置
    rel_path = update_behavior_pack_config(config, base_dir, behavior_pack_dir, target_dir)
    if behavior_pack_dir:
        click.echo(click.style(f'📦 已配置自动包发现于: {rel_path}', fg='green'))
    
    update_config(config)
    click.echo(click.style('✅ 初始化完成！配置文件已更新到 pyproject.toml', fg='green'))
    
    # 使用pip安装项目（可编辑模式）
    if click.confirm(click.style('❓ 是否立即安装项目到开发环境？（使用pip install -e .命令）', fg='magenta'), default=True):
        if install_project_dev_mode():
            click.echo(click.style('🚀 现在你可以开始编写Minecraft Python脚本了！', fg='bright_green', bold=True))

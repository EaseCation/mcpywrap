# -*- coding: utf-8 -*-

"""
初始化命令模块
"""
import os
import click
from pathlib import Path
from ..config import update_config, config_exists
from ..utils.utils import ensure_dir
from ..minecraft.addons import setup_minecraft_addon, is_minecraft_addon_project
from ..utils.print_guide import print_guide
from ..utils.project_setup import (
    get_default_author, get_default_email, get_default_project_name, find_behavior_pack_dir,
    update_behavior_pack_config, install_project_dev_mode
)
from ..minecraft.template.mod_template import open_ui_crate_mod


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
    else:
        # 设置默认值
        author_email = get_default_email()
        project_url = ''
        license_name = 'MIT'
        python_requires = '>=3.6'

    # 获取依赖列表
        dependencies = []
        click.echo(click.style('📚 请输入项目依赖包（其他需要打包到入此项目的mcpywrap项目），每行一个（输入空行结束）:', fg='cyan'))
        while True:
            dep = click.prompt(click.style('➕ 依赖', fg='bright_blue'), default='', show_default=False)
            if not dep:
                break
            dependencies.append(dep)
    
    base_dir = os.getcwd()
    behavior_pack_dir = None
    minecraft_addon_info = {}
    target_dir = None
    
    # 检查是否为Minecraft addon项目
    if is_minecraft_addon_project(base_dir):
        click.echo(click.style('🔍 检测到已有 Minecraft Addon 项目结构', fg='magenta'))
        behavior_pack_dir = find_behavior_pack_dir(base_dir)
        if behavior_pack_dir:
            click.echo(click.style(f'✅ 找到行为包目录: {behavior_pack_dir}', fg='green'))
        else:
            click.echo(click.style('⚠️ 无法找到行为包目录', fg='yellow'))
    else:
        if click.confirm(click.style('❓ 是否创建 Minecraft addon 基础框架？', fg='magenta'), default=True):
            click.echo(click.style('🧱 正在创建 Minecraft addon 基础框架...', fg='magenta'))
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

    # 检查行为包中是否有任意Python包
    if behavior_pack_dir:
        if not any(file.endswith('.py') for file in os.listdir(behavior_pack_dir)):
            if click.confirm(click.style('⚠️ 是否使用模板创建 Mod 基础 Python 脚本框架？', fg='yellow'), default=True):
                open_ui_crate_mod(behavior_pack_dir)

    # 构建目录
    target_dir = click.prompt(click.style('📂 默认构建目录', fg='cyan'), default='./build', type=str)
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
            'dependencies': dependencies,
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
    
    # 更新行为包配置
    rel_path = update_behavior_pack_config(config, base_dir, behavior_pack_dir, target_dir)
    if behavior_pack_dir:
        click.echo(click.style(f'📦 已配置自动包发现于: {rel_path}', fg='green'))
    
    update_config(config)
    click.echo(click.style('✅ 初始化完成！配置文件已更新到 pyproject.toml', fg='green'))
    
    # 使用pip安装项目（可编辑模式）
    install_project_dev_mode()

    # 创建.gitignore文件
    if click.confirm(click.style('❓ 是否创建.gitignore文件？（包含Python和构建目录的忽略项）', fg='magenta'), default=True):
        gitignore_content = """# Python相关
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# 虚拟环境
.env
.venv
venv/
ENV/
env.bak/
venv.bak/

# IDE相关
.idea/
.vscode/
*.swp
*.swo
.mcs
studio.json
work.mcscfg

# Minecraft Addon 构建目录
/build/
"""
        gitignore_path = Path(base_dir) / '.gitignore'
        if gitignore_path.exists():
            if click.confirm(click.style('⚠️  .gitignore文件已存在，是否覆盖？', fg='yellow'), default=False):
                gitignore_path.write_text(gitignore_content)
                click.echo(click.style('✅ .gitignore文件已更新！', fg='green'))
        else:
            gitignore_path.write_text(gitignore_content)
            click.echo(click.style('✅ .gitignore文件已创建！', fg='green'))

    # 指令使用指南
    print_guide()
# -*- coding: utf-8 -*-

"""
初始化命令模块
"""
import os
import click
import time
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.markdown import Markdown
from rich.tree import Tree
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.syntax import Syntax
from rich.style import Style
from rich.columns import Columns
from rich.text import Text

from ..config import update_config, config_exists
from ..utils.utils import ensure_dir
from ..minecraft.addons import setup_minecraft_addon, is_minecraft_addon_project
from ..minecraft.map import setup_minecraft_map, is_minecraft_map_project
from ..utils.print_guide import print_guide
from ..utils.project_setup import (
    get_default_author, get_default_email, get_default_project_name, find_behavior_pack_dir,
    update_behavior_pack_config, install_project_dev_mode
)
from ..config import update_map_setuptools_config
from ..minecraft.template.mod_template import open_ui_crate_mod

# 创建控制台对象
console = Console()

@click.command()
def init_cmd():
    """交互式初始化项目，创建基础的包信息及配置"""
    init()

def init():
    # 显示欢迎横幅
    console.print(Panel.fit(
        "[bold yellow]欢迎使用 mcpywrap 初始化向导！[/]",
        border_style="green",
        padding=(1, 10),
        title="[bold cyan]🎮 Minecraft Python Wrapper[/]",
        subtitle="[blue]让包管理更轻松！[/]"
    ))
    
    # 检查配置是否存在
    if config_exists():
        if not Confirm.ask(
            "[yellow]⚠️  配置文件已存在，是否覆盖？[/]", 
            default=False, 
            console=console
        ):
            console.print("[bold red]🚫 初始化已取消[/]")
            return

    # 准备不同阶段的信息，便于管理
    stages = [
        "收集项目信息", 
        "配置高级项目设置", 
        "配置项目依赖", 
        "检测项目类型", 
        "创建项目结构", 
        "完成配置"
    ]
    
    # 初始化进度信息
    total_stages = len(stages)
    current_stage = 0
    
    # 创建项目信息存储变量
    project_info = {}
    
    # 第1阶段：收集基本项目信息
    current_stage += 1
    with Progress(
        SpinnerColumn(),
        TextColumn(f"[bold blue]({current_stage}/{total_stages}) {stages[current_stage-1]}"),
        console=console
    ) as progress:
        task = progress.add_task("准备中...", total=1)
        time.sleep(0.5)  # 视觉暂停
        progress.update(task, completed=1)
    
    # 显示项目信息表单标题
    console.print(Panel("[bold cyan]📝 项目基本信息[/]", border_style="blue"))
    
    # 获取项目信息
    default_project_name = get_default_project_name()
    project_name = Prompt.ask(
        "[cyan]📦 项目名称[/]", 
        default=default_project_name, 
        console=console
    )
    
    project_version = Prompt.ask(
        "[cyan]🔢 项目版本[/]", 
        default="0.1.0", 
        console=console
    )
    
    project_description = Prompt.ask(
        "[cyan]📝 项目描述[/]", 
        default="", 
        console=console
    )
    
    # 自动获取作者信息
    default_author = get_default_author()
    author = Prompt.ask(
        "[cyan]👤 作者名称[/]", 
        default=default_author, 
        console=console
    )

    project_info['name'] = project_name
    project_info['version'] = project_version
    project_info['description'] = project_description
    project_info['author'] = author
    
    # 第2阶段：高级项目设置
    current_stage += 1
    with Progress(
        SpinnerColumn(),
        TextColumn(f"[bold blue]({current_stage}/{total_stages}) {stages[current_stage-1]}"),
        console=console
    ) as progress:
        task = progress.add_task("准备中...", total=1)
        time.sleep(0.5)  # 视觉暂停
        progress.update(task, completed=1)
    
    # 创建高级选项表格
    advanced_table = Table(
        title="🔧 高级项目设置",
        border_style="blue",
        box=None,
        show_header=False,
        show_lines=False
    )
    advanced_table.add_column("选项", justify="right", style="cyan")
    advanced_table.add_column("说明", style="yellow")
    
    advanced_table.add_row("✉️  邮箱", "作者联系邮箱")
    advanced_table.add_row("🔗 项目URL", "项目主页链接")
    advanced_table.add_row("📜 许可证", "项目使用的开源许可证")
    advanced_table.add_row("🐍 Python版本", "支持的最低Python版本")
    
    console.print(advanced_table)
    
    if Confirm.ask(
        "[magenta]❓ 是否配置高级项目设置？[/]", 
        default=False, 
        console=console
    ):
        default_email = get_default_email()
        author_email = Prompt.ask(
            "[cyan]✉️  作者邮箱[/]", 
            default=default_email, 
            console=console
        )
        
        project_url = Prompt.ask(
            "[cyan]🔗 项目URL[/]", 
            default="", 
            console=console
        )
        
        license_name = Prompt.ask(
            "[cyan]📜 许可证类型[/]", 
            default="MIT", 
            console=console
        )
        
        python_requires = Prompt.ask(
            "[cyan]🐍 Python版本要求[/]", 
            default=">=3.6", 
            console=console
        )
    else:
        # 设置默认值
        author_email = get_default_email()
        project_url = ''
        license_name = 'MIT'
        python_requires = '>=3.6'
        console.print("[dim]已使用默认高级设置[/]")
    
    project_info['author_email'] = author_email
    project_info['url'] = project_url
    project_info['license'] = license_name
    project_info['python_requires'] = python_requires
    
    # 第3阶段：依赖配置
    current_stage += 1
    with Progress(
        SpinnerColumn(),
        TextColumn(f"[bold blue]({current_stage}/{total_stages}) {stages[current_stage-1]}"),
        console=console
    ) as progress:
        task = progress.add_task("准备中...", total=1)
        time.sleep(0.5)  # 视觉暂停
        progress.update(task, completed=1)
    
    # 获取依赖列表
    dependencies = []
    console.print(Panel(
        "[cyan]📚 请输入项目依赖包（每行一个，输入空行结束）\n"
        "支持其他mcpywrap项目作为依赖[/]",
        border_style="blue", 
        title="依赖配置"
    ))
    
    while True:
        dep = Prompt.ask("[bright_blue]➕ 依赖[/]", default="", console=console, show_default=False)
        if not dep:
            break
        dependencies.append(dep)
    
    if dependencies:
        # 显示已添加的依赖列表
        deps_tree = Tree("📦 [bold]项目依赖[/]")
        for dep in dependencies:
            deps_tree.add("[cyan]" + dep + "[/]")
        console.print(deps_tree)
    else:
        console.print("[dim]未添加任何依赖项[/]")
    
    project_info['dependencies'] = dependencies

    # 第4阶段：项目类型检测
    current_stage += 1
    with Progress(
        SpinnerColumn(),
        TextColumn(f"[bold blue]({current_stage}/{total_stages}) {stages[current_stage-1]}"),
        console=console
    ) as progress:
        task = progress.add_task("扫描项目结构...", total=1)
        
        base_dir = os.getcwd()
        # 自动检测项目类型
        is_map = is_minecraft_map_project(base_dir)
        is_addon = is_minecraft_addon_project(base_dir)
        
        progress.update(task, completed=1)
    
    behavior_pack_dir = None
    minecraft_addon_info = {}
    minecraft_map_info = {}
    target_dir = None
    project_type = "addon"  # 默认项目类型
    
    # 显示项目类型选择器
    project_type_table = Table(title="可用项目类型", border_style="green")
    project_type_table.add_column("选项", justify="center", style="cyan", width=6)
    project_type_table.add_column("类型", style="bright_blue")
    project_type_table.add_column("说明", style="white")
    
    project_type_table.add_row("1", "📦 插件 (Addon)", "创建Minecraft插件项目，包含行为包和资源包")
    project_type_table.add_row("2", "🗺️ 地图 (Map)", "创建Minecraft地图项目，包含世界存档")
    
    # 如果既不是地图也不是插件，则询问用户要创建的项目类型
    if not is_map and not is_addon:
        console.print(Panel(
            "[magenta]未检测到现有的Minecraft项目结构，请选择要创建的项目类型[/]",
            border_style="yellow"
        ))
        console.print(project_type_table)
        
        choice = Prompt.ask(
            "[bright_magenta]👉 请选择项目类型[/]",
            choices=["1", "2"],
            default="1", 
            console=console
        )
        
        project_type = "addon" if choice == "1" else "map"
        console.print(f"[green]已选择: [bold]{'📦 插件项目' if project_type == 'addon' else '🗺️ 地图项目'}[/][/]")
    elif is_map:
        project_type = "map"
        console.print("[magenta]🔍 检测到已有 Minecraft Map 项目结构[/]")
    elif is_addon:
        project_type = "addon"
        console.print("[magenta]🔍 检测到已有 Minecraft Addon 项目结构[/]")
    
    project_info['project_type'] = project_type
    
    # 第5阶段：根据项目类型创建相应结构
    current_stage += 1
    console.print(f"[bold blue]({current_stage}/{total_stages}) {stages[current_stage-1]}[/]")
    
    if project_type == "map":
        if is_map:
            console.print(Panel("[green]✅ 已检测到地图存档结构[/]", border_style="green"))
        else:
            if Confirm.ask(
                "[magenta]❓ 是否创建 Minecraft 地图存档基础框架？[/]", 
                default=True, 
                console=console
            ):
                # 游戏模式选择表格
                game_mode_table = Table(title="游戏模式", border_style="blue")
                game_mode_table.add_column("选项", justify="center", style="cyan", width=6)
                game_mode_table.add_column("模式", style="bright_blue")
                game_mode_table.add_column("说明", style="white")
                
                game_mode_table.add_row("1", "🏠 生存模式", "需要收集资源和生存")
                game_mode_table.add_row("2", "🎨 创造模式", "无限资源和飞行能力")
                game_mode_table.add_row("3", "🔍 冒险模式", "限制破坏，适合冒险地图")
                
                console.print(game_mode_table)
                
                game_choice = Prompt.ask(
                    "[bright_magenta]👉 请选择游戏模式[/]",
                    choices=["1", "2", "3"],
                    default="1", 
                    console=console
                )
                
                # 将选择映射到游戏模式ID
                game_type = int(game_choice) - 1
                
                with Progress(
                    SpinnerColumn(), 
                    TextColumn("[cyan]创建地图框架中...[/]"), 
                    console=console
                ) as map_progress:
                    map_task = map_progress.add_task("创建中", total=1)
                    
                    minecraft_map_info = setup_minecraft_map(
                        base_dir,
                        project_name,
                        project_description,
                        game_type
                    )
                    
                    map_progress.update(map_task, advance=1)
                
                console.print(Panel.fit(
                    f"[green]✅ Minecraft 地图存档基础框架创建成功！\n"
                    f"[cyan]📂 地图路径: [bold white]{minecraft_map_info['map_path']}[/][/]",
                    border_style="green",
                    title="地图创建成功"
                ))
    else:  # project_type == "addon"
        # 检查是否为Minecraft addon项目
        if is_minecraft_addon_project(base_dir):
            console.print("[magenta]🔍 检测到已有 Minecraft Addon 项目结构[/]")
            behavior_pack_dir = find_behavior_pack_dir(base_dir)
            if behavior_pack_dir:
                console.print(f"[green]✅ 找到行为包目录: [bold white]{behavior_pack_dir}[/][/]")
            else:
                console.print("[yellow]⚠️ 无法找到行为包目录[/]")
        else:
            if Confirm.ask(
                "[magenta]❓ 是否创建 Minecraft addon 基础框架？[/]", 
                default=True, 
                console=console
            ):
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[cyan]创建插件框架中...[/]"), 
                    console=console
                ) as addon_progress:
                    addon_task = addon_progress.add_task("创建中", total=1)
                    
                    minecraft_addon_info = setup_minecraft_addon(
                        base_dir, 
                        project_name, 
                        project_description, 
                        project_version
                    )
                    
                    addon_progress.update(addon_task, advance=1)
                
                console.print(Panel.fit(
                    f"[green]✅ Minecraft Addon 基础框架创建成功！\n"
                    f"[cyan]📂 资源包: [bold white]{minecraft_addon_info['resource_pack']['path']}[/]\n"
                    f"📂 行为包: [bold white]{minecraft_addon_info['behavior_pack']['path']}[/][/]",
                    border_style="green",
                    title="插件创建成功"
                ))
                
                behavior_pack_dir = minecraft_addon_info["behavior_pack"]["path"]

        # 检查行为包中是否有任意Python包
        if behavior_pack_dir:
            if not any(file.endswith('.py') for file in os.listdir(behavior_pack_dir)):
                if Confirm.ask(
                    "[yellow]⚠️ 是否使用模板创建 Mod 基础 Python 脚本框架？[/]", 
                    default=True, 
                    console=console
                ):
                    with Progress(
                        SpinnerColumn(),
                        TextColumn("[cyan]创建Python模板...[/]"), 
                        console=console
                    ) as py_progress:
                        py_task = py_progress.add_task("创建中", total=1)
                        open_ui_crate_mod(behavior_pack_dir)
                        py_progress.update(py_task, advance=1)
                    
                    console.print("[green]✅ 已创建基础Python脚本模板[/]")
    
    # 第6阶段: 完成配置
    current_stage += 1
    with Progress(
        SpinnerColumn(),
        TextColumn(f"[bold blue]({current_stage}/{total_stages}) {stages[current_stage-1]}"),
        console=console
    ) as progress:
        task = progress.add_task("准备中...", total=1)
        time.sleep(0.5)  # 视觉暂停
        progress.update(task, completed=1)
    
    # 构建目录
    target_dir = Prompt.ask(
        "[cyan]📂 默认构建目录[/]", 
        default='./build', 
        console=console
    )
    project_info['target_dir'] = target_dir
    
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
            'license': license_name,
            'classifiers': [
                "Programming Language :: Python",
                "Programming Language :: Python :: 3",
            ]
        },
        'tool': {
            'mcpywrap': {
                'project_type': project_type
            }
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
    
    # 根据项目类型配置 setuptools
    if project_type == "addon" and behavior_pack_dir:
        rel_path = update_behavior_pack_config(config, base_dir, behavior_pack_dir, target_dir)
        console.print(f"[green]📦 已配置自动包发现于: [bold white]{rel_path}[/][/]")
    elif project_type == "map":
        # 为 map 项目添加基本的 setuptools 配置，排除地图目录
        config.setdefault('tool', {})['setuptools'] = {
            'packages': {
                'find': {
                    'exclude': ["behavior_packs*", "resource_packs*", "db*"]
                }
            }
        }
    
    # 创建.gitignore文件
    if Confirm.ask(
        "[magenta]❓ 是否创建.gitignore文件？（包含Python和构建目录的忽略项）[/]", 
        default=True, 
        console=console
    ):
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
.runtime/
"""
        gitignore_path = Path(base_dir) / '.gitignore'
        if gitignore_path.exists():
            if Confirm.ask(
                "[yellow]⚠️ .gitignore文件已存在，是否覆盖？[/]", 
                default=False, 
                console=console
            ):
                gitignore_path.write_text(gitignore_content, encoding='utf-8')
                console.print("[green]✅ .gitignore文件已更新！[/]")
        else:
            gitignore_path.write_text(gitignore_content, encoding='utf-8')
            console.print("[green]✅ .gitignore文件已创建！[/]")
    
    update_config(config)
    
    # 显示项目结构树
    console.print("\n[bold cyan]📂 项目结构预览:[/]")
    project_structure = create_project_structure_tree(base_dir, project_type, behavior_pack_dir)
    console.print(project_structure)
    
    # 安装项目
    console.print(Panel.fit(
        "[cyan]正在以开发模式安装项目...[/]",
        border_style="blue",
        title="🔧 安装"
    ))
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]安装项目中...[/]"), 
        console=console
    ) as install_progress:
        install_task = install_progress.add_task("安装中", total=1)
        install_project_dev_mode()
        install_progress.update(install_task, completed=1)
    
    # 为 map 项目自动扫描和配置 behavior_packs
    if project_type == "map":
        console.print("\n[cyan]🔍 扫描 behavior_packs 目录...[/]")
        update_map_setuptools_config(interactive=False)
    
    # 总结
    console.print(Panel.fit(
        f"[bold green]✅ 初始化完成！[/]\n\n"
        f"[cyan]项目信息:[/]\n"
        f"• 名称: [bold]{project_name}[/]\n"
        f"• 类型: [bold]{'🗺️ 地图存档' if project_type == 'map' else '📦 插件项目'}[/]\n"
        f"• 版本: [bold]{project_version}[/]\n"
        f"• 构建目录: [bold]{target_dir}[/]\n\n"
        f"配置文件已更新到 [bold]pyproject.toml[/]",
        border_style="green",
        title="🎉 完成",
        subtitle="使用 `mcpywrap run` 运行项目"
    ))
    
    # 指令使用指南
    print_guide()

def create_project_structure_tree(base_dir, project_type, behavior_pack_dir=None):
    """创建并返回项目结构树"""
    tree = Tree(
        f"[bold yellow]{Path(base_dir).name}[/]",
        guide_style="dim"
    )
    
    # 最多遍历3层目录，避免树形结构过大
    def add_directory(path, tree_node, depth=0):
        if depth > 2:  # 限制深度
            tree_node.add("[dim]...[/]")
            return
            
        for item in sorted(Path(path).iterdir()):
            if item.name.startswith('.') or item.name == "__pycache__" or item.name == "build":
                continue
                
            if item.is_dir():
                branch = tree_node.add(f"[bold blue]{item.name}/[/]")
                add_directory(item, branch, depth + 1)
            else:
                if item.suffix == '.py':
                    tree_node.add(f"[green]{item.name}[/]")
                elif item.suffix in ['.json', '.yaml', '.toml']:
                    tree_node.add(f"[yellow]{item.name}[/]")
                elif item.suffix in ['.md', '.txt']:
                    tree_node.add(f"[cyan]{item.name}[/]")
                else:
                    tree_node.add(f"[dim]{item.name}[/]")
    
    # 添加特定文件的高亮
    pyproject = tree.add("[bold magenta]pyproject.toml[/] [dim](配置文件)[/]")
    
    # 添加目录结构
    add_directory(base_dir, tree)
    
    return tree
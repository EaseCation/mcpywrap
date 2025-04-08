# -*- coding: utf-8 -*-

"""
项目运行命令模块
"""

import click
import os
import json
import uuid
import shutil
import time
from datetime import datetime

from ..builders import DependencyManager
from ..config import config_exists, read_config, get_project_dependencies, get_project_type, get_project_name
from ..builders.AddonsPack import AddonsPack
from ..mcstudio.game import open_game, open_safaia
from ..mcstudio.mcs import *
from ..mcstudio.runtime_cppconfig import gen_runtime_config
from ..mcstudio.studio_server_ui import run_studio_server_ui_subprocess
from ..mcstudio.symlinks import setup_global_addons_symlinks, setup_map_packs_symlinks
from ..utils.project_setup import find_and_configure_behavior_pack
from ..utils.utils import ensure_dir
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.tree import Tree
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

# 创建控制台对象
console = Console()

base_dir = os.getcwd()


# 实例管理助手函数
def _get_all_instances():
    """获取所有运行实例信息"""
    runtime_dir = os.path.join(base_dir, ".runtime")
    if not os.path.exists(runtime_dir):
        return []
    
    instances = []
    for file in os.listdir(runtime_dir):
        if file.endswith('.cppconfig'):
            file_path = os.path.join(runtime_dir, file)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    level_id = config.get('world_info', {}).get('level_id')
                    if level_id:
                        creation_time = os.path.getctime(file_path)
                        instances.append({
                            'level_id': level_id,
                            'config_path': file_path,
                            'creation_time': creation_time,
                            'name': config.get('world_info', {}).get('name', '未命名')
                        })
            except:
                continue
    
    # 按创建时间排序，最新的在前
    instances.sort(key=lambda x: x['creation_time'], reverse=True)
    return instances

def _get_latest_instance():
    """获取最新的运行实例"""
    instances = _get_all_instances()
    if instances:
        return instances[0]
    return None

def _match_instance_by_prefix(prefix):
    """通过前缀匹配实例"""
    if not prefix:
        return None
    
    instances = _get_all_instances()
    for instance in instances:
        if instance['level_id'].startswith(prefix):
            return instance
    return None

def _generate_new_instance_config(base_dir, project_name):
    """生成新的运行实例配置文件路径"""
    runtime_dir = os.path.join(base_dir, ".runtime")
    ensure_dir(runtime_dir)
    
    # 生成新的level_id
    level_id = str(uuid.uuid4())
    
    # 配置文件路径使用level_id作为名称
    config_path = os.path.join(runtime_dir, f"{level_id}.cppconfig")
    
    return level_id, config_path

def _setup_dependencies(project_name, base_dir):
    """设置项目依赖"""
    all_packs = []
    project_type = get_project_type()
    config = read_config()

    if project_type == 'addon':
        # 查找当前项目的行为包
        behavior_pack_dir, resource_pack_dir = find_and_configure_behavior_pack(base_dir, config)
        if not behavior_pack_dir:
            console.print("❌ 未找到行为包目录，请检查项目结构", style="red bold")
            return None
        # 创建主包实例
        main_pack = AddonsPack(project_name, base_dir, is_origin=True)
        all_packs.append(main_pack)

    # 解析依赖包
    dependency_manager = DependencyManager()
    dependencies = get_project_dependencies()

    if dependencies:
        with console.status("📦 正在解析依赖包...", spinner="dots"):
            # 构建依赖树
            dependency_manager.build_dependency_tree(
                project_name,
                base_dir,
                dependencies
            )

            # 获取所有依赖 - 修复可能的类型错误
            try:
                dependency_map = dependency_manager.get_all_dependencies()
                # 安全地处理返回结果，防止类型错误
                dependency_packs = []
                for dep in dependency_map.values():
                    dependency_packs.append(dep)
                
                if dependency_packs:
                    console.print(f"✅ 成功解析 {len(dependency_packs)} 个依赖包", style="green")

                    # 打印依赖树结构
                    console.print("📊 依赖关系:", style="cyan")
                    root_node = dependency_manager.get_dependency_tree()
                    if (root_node):
                        tree = Tree(f"[cyan]{root_node.name}[/] [bright_cyan](主项目)[/]")
                        _build_dependency_tree(root_node, tree)
                        console.print(tree)
                    
                    all_packs.extend(dependency_packs)
                else:
                    console.print("ℹ️ 没有找到可用的依赖包", style="cyan")
            except Exception as e:
                console.print(f"⚠️ 解析依赖时出错: {str(e)}", style="yellow")
                console.print("ℹ️ 将继续而不加载依赖包", style="yellow")
    else:
        console.print("ℹ️ 项目没有声明依赖包", style="cyan")

    return all_packs


def _build_dependency_tree(node, tree_node):
    """使用Rich的Tree构建依赖树"""
    for child in node.children:
        child_node = tree_node.add(f"[cyan]{child.name}[/]")
        _build_dependency_tree(child, child_node)


def _run_game_with_instance(config_path, level_id, all_packs):
    """使用指定的实例运行游戏"""
    project_type = get_project_type()
    project_name = get_project_name()
    
    # 获取MC Studio安装目录
    mcs_download_dir = get_mcs_download_path()
    if not mcs_download_dir:
        console.print("❌ 未找到MC Studio下载目录，请确保已安装MC Studio", style="red bold")
        return False

    # 获取游戏引擎版本
    engine_dirs = get_mcs_game_engine_dirs()
    if not engine_dirs:
        console.print("❌ 未找到MC Studio游戏引擎，请确保已安装MC Studio", style="red bold")
        return False
    
    # 获取游戏引擎数据目录
    engine_data_path = get_mcs_game_engine_data_path()

    # 使用最新版本的引擎
    latest_engine = engine_dirs[0]
    console.print(f"🎮 使用引擎版本: {latest_engine}", style="cyan")

    # 生成世界名称
    world_name = project_name

    # 使用Live组件显示整个设置过程
    with Live(auto_refresh=True, console=console) as live:
        # 设置软链接
        live.update(Text("🔄 正在设置软链接...", style="cyan"))
        link_suc, behavior_links, resource_links = setup_global_addons_symlinks(all_packs)

        if not link_suc:
            live.update(Text("❌ 软链接创建失败，请检查权限", style="red bold"))
            return False

        # 显示世界名称
        live.update(Text(f"🌍 世界名称: {world_name}", style="cyan"))

        # 生成运行时配置
        live.update(Text("📝 生成运行时配置中...", style="cyan"))
        runtime_config = gen_runtime_config(
            latest_engine,
            world_name,
            level_id,
            mcs_download_dir,
            project_name,
            behavior_links,
            resource_links
        )

        # 写入配置文件
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(runtime_config, f, ensure_ascii=False, indent=2)

        live.update(Text(f"📝 配置文件已生成: {os.path.basename(config_path)}", style="green"))

        # 地图存档创建
        if project_type == 'map':
            # 判断目标地图存档路径
            runtime_map_dir = os.path.join(engine_data_path, "minecraftWorlds", level_id)
            ensure_dir(runtime_map_dir)
            
            live.update(Text("🗺️ 正在准备地图存档...", style="cyan"))
            
            # 判断是否有level.dat，没有的话就复制
            level_dat_path = os.path.join(runtime_map_dir, "level.dat")
            if not os.path.exists(level_dat_path):
                origin_level_dat_path = os.path.join(base_dir, "level.dat")
                if os.path.exists(origin_level_dat_path):
                    shutil.copy2(origin_level_dat_path, level_dat_path)
                    live.update(Text(f"✓ 已复制level.dat文件", style="green"))
                
            level_db_dir = os.path.join(runtime_map_dir, "db")
            if not os.path.exists(level_db_dir) and os.path.exists(os.path.join(base_dir, "db")):
                shutil.copytree(os.path.join(base_dir, "db"), level_db_dir)
                live.update(Text(f"✓ 已复制db文件夹", style="green"))
                
            # 链接
            live.update(Text("🔗 正在设置地图软链接...", style="cyan"))
            setup_map_packs_symlinks(base_dir, level_id)

    # 启动游戏
    logging_port = 8678

    console.print(f"🚀 正在启动游戏实例: {level_id[:8]}...", style="bright_blue bold")
    
    with console.status("启动游戏中...", spinner="dots"):
        game_process = open_game(config_path, logging_port=logging_port)

    if game_process is None:
        console.print("❌ 游戏启动失败", style="red bold")
        return False

    # 启动studio_logging_server
    run_studio_server_ui_subprocess(port=logging_port)

    # 启动日志与调试工具
    open_safaia()

    # 等待游戏进程结束
    console.print("✨ 游戏已启动，正在运行中...", style="bright_green bold")
    console.print("⏱️ 按 Ctrl+C 可以中止等待", style="yellow")

    try:
        # 等待游戏进程结束
        game_process.wait()
        console.print("👋 游戏已退出", style="bright_cyan bold")
    except KeyboardInterrupt:
        # 捕获 Ctrl+C，但不终止游戏进程
        console.print("\n🛑 收到中止信号，脚本将退出但游戏继续运行", style="yellow")
    
    return True


@click.command()
@click.option('--new', '-n', is_flag=True, help='创建新的游戏实例')
@click.option('--list', '-l', is_flag=True, help='列出所有可用的游戏实例')
@click.option('--delete', '-d', help='删除指定的游戏实例 (输入实例ID前缀)')
@click.option('--force', '-f', is_flag=True, help='强制删除，不提示确认')
@click.option('--clean-all', is_flag=True, help='清空所有游戏实例')
@click.option('--ui', is_flag=True, help='使用图形界面进行操作')
@click.argument('instance_prefix', required=False)
def run_cmd(new, list, delete, force, clean_all, instance_prefix, ui):
    """游戏实例运行与管理
    
    可直接运行 'mcpy run' 启动最新实例，或使用选项管理实例
    """
    # 启动图形界面
    if ui:
        from ..ui.run_ui import show_run_ui
        # 显示图形界面
        show_run_ui(base_dir)
        return
        
    # 检查项目是否已初始化
    if not config_exists():
        console.print("❌ 项目尚未初始化，请先运行 mcpy init", style="red bold")
        return

    project_name = get_project_name()
    
    # 创建运行时配置目录
    runtime_dir = os.path.join(base_dir, ".runtime")
    ensure_dir(runtime_dir)

    # 清空所有实例
    if clean_all:
        _clean_all_instances(force)
        return

    # 列出所有实例
    if list:
        _list_instances()
        return
    
    # 删除指定实例
    if delete:
        _delete_instance(delete, force)
        return

    # 设置依赖
    all_packs = _setup_dependencies(project_name, base_dir)
    if all_packs is None:
        return

    # 确定要使用的实例
    config_path = None
    level_id = None
    
    if new:
        # 创建新实例
        level_id, config_path = _generate_new_instance_config(base_dir, project_name)
        console.print(f"🆕 创建新实例: {level_id[:8]}...", style="green")
    elif instance_prefix:
        # 通过前缀查找实例
        instance = _match_instance_by_prefix(instance_prefix)
        if instance:
            level_id = instance['level_id']
            config_path = instance['config_path']
            console.print(f"🔍 使用实例: {level_id[:8]}...", style="green")
        else:
            console.print(f"❌ 未找到前缀为 \"{instance_prefix}\" 的实例", style="red")
            instances = _get_all_instances()
            if instances:
                console.print("💡 可用实例:", style="yellow")
                
                table = Table(show_header=False, box=None)
                for i, inst in enumerate(instances):
                    if i < 5:  # 只显示前5个
                        table.add_row("   -", f"{inst['level_id'][:8]}")
                    else:
                        table.add_row("   ...", f"还有 {len(instances) - 5} 个实例")
                        break
                
                console.print(table)
                console.print("💡 使用 \"mcpy run -l\" 查看所有实例", style="yellow")
            return
    else:
        # 使用最新实例，如果没有则创建新实例
        latest_instance = _get_latest_instance()
        if latest_instance:
            level_id = latest_instance['level_id']
            config_path = latest_instance['config_path']
            console.print(f"📅 使用最新实例: {level_id[:8]}...", style="green")
        else:
            # 只有在找不到任何现有实例时才创建新实例
            level_id, config_path = _generate_new_instance_config(base_dir, project_name)
            console.print(f"🆕 创建首个实例: {level_id[:8]}...", style="green")
            console.print("💡 下次运行将重用此实例，若需创建新实例请使用 \"--new\" 参数", style="yellow")

    # 运行游戏
    _run_game_with_instance(config_path, level_id, all_packs)


def _list_instances():
    """列出所有可用的游戏实例"""
    instances = _get_all_instances()
    
    if not instances:
        console.print("📭 没有找到任何游戏实例", style="yellow")
        return
    
    # 创建漂亮的表格展示实例列表
    table = Table(title="📋 可用游戏实例列表", title_style="bright_cyan")
    table.add_column("状态", style="cyan", no_wrap=True)
    table.add_column("ID预览", style="cyan", no_wrap=True)
    table.add_column("创建时间", style="cyan")
    table.add_column("世界名称", style="cyan")
    
    for i, instance in enumerate(instances):
        creation_time = datetime.fromtimestamp(instance['creation_time'])
        time_str = creation_time.strftime('%Y-%m-%d %H:%M:%S')
        
        status = "📌" if i == 0 else ""
        level_id = instance['level_id']
        # 只显示前8个字符，方便引用
        short_id = level_id[:8]
        
        row_style = "bright_green" if i == 0 else "green"
        table.add_row(status, short_id, time_str, instance['name'], style=row_style)
    
    console.print(table)
    
    # 使用Panel组件显示提示
    tips = Panel(
        "[cyan]💡 提示:[/]\n"
        "• 使用 [green]'mcpy run <实例ID前缀>'[/] 运行特定实例\n"
        "• 使用 [green]'mcpy run -n'[/] 创建新实例\n"
        "• 使用 [green]'mcpy run -d <实例ID前缀>'[/] 删除实例",
        title="帮助", border_style="cyan"
    )
    console.print(tips)


def _delete_instance(instance_prefix, force):
    """删除指定的游戏实例"""
    instance = _match_instance_by_prefix(instance_prefix)
    
    if not instance:
        console.print(f"❌ 未找到前缀为 \"{instance_prefix}\" 的实例", style="red")
        return
    
    level_id = instance['level_id']
    config_path = instance['config_path']
    
    if not force:
        console.print(f"即将删除实例: {level_id[:8]} ({instance['name']})", style="yellow")
        confirmation = click.confirm('确定要删除吗?', abort=True)
    
    with console.status(f"正在删除实例 {level_id[:8]}...", spinner="dots"):
        try:
            # 删除配置文件
            if os.path.exists(config_path):
                os.remove(config_path)
                
            # 获取游戏引擎数据目录
            engine_data_path = get_mcs_game_engine_data_path()
            
            # 删除游戏世界目录
            world_dir = os.path.join(engine_data_path, "minecraftWorlds", level_id)
            if os.path.exists(world_dir):
                console.log(f"🗑️ 正在删除游戏存档: {world_dir}")
                shutil.rmtree(world_dir, ignore_errors=True)
            else:
                console.log(f"ℹ️ 未找到对应的游戏存档")
        
        except Exception as e:
            console.print(f"❌ 删除实例时出错: {str(e)}", style="red")
            return
    
    console.print(f"✅ 成功删除实例: {level_id[:8]}", style="green")


def _clean_all_instances(force):
    """清空所有游戏实例"""
    instances = _get_all_instances()
    
    if not instances:
        console.print("📭 没有找到任何游戏实例", style="yellow")
        return
    
    count = len(instances)
    
    if not force:
        warning = Panel(
            f"即将删除所有 {count} 个游戏实例!\n"
            "此操作将删除所有实例配置及对应的游戏存档，且不可恢复!",
            title="⚠️ 警告", border_style="bright_red", title_align="left"
        )
        console.print(warning)
        
        # 二次确认
        confirmation1 = click.confirm('确定要继续吗?', default=False)
        if not confirmation1:
            console.print("操作已取消", style="green")
            return
            
        confirmation2 = click.confirm('⚠️ 最后确认: 真的要删除所有实例吗?', default=False)
        if not confirmation2:
            console.print("操作已取消", style="green")
            return
    
    # 开始删除所有实例
    with Progress(
        SpinnerColumn(),
        TextColumn("[yellow]正在删除游戏实例... {task.completed}/{task.total}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        delete_task = progress.add_task("删除", total=len(instances))
        
        success_count = 0
        fail_count = 0
        
        for instance in instances:
            try:
                level_id = instance['level_id']
                config_path = instance['config_path']
                
                progress.update(delete_task, description=f"删除 {level_id[:8]}")
                
                # 删除配置文件
                if os.path.exists(config_path):
                    os.remove(config_path)
                    
                # 获取游戏引擎数据目录
                engine_data_path = get_mcs_game_engine_data_path()
                
                # 删除游戏世界目录
                world_dir = os.path.join(engine_data_path, "minecraftWorlds", level_id)
                if os.path.exists(world_dir):
                    shutil.rmtree(world_dir, ignore_errors=True)
                    
                success_count += 1
            except Exception as e:
                fail_count += 1
                if not force:  # 在非强制模式下显示错误
                    progress.console.print(f"❌ 删除实例 {instance['level_id'][:8]} 时出错: {str(e)}", style="red")
            
            progress.advance(delete_task)
    
    # 报告结果
    if success_count == count:
        console.print(f"✅ 已成功删除所有 {count} 个游戏实例", style="green bold")
    else:
        console.print(f"⚠️ 删除结果: 成功 {success_count} 个, 失败 {fail_count} 个", style="yellow bold")
        if fail_count > 0 and not force:
            console.print("💡 提示: 使用 \"--force\" 选项可以忽略错误继续删除", style="cyan")


def _print_dependency_tree(node, level):
    """打印依赖树结构"""
    indent = "  " * level
    if level == 0:
        click.secho(f"{indent}└─ {node.name} (主项目)", fg="bright_cyan")
    else:
        click.secho(f"{indent}└─ {node.name}", fg="cyan")

    for child in node.children:
        _print_dependency_tree(child, level + 1)
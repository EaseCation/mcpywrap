# -*- coding: utf-8 -*-

"""
项目运行命令模块
"""

import click
from ..command_context import OperationCommand, project_dir as current_project, non_interactive, require_project
import os
import json
import uuid
import shutil
from datetime import datetime

from ..builders import DependencyManager
from ..builders.MapPack import MapPack
from ..config import config_exists, read_config, get_project_dependencies, get_project_type, get_project_name, ensure_map_setuptools_sync
from ..builders.AddonsPack import AddonsPack
from ..mcstudio.game import open_game, open_safaia
from ..mcstudio.mcs import get_mcs_game_engine_data_path, is_windows
from ..mcstudio.runtime_cppconfig import gen_runtime_config
from ..mcstudio.discovery import discover_engines, require_resources, DiscoveryError, engine_options
from ..mcstudio.symlinks import setup_global_addons_symlinks
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



# 实例管理助手函数
def _get_all_instances(project_dir=None):
    """获取所有运行实例信息"""
    runtime_dir = os.path.join(project_dir or str(current_project()), ".runtime")
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

def _match_instance_by_prefix(prefix, project_dir=None):
    """通过前缀匹配实例"""
    if not prefix:
        return None
    
    instances = _get_all_instances(project_dir)
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

def _setup_dependencies(project_name, base_dir, raise_errors=False):
    """设置项目依赖"""
    from ..dependencies import DependencyService, DependencyError, addon_directories, read_project
    try:
        config = read_project(base_dir)
        project_type = config.get('tool', {}).get('mcpywrap', {}).get('project_type', 'addon')
        if project_type == 'addon':
            addon_directories(base_dir)
        manager = DependencyService(base_dir).resolve()
        packs = list(manager.get_all_dependencies().values())
        if project_type == 'addon':
            packs.append(manager.root_node.addon_pack)
        return packs
    except (DependencyError, OSError) as exc:
        if raise_errors:
            raise
        console.print(str(exc), style='red', markup=False)
        return None


def _build_dependency_tree(node, tree_node):
    """使用Rich的Tree构建依赖树"""
    for child in node.children:
        child_node = tree_node.add(f"[cyan]{child.name}[/]")
        _build_dependency_tree(child, child_node)


def _run_game_with_instance(config_path, level_id, all_packs, wait=True, log_callback=None,
                            engine_overrides=None, no_gui=False, logging_port=None, output_path=None):
    """使用指定的实例运行游戏
    
    Args:
        config_path: 配置文件路径
        level_id: 世界ID
        all_packs: 所有要加载的包
        wait: 是否等待游戏进程结束（默认为True）
        log_callback: 日志回调函数，格式为 log_callback(message, level)
    
    Returns:
        tuple: (成功状态, 游戏进程对象)
    """
    from pathlib import Path
    from ..dependencies import read_project
    project_dir = str(Path(config_path).resolve().parent.parent)
    config = read_project(project_dir)
    if 'server' in config.get('tool', {}).get('mcpywrap', {}):
        # GUI/旧会话也不能将网络目标误启动成本地世界。
        raise ValueError('服务器目标请通过 CLI mcpy run 启动，不能使用本地世界实例')
    project_type = config.get('tool', {}).get('mcpywrap', {}).get('project_type', 'addon')
    project_name = config.get('project', {}).get('name', 'project')
    all_packs = _setup_dependencies(project_name, project_dir)
    if all_packs is None:
        return False, None

    # 日志输出函数
    def log_message(message, level="normal"):
        if log_callback:
            log_callback(message, level)
        else:
            style = {
                "error": "red bold",
                "success": "green",
                "info": "cyan",
                "warning": "yellow"
            }.get(level, None)
            console.print(message, style=style, markup=False)
    
    # 在创建软链接或覆写实例前，固定引擎与资源路径。
    try:
        instance_version = None
        if os.path.isfile(config_path):
            with open(config_path, encoding='utf-8') as stream:
                instance_version = json.load(stream).get('version')
        discovery = discover_engines(project_dir, engine_overrides, instance_version)
        engine = discovery.require_engine()
        require_resources(engine)
    except (DiscoveryError, OSError, ValueError) as exc:
        log_message(str(exc) + '\n可运行 mcpy doctor 查看发现详情。', 'error')
        return False, None
    mcs_download_dir = engine.download_dir
    # 获取游戏引擎数据目录
    engine_data_path = get_mcs_game_engine_data_path()

    log_message(f"🎮 使用引擎版本: {engine.version} ({engine.source})", "info")

    # 生成世界名称
    world_name = project_name

    # 使用Live组件显示整个设置过程
    with Live(auto_refresh=True, console=console) as live:
        # 设置软链接
        live.update(Text("🔄 正在设置软链接...", "cyan"))
        log_message("🔄 正在设置软链接...", "info")
        link_suc, behavior_links, resource_links = setup_global_addons_symlinks(all_packs)

        if not link_suc:
            live.update(Text("❌ 软链接创建失败，请检查权限", "red bold"))
            log_message("❌ 软链接创建失败，请检查权限", "error")
            return False, None

        # 显示世界名称
        live.update(Text(f"🌍 世界名称: {world_name}", "cyan"))
        log_message(f"🌍 世界名称: {world_name}", "info")

        # 生成运行时配置
        live.update(Text("📝 生成运行时配置中...", "cyan"))
        log_message("📝 生成运行时配置中...", "info")
        runtime_config = gen_runtime_config(
            engine.version,
            world_name,
            level_id,
            mcs_download_dir,
            project_name,
            behavior_links,
            resource_links
        )

        # 写入配置文件
        ensure_dir(os.path.dirname(os.path.abspath(config_path)))
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(runtime_config, f, ensure_ascii=False, indent=2)

        live.update(Text(f"📝 配置文件已生成: {os.path.basename(config_path)}", "green"))
        log_message(f"📝 配置文件已生成: {os.path.basename(config_path)}", "success")

        # 地图存档创建
        if project_type == 'map':
            # 判断目标地图存档路径
            runtime_map_dir = os.path.join(engine_data_path, "minecraftWorlds", level_id)
            ensure_dir(runtime_map_dir)

            # MapPack
            map_pack_origin = MapPack(project_name, project_dir)
            map_pack_target = MapPack(project_name, runtime_map_dir)
            
            live.update(Text("🗺️ 正在准备地图存档...", "cyan"))
            log_message("🗺️ 正在准备地图存档...", "info")
            
            map_pack_origin.copy_level_data_to(runtime_map_dir)

            live.update(Text(f"✓ 已复制地图存档", "green"))
            log_message(f"✓ 已复制地图存档", "success")
                
            # 链接
            live.update(Text("🔗 正在设置地图软链接...", "cyan"))
            log_message("🔗 正在设置地图软链接...", "info")
            map_pack_origin.setup_packs_symlinks_to(level_id, runtime_map_dir)

            # 创建world_behavior_packs.json和world_resource_packs.json
            live.update(Text("📄 正在生成包配置文件...", "cyan"))
            log_message("📄 正在生成包配置文件...", "info")
            
            # 处理行为包
            behavior_packs_config, resource_packs_config = map_pack_target.setup_world_packs_config()
            
            live.update(Text(f"✓ 已创建world_behavior_packs.json，包含{len(behavior_packs_config)}个行为包", "green"))
            log_message(f"✓ 已创建world_behavior_packs.json，包含{len(behavior_packs_config)}个行为包", "success")
            
            live.update(Text(f"✓ 已创建world_resource_packs.json，包含{len(resource_packs_config)}个资源包", "green"))
            log_message(f"✓ 已创建world_resource_packs.json，包含{len(resource_packs_config)}个资源包", "success")
            
    # 启动游戏
    logging_port = logging_port if logging_port is not None else _gen_random_port()

    log_message(f"🚀 正在启动游戏实例: {level_id[:8]}...", "bright_blue")
    
    with console.status("启动游戏中...", spinner="dots"):
        game_process = open_game(config_path, logging_port=logging_port, wait=False, engine=engine,
                                 **({'output_path': output_path} if output_path else {}))

    if not game_process:
        log_message("❌ 游戏启动失败", "error")
        return False, None

    # 启动studio_logging_server
    if is_windows() and not no_gui:
        from ..mcstudio.studio_server_ui import run_studio_server_ui_subprocess
        run_studio_server_ui_subprocess(port=logging_port)

    # 启动日志与调试工具
    if not no_gui:
        open_safaia()

    # 输出成功启动信息
    log_message("✨ 游戏已启动，正在运行中...", "bright_green")
    
    # 根据wait参数决定是否等待游戏进程结束
    if wait:
        log_message("⏱️ 按 Ctrl+C 可以中止等待", "yellow")
        try:
            # 等待游戏进程结束
            game_process.wait()
            log_message("👋 游戏已退出", "bright_cyan")
        except KeyboardInterrupt:
            # 捕获 Ctrl+C，但不终止游戏进程
            log_message("\n🛑 收到中止信号，脚本将退出但游戏继续运行", "yellow")
            raise
    
    return True, game_process

using_ports = []

def _is_port_in_use(port):
    """检查端口是否被系统占用"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("localhost", port))
            return False
        except socket.error:
            return True

def _gen_random_port():
    """生成随机端口，确保在系统中未被占用"""
    import random
    max_attempts = 50  # 设置最大尝试次数，避免无限循环
    attempts = 0
    
    while attempts < max_attempts:
        port = random.randint(1024, 65535)
        if port not in using_ports and not _is_port_in_use(port):
            using_ports.append(port)
            return port
        attempts += 1
    
    # 如果尝试多次仍无法找到可用端口，使用一个高概率可用的端口
    console.print("⚠️ 无法找到空闲端口，将使用默认值", style="yellow")
    return 0  # 返回0让操作系统自动分配端口


@click.command(cls=OperationCommand)
@engine_options
@click.option("--no-gui", is_flag=True, help="只显示游戏，不打开辅助 GUI")
@click.option("--detach", is_flag=True, help="后台运行并返回游戏会话")
@click.option('--new', '-n', is_flag=True, help='创建新的游戏实例')
@click.option('--list', '-l', is_flag=True, help='列出所有可用的游戏实例')
@click.option('--delete', '-d', help='删除指定的游戏实例 (输入实例ID前缀)')
@click.option('--force', '-f', is_flag=True, help='强制删除，不提示确认')
@click.option('--clean-all', is_flag=True, help='清空所有游戏实例')
@click.argument('instance_prefix', required=False)
def run_cmd(new, list, delete, force, clean_all, instance_prefix, no_gui, detach, **engine_overrides):
    """游戏实例运行与管理
    
    可直接运行 'mcpy run' 启动最新实例，或使用选项管理实例。

    配置 [tool.mcpywrap.server] host/port 时改为未认证网络连接，
    不装配本地 Mod，不保证服务器接受连接。网络模式前台采集日志，
    Ctrl+C 结束本次游戏，暂不支持 --detach。
    """
    base_dir = str(current_project())
    if (delete or clean_all) and non_interactive() and not force:
        raise click.UsageError("非交互删除需要 --force")
    # 检查项目是否已初始化
    if not config_exists():
        require_project()

    # 在存档选择、配置同步和目录创建之前分流；管理选项仍只管理本地存档。
    if not (list or delete or clean_all):
        from ..dependencies import read_project
        from ..mcstudio.network import configured_target, prepare_project, run_network
        config = read_project(base_dir)
        target = configured_target(config)
        if target is not None:
            if new or instance_prefix:
                raise click.UsageError('网络模式不支持 --new 或本地世界实例 ID')
            if detach:
                raise click.UsageError('网络模式暂不支持 --detach；请在终端会话中前台运行')
            packs = prepare_project(base_dir, config)
            return run_network(target, project_dir=base_dir, packs=packs,
                               engine_overrides=engine_overrides)

    # 确保 map 项目的 setuptools 配置同步
    ensure_map_setuptools_sync(interactive=False)

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
        return {'instances': _get_all_instances()}
    
    # 删除指定实例
    if delete:
        _delete_instance(delete, force)
        return

    # 设置依赖
    all_packs = _setup_dependencies(project_name, base_dir)
    if all_packs is None:
        raise click.ClickException('依赖校验失败')

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
            raise click.ClickException("未找到指定实例")
    else:
        # 使用最新实例，如果没有则创建新实例
        latest_instance = _get_latest_instance()
        if (latest_instance):
            level_id = latest_instance['level_id']
            config_path = latest_instance['config_path']
            console.print(f"📅 使用最新实例: {level_id[:8]}...", style="green")
        else:
            # 只有在找不到任何现有实例时才创建新实例
            level_id, config_path = _generate_new_instance_config(base_dir, project_name)
            console.print(f"🆕 创建首个实例: {level_id[:8]}...", style="green")
            console.print("💡 下次运行将重用此实例，若需创建新实例请使用 \"--new\" 参数", style="yellow")

    from ..command_context import json_output
    if json_output() and not detach:
        raise click.UsageError('run --json 需要 --detach，避免等待游戏退出')
    if no_gui or detach or non_interactive():
        from ..mcstudio import sessions
        import time
        data = sessions.start(base_dir, config_path, level_id, engine_overrides)
        result = {'application': 'game', 'project': base_dir, 'session': data['session'],
                  'state': data['state'], **data['game'], 'log_path': data['log_path'],
                  'engine_log_path': data.get('engine_log_path'),
                  'window_title_hint': 'Minecraft', 'window_verified': False}
        if detach:
            return result
        click.echo('会话: ' + data['session'] + '；日志: ' + data['log_path'])
        try:
            while sessions.read(base_dir, data['session'])['state'] in ('starting', 'running'):
                time.sleep(0.3)
        except KeyboardInterrupt:
            click.echo('游戏继续运行；使用 stop --session ' + data['session'] + ' 停止。', err=True)
            raise
        final = sessions.read(base_dir, data['session'])
        if final['state'] == 'failed' or final.get('exit_code', 0) != 0:
            raise click.ClickException(final.get('error') or '游戏异常退出，请查看会话日志')
        return result
    success, _ = _run_game_with_instance(config_path, level_id, all_packs,
                                         engine_overrides=engine_overrides)
    if not success:
        raise click.ClickException('游戏启动失败')



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


def _safe_remove_directory(path):
    """
    安全地递归删除目录，对于软链接只删除链接本身而不删除其指向的内容
    
    Args:
        path: 要删除的目录路径
    """
    if not os.path.exists(path) and not os.path.islink(path):
        return
        
    if os.path.islink(path):
        # 如果是软链接，只删除链接本身
        os.unlink(path)
    elif os.path.isdir(path):
        # 如果是目录，先处理其内容
        for item in os.listdir(path):
            item_path = os.path.join(path, item)
            if os.path.islink(item_path):
                # 如果是软链接，只删除链接本身
                os.unlink(item_path)
            elif os.path.isdir(item_path):
                # 递归处理子目录
                _safe_remove_directory(item_path)
            else:
                # 删除文件
                os.remove(item_path)
        # 删除空目录
        os.rmdir(path)
    elif os.path.isfile(path):
        # 删除文件
        os.remove(path)

def _delete_instance(instance_prefix, force, project_dir=None):
    """删除指定的游戏实例"""
    instance = _match_instance_by_prefix(instance_prefix, project_dir)
    
    if not instance:
        console.print(f"❌ 未找到前缀为 \"{instance_prefix}\" 的实例", style="red")
        raise click.ClickException("删除实例失败，请检查实例 ID 或文件访问权限")
    
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
            if os.path.exists(world_dir) or os.path.islink(world_dir):
                console.log(f"🗑️ 正在安全删除游戏存档: {world_dir}")
                _safe_remove_directory(world_dir)
            else:
                console.log(f"ℹ️ 未找到对应的游戏存档")
        
        except Exception as e:
            console.print(f"❌ 删除实例时出错: {str(e)}", style="red")
            raise click.ClickException("删除实例失败，请检查实例 ID 或文件访问权限")
    
    console.print(f"✅ 成功删除实例: {level_id[:8]}", style="green")


def _clean_all_instances(force, project_dir=None):
    """清空所有游戏实例"""
    instances = _get_all_instances(project_dir)
    
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
            raise click.Abort()
            
        confirmation2 = click.confirm('⚠️ 最后确认: 真的要删除所有实例吗?', default=False)
        if not confirmation2:
            raise click.Abort()
    
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
                if os.path.exists(world_dir) or os.path.islink(world_dir):
                    _safe_remove_directory(world_dir)
                    
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
        if fail_count > 0:
            raise click.ClickException(f"删除失败 {fail_count} 个实例，请检查文件访问权限")
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


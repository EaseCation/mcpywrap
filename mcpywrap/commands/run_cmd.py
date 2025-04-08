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


# 实例管理助手函数
def _get_all_instances():
    """获取所有运行实例信息"""
    runtime_dir = os.path.join(os.getcwd(), ".runtime")
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
            click.echo(click.style('❌ 未找到行为包目录，请检查项目结构', fg='red', bold=True))
            return None
        # 创建主包实例
        main_pack = AddonsPack(project_name, base_dir, is_origin=True)
        all_packs.append(main_pack)

    # 解析依赖包
    dependency_manager = DependencyManager()
    dependencies = get_project_dependencies()

    if dependencies:
        click.secho('📦 正在解析依赖包...', fg='blue')

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
                click.secho(f'✅ 成功解析 {len(dependency_packs)} 个依赖包', fg='green')

                # 打印依赖树结构
                click.secho('📊 依赖关系:', fg='cyan')
                root_node = dependency_manager.get_dependency_tree()
                if (root_node):
                    _print_dependency_tree(root_node, 0)
                
                all_packs.extend(dependency_packs)
            else:
                click.secho('ℹ️ 没有找到可用的依赖包', fg='cyan')
        except Exception as e:
            click.secho(f'⚠️ 解析依赖时出错: {str(e)}', fg='yellow')
            click.secho('ℹ️ 将继续而不加载依赖包', fg='yellow')
    else:
        click.secho('ℹ️ 项目没有声明依赖包', fg='cyan')

    return all_packs

def _run_game_with_instance(config_path, level_id, all_packs):
    """使用指定的实例运行游戏"""
    base_dir = os.getcwd()
    project_type = get_project_type()
    project_name = get_project_name()
    
    # 获取MC Studio安装目录
    mcs_download_dir = get_mcs_download_path()
    if not mcs_download_dir:
        click.echo(click.style('❌ 未找到MC Studio下载目录，请确保已安装MC Studio', fg='red', bold=True))
        return False

    # 获取游戏引擎版本
    engine_dirs = get_mcs_game_engine_dirs()
    if not engine_dirs:
        click.echo(click.style('❌ 未找到MC Studio游戏引擎，请确保已安装MC Studio', fg='red', bold=True))
        return False
    
    # 获取游戏引擎数据目录
    engine_data_path = get_mcs_game_engine_data_path()

    # 使用最新版本的引擎
    latest_engine = engine_dirs[0]
    click.echo(click.style(f'🎮 使用引擎版本: {latest_engine}', fg='cyan'))

    # 设置软链接
    link_suc, behavior_links, resource_links = setup_global_addons_symlinks(all_packs)

    if not link_suc:
        click.echo(click.style('❌ 软链接创建失败，请检查权限', fg='red', bold=True))
        return False

    # 生成世界名称
    world_name = project_name

    print(click.style(f'🌍 世界名称: {world_name}', fg='cyan'))

    # 生成运行时配置
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

    click.echo(click.style(f'📝 配置文件已生成: {os.path.basename(config_path)}', fg='green'))

    # 地图存档创建
    if project_type == 'map':
        # 判断目标地图存档路径
        runtime_map_dir = os.path.join(engine_data_path, "minecraftWorlds", level_id)
        ensure_dir(runtime_map_dir)
        # 判断是否有level.dat，没有的话就复制
        level_dat_path = os.path.join(runtime_map_dir, "level.dat")
        if not os.path.exists(level_dat_path):
            click.echo(click.style(f"🗺️ 创建地图存档... {level_dat_path}", fg='yellow'))
            origin_level_dat_path = os.path.join(base_dir, "level.dat")
            if os.path.exists(origin_level_dat_path):
                shutil.copy2(origin_level_dat_path, level_dat_path)
        level_db_dir = os.path.join(runtime_map_dir, "db")
        if not os.path.exists(level_db_dir) and os.path.exists(os.path.join(base_dir, "db")):
            shutil.copytree(os.path.join(base_dir, "db"), level_db_dir)
        # 链接
        setup_map_packs_symlinks(base_dir, runtime_map_dir)

    # 启动游戏
    logging_port = 8678

    click.echo(click.style(f'🚀 正在启动游戏实例: {level_id[:8]}...', fg='bright_blue', bold=True))
    
    game_process = open_game(config_path, logging_port=logging_port)

    if game_process is None:
        click.echo(click.style('❌ 游戏启动失败', fg='red', bold=True))
        return False

    # 启动studio_logging_server
    run_studio_server_ui_subprocess(port=logging_port)

    # 启动日志与调试工具
    open_safaia()

    # 等待游戏进程结束
    click.echo(click.style('✨ 游戏已启动，正在运行中...', fg='bright_green', bold=True))
    click.echo(click.style('⏱️ 按 Ctrl+C 可以中止等待', fg='yellow'))

    try:
        # 等待游戏进程结束
        game_process.wait()
        click.echo(click.style('👋 游戏已退出', fg='bright_cyan', bold=True))
    except KeyboardInterrupt:
        # 捕获 Ctrl+C，但不终止游戏进程
        click.echo(click.style('\n🛑 收到中止信号，脚本将退出但游戏继续运行', fg='yellow'))
    
    return True


@click.command()
@click.option('--new', '-n', is_flag=True, help='创建新的游戏实例')
@click.option('--list', '-l', is_flag=True, help='列出所有可用的游戏实例')
@click.option('--delete', '-d', help='删除指定的游戏实例 (输入实例ID前缀)')
@click.option('--force', '-f', is_flag=True, help='强制删除，不提示确认')
@click.argument('instance_prefix', required=False)
def run_cmd(new, list, delete, force, instance_prefix):
    """游戏实例运行与管理
    
    可直接运行 'mcpy run' 启动最新实例，或使用选项管理实例
    """
    # 检查项目是否已初始化
    if not config_exists():
        click.echo(click.style('❌ 项目尚未初始化，请先运行 mcpy init', fg='red', bold=True))
        return

    base_dir = os.getcwd()
    project_name = get_project_name()
    
    # 创建运行时配置目录
    runtime_dir = os.path.join(base_dir, ".runtime")
    ensure_dir(runtime_dir)

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
        click.secho(f'🆕 创建新实例: {level_id[:8]}...', fg='green')
    elif instance_prefix:
        # 通过前缀查找实例
        instance = _match_instance_by_prefix(instance_prefix)
        if instance:
            level_id = instance['level_id']
            config_path = instance['config_path']
            click.secho(f'🔍 使用实例: {level_id[:8]}...', fg='green')
        else:
            click.secho(f'❌ 未找到前缀为 "{instance_prefix}" 的实例', fg='red')
            instances = _get_all_instances()
            if instances:
                click.secho('💡 可用实例:', fg='yellow')
                for i, inst in enumerate(instances):
                    if i < 5:  # 只显示前5个
                        click.secho(f'   - {inst["level_id"][:8]}', fg='yellow')
                    else:
                        click.secho(f'   ...还有 {len(instances) - 5} 个实例', fg='yellow')
                        break
                click.secho('💡 使用 "mcpy run -l" 查看所有实例', fg='yellow')
            return
    else:
        # 使用最新实例，如果没有则创建新实例
        latest_instance = _get_latest_instance()
        if latest_instance:
            level_id = latest_instance['level_id']
            config_path = latest_instance['config_path']
            click.secho(f'📅 使用最新实例: {level_id[:8]}...', fg='green')
        else:
            # 只有在找不到任何现有实例时才创建新实例
            level_id, config_path = _generate_new_instance_config(base_dir, project_name)
            click.secho(f'🆕 创建首个实例: {level_id[:8]}...', fg='green')
            click.secho('💡 下次运行将重用此实例，若需创建新实例请使用 "--new" 参数', fg='yellow')

    # 运行游戏
    _run_game_with_instance(config_path, level_id, all_packs)


def _list_instances():
    """列出所有可用的游戏实例"""
    instances = _get_all_instances()
    
    if not instances:
        click.secho('📭 没有找到任何游戏实例', fg='yellow')
        return
    
    click.secho('📋 可用游戏实例列表:', fg='bright_cyan')
    click.secho(f"{'  ID预览  ':12} {'创建时间':19} {'世界名称'}", fg='cyan')
    click.secho("-" * 50, fg='cyan')
    
    for i, instance in enumerate(instances):
        creation_time = datetime.fromtimestamp(instance['creation_time'])
        time_str = creation_time.strftime('%Y-%m-%d %H:%M:%S')
        
        prefix = '📌 ' if i == 0 else '   '
        level_id = instance['level_id']
        # 只显示前8个字符，方便引用
        short_id = level_id[:8]
        
        click.secho(f"{prefix}{short_id:10} {time_str} {instance['name']}", 
                   fg='bright_green' if i == 0 else 'green')
        
    click.secho("\n💡 提示: 使用 'mcpy run <实例ID前缀>' 运行特定实例", fg='cyan')
    click.secho("💡 提示: 使用 'mcpy run -n' 创建新实例", fg='cyan')
    click.secho("💡 提示: 使用 'mcpy run -d <实例ID前缀>' 删除实例", fg='cyan')


def _delete_instance(instance_prefix, force):
    """删除指定的游戏实例"""
    instance = _match_instance_by_prefix(instance_prefix)
    
    if not instance:
        click.secho(f'❌ 未找到前缀为 "{instance_prefix}" 的实例', fg='red')
        return
    
    level_id = instance['level_id']
    config_path = instance['config_path']
    
    if not force:
        click.secho(f'即将删除实例: {level_id[:8]} ({instance["name"]})', fg='yellow')
        confirmation = click.confirm('确定要删除吗?', abort=True)
    
    try:
        # 删除配置文件
        if os.path.exists(config_path):
            os.remove(config_path)
            
        # 获取游戏引擎数据目录
        engine_data_path = get_mcs_game_engine_data_path()
        
        # 删除游戏世界目录
        world_dir = os.path.join(engine_data_path, "minecraftWorlds", level_id)
        if os.path.exists(world_dir):
            shutil.rmtree(world_dir, ignore_errors=True)
        
        click.secho(f'✅ 成功删除实例: {level_id[:8]}', fg='green')
    except Exception as e:
        click.secho(f'❌ 删除实例时出错: {str(e)}', fg='red')


def _print_dependency_tree(node, level):
    """打印依赖树结构"""
    indent = "  " * level
    if level == 0:
        click.secho(f"{indent}└─ {node.name} (主项目)", fg="bright_cyan")
    else:
        click.secho(f"{indent}└─ {node.name}", fg="cyan")

    for child in node.children:
        _print_dependency_tree(child, level + 1)
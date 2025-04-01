# -*- coding: utf-8 -*-

"""
开发命令模块
"""
import os
import time
import click
from ..config import get_mcpywrap_config, config_exists, read_config
from ..builders.watcher import FileWatcher, MultiWatcher
from ..builders.project_builder import find_mcpywrap_dependencies
from .build_cmd import build

def file_change_callback(src_path, dest_path, success, output, is_python, is_dependency=False, dependency_name=None):
    """文件变化回调函数 - 展示处理结果"""
    if is_dependency:
        click.secho(f"\n📝 检测到依赖项目 ", fg="bright_blue", nl=False)
        click.secho(f"{dependency_name}", fg="bright_magenta", nl=False)
        click.secho(f" 文件变化: ", fg="bright_blue", nl=False)
    else:
        click.secho(f"\n📝 检测到文件变化: ", fg="bright_blue", nl=False)
    
    click.secho(f"{src_path}", fg="bright_cyan")
    
    if is_python:
        click.secho("🔄 正在转换 Python 文件...", fg="yellow")
        if success:
            click.secho(f'✅ Python 文件已转换: ', fg="green", nl=False)
            click.secho(f'{dest_path}', fg="bright_green")
        else:
            click.secho(f'❌ Python 文件转换失败: ', fg="red", nl=False)
            click.secho(f'{output}', fg="bright_red")
    else:
        click.secho("📋 正在复制非 Python 文件...", fg="yellow")
        if success:
            click.secho(f'✅ 文件已复制: ', fg="green", nl=False)
            click.secho(f'{dest_path}', fg="bright_green")
        else:
            click.secho(f'❌ 文件复制失败: ', fg="red", nl=False)
            click.secho(f'{output}', fg="bright_red")

@click.command()
def dev_cmd():
    """使用watch模式，实时构建为 MCStudio 工程，代码更新时，自动构建"""
    if not config_exists():
        click.secho('❌ 错误: 未找到配置文件。请先运行 `mcpywrap init` 初始化项目。', fg="red")
        return False
    
    # 获取mcpywrap特定配置
    mcpywrap_config = get_mcpywrap_config()
    # 源代码目录固定为当前目录
    source_dir = os.getcwd()
    # 目标目录从配置中读取behavior_pack_dir
    target_dir = mcpywrap_config.get('target_dir')
    
    if not target_dir:
        click.secho('❌ 错误: 配置文件中未找到target_dir。请手动添加。', fg="red")
        return False
    
    # 转换为绝对路径
    target_dir = os.path.normpath(os.path.join(source_dir, target_dir))

    # 读取项目配置获取依赖项
    config = read_config()
    dependencies_list = config.get('project', {}).get('dependencies', [])
    
    # 查找依赖项目路径
    dependencies = find_mcpywrap_dependencies(dependencies_list)
    
    # 实际构建
    suc = build(source_dir, target_dir)
    if not suc:
        click.secho("❌ 初始构建失败", fg="red")

    click.secho(f"🔍 开始监控代码变化，路径: ", fg="bright_blue", nl=False)
    click.secho(f"{source_dir}", fg="bright_cyan")
    
    # 创建多项目监视器
    multi_watcher = MultiWatcher()
    
    # 为当前项目创建文件监视器并添加到多项目监视器
    main_watcher = FileWatcher(source_dir, target_dir, file_change_callback)
    multi_watcher.add_watcher(main_watcher)
    
    # 为每个依赖项目创建文件监视器
    for dep_name, dep_addon in dependencies.items():
        click.secho(f"🔍 监控依赖项目: ", fg="bright_blue", nl=False)
        click.secho(f"{dep_name}", fg="bright_magenta", nl=False)
        click.secho(f" 路径: ", fg="bright_blue", nl=False)
        click.secho(f"{dep_addon.path}", fg="bright_cyan")
        
        # 为依赖项目创建文件监视器
        dep_watcher = FileWatcher(
            dep_addon.path, 
            target_dir, 
            file_change_callback,
            is_dependency=True,
            dependency_name=dep_name
        )
        multi_watcher.add_watcher(dep_watcher)
    
    # 启动所有监视器
    multi_watcher.start_all()
    
    try:
        click.secho("👀 监控中... 按 Ctrl+C 停止", fg="bright_magenta")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        multi_watcher.stop_all()
        click.secho("🛑 监控已停止", fg="bright_yellow")

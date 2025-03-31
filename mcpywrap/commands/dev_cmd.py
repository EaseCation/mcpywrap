# -- coding: utf-8 -*-

"""
开发命令模块
"""
import os
import time
import click
from ..config import get_mcpywrap_config, config_exists
from ..builders.watcher import FileWatcher
from .build_cmd import build

def file_change_callback(src_path, dest_path, success, output, is_python):
    """文件变化回调函数 - 展示处理结果"""
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

    # 实际构建
    suc = build(source_dir, target_dir)
    if not suc:
        click.secho("❌ 初始构建失败", fg="red")

    click.secho(f"🔍 开始监控代码变化，路径: ", fg="bright_blue", nl=False)

    click.secho(f"{source_dir}", fg="bright_cyan")
    
    # 创建并启动文件监控器
    watcher = FileWatcher(source_dir, target_dir, file_change_callback)
    watcher.start()
    
    try:
        click.secho("👀 监控中... 按 Ctrl+C 停止", fg="bright_magenta")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        watcher.stop()
        click.secho("🛑 监控已停止", fg="bright_yellow")
    
# -*- coding: utf-8 -*-

import os
import click
import shutil
import ctypes
import sys
import subprocess
from .mcs import *


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def run_as_admin(args=None, force_restart=True):
    """
    以管理员权限重新启动当前脚本
    
    Args:
        args: 命令行参数列表
        force_restart: 是否强制重启进程
        
    Returns:
        bool: 是否成功请求管理员权限
    """
    if args is None:
        args = sys.argv
    
    try:
        if sys.platform == 'win32':
            # 在Windows上使用ShellExecute以管理员权限启动程序
            result = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, subprocess.list2cmdline(args), None, 1
            ) > 32
            
            # 如果成功启动并且需要强制重启，则退出当前进程
            if result and force_restart:
                sys.exit(0)
                
            return result
        else:
            # 在非Windows平台上不支持这个功能
            return False
    except Exception as e:
        click.secho(f"❌ 无法请求管理员权限: {str(e)}", fg="red", bold=True)
        return False


def setup_addons_symlinks(packs: list):
    """
    在MC Studio用户数据目录下为行为包和资源包创建软链接

    Args:
        packs: 行为包和资源包列表

    Returns:
        tuple: (成功状态, 行为包链接列表, 资源包链接列表)
    """
    if not is_windows():
        click.secho("❌ 此功能仅支持Windows系统", fg="red", bold=True)
        return False, [], []
        
    # 检查管理员权限，如果没有则请求
    if is_windows() and not is_admin():
        click.secho("⚠️ 创建软链接需要管理员权限，正在请求...", fg="yellow", bold=True)
        # 请求管理员权限并退出当前进程，新进程将继续执行
        if run_as_admin():
            # 成功请求管理员权限，程序会重新启动，当前进程退出
            sys.exit(0)
        else:
            click.secho("❌ 无法获取管理员权限，软链接创建可能会失败", fg="red", bold=True)
            # 继续尝试创建软链接，但可能会失败

    # 如果代码执行到这里，说明已经有管理员权限或者获取权限失败
    behavior_links = []
    resource_links = []

    try:
        # 获取MC Studio用户数据目录
        user_data_path = get_mcs_game_engine_data_path()
        if not user_data_path:
            click.secho("❌ 未找到MC Studio用户数据目录", fg="red", bold=True)
            return False, [], []

        # 行为包和资源包目录
        behavior_packs_dir = os.path.join(user_data_path, "behavior_packs")
        resource_packs_dir = os.path.join(user_data_path, "resource_packs")

        # 确保目录存在
        os.makedirs(behavior_packs_dir, exist_ok=True)
        os.makedirs(resource_packs_dir, exist_ok=True)

        # 清空现有链接
        click.secho("🧹 清理现有软链接...", fg="cyan")
        # 使用shutil.rmtree删除目录及其内容，然后重新创建

        if os.path.exists(behavior_packs_dir):
            try:
                shutil.rmtree(behavior_packs_dir)
            except Exception as e:
                click.secho(f"⚠️ 删除行为包目录失败: {str(e)}", fg="yellow")
                _clear_directory_symlinks(behavior_packs_dir)  # 备选方案：清理软链接

        if os.path.exists(resource_packs_dir):
            try:
                shutil.rmtree(resource_packs_dir)
            except Exception as e:
                click.secho(f"⚠️ 删除资源包目录失败: {str(e)}", fg="yellow")
                _clear_directory_symlinks(resource_packs_dir)  # 备选方案：清理软链接

        # 重新创建目录
        os.makedirs(behavior_packs_dir, exist_ok=True)
        os.makedirs(resource_packs_dir, exist_ok=True)

        # 创建新链接
        click.secho("🔗 创建新的软链接...", fg="cyan")

        for pack in packs:
            # 处理行为包
            if pack.behavior_pack_dir and os.path.exists(pack.behavior_pack_dir):
                link_name = f"{os.path.basename(pack.behavior_pack_dir)}_{pack.pkg_name}"
                link_path = os.path.join(behavior_packs_dir, link_name)

                try:
                    # 创建软链接
                    os.symlink(pack.behavior_pack_dir, link_path, target_is_directory=True)
                    click.secho(f"✅ 行为包链接创建成功: {link_name}", fg="green")
                    behavior_links.append(link_name)
                except Exception as e:
                    click.secho(f"⚠️ 行为包链接创建失败: {str(e)}", fg="yellow")

            # 处理资源包
            if pack.resource_pack_dir and os.path.exists(pack.resource_pack_dir):
                link_name = f"{os.path.basename(pack.resource_pack_dir)}_{pack.pkg_name}"
                link_path = os.path.join(resource_packs_dir, link_name)

                try:
                    # 创建软链接
                    os.symlink(pack.resource_pack_dir, link_path, target_is_directory=True)
                    click.secho(f"✅ 资源包链接创建成功: {link_name}", fg="green")
                    resource_links.append(link_name)
                except Exception as e:
                    click.secho(f"⚠️ 资源包链接创建失败: {str(e)}", fg="yellow")

        click.secho("✅ 软链接设置完成！", fg="bright_green", bold=True)
        return True, behavior_links, resource_links

    except Exception as e:
        click.secho(f"❌ 设置软链接失败: {str(e)}", fg="red", bold=True)
        return False, behavior_links, resource_links

def _clear_directory_symlinks(directory):
    """
    清除目录中的所有软链接

    Args:
        directory: 要清理的目录路径
    """
    if not os.path.exists(directory):
        return

    for item in os.listdir(directory):
        item_path = os.path.join(directory, item)
        if os.path.islink(item_path):
            try:
                os.unlink(item_path)
                click.secho(f"🗑️ 删除链接: {item}", fg="cyan")
            except Exception as e:
                click.secho(f"⚠️ 删除链接失败 {item}: {str(e)}", fg="yellow")
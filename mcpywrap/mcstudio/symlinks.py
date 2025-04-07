# -*- coding: utf-8 -*-

import os
import click
import shutil
from .mcs import *


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
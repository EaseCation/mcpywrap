# -*- coding: utf-8 -*-

import os
import json
import subprocess
import click
from .mcs import *

class SimpleMonitor:
    def __init__(self, process_name="Minecraft.Windows.exe"):
        self.process_name = process_name
        self.running = False

        # 检查进程是否已启动
        import psutil
        for proc in psutil.process_iter(['name']):
            if proc.info['name'] == self.process_name:
                self.running = True
                break

    def wait(self):
        """等待进程结束"""
        import psutil
        import time

        # 等待游戏启动
        start_time = time.time()
        while not self.running and time.time() - start_time < 30:
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] == self.process_name:
                    self.running = True
                    break
            time.sleep(1)

        # 如果游戏已启动，等待它结束
        if self.running:
            while True:
                found = False
                for proc in psutil.process_iter(['name']):
                    if proc.info['name'] == self.process_name:
                        found = True
                        break
                if not found:
                    break
                time.sleep(1)

        return True

def open_game(config_path):
    """
    打开MC Studio游戏引擎

    Args:
        config_path: 游戏配置文件路径
        return_process: 是否返回进程对象

    Returns:
        如果 return_process=True，返回进程对象；否则返回布尔值表示是否成功启动
    """
    if not is_windows():
        click.secho("❌ 此功能仅支持Windows系统", fg="red", bold=True)
        return False

    try:
        # 检查配置文件是否存在
        if not os.path.isfile(config_path):
            click.secho(f"❌ 配置文件不存在: {config_path}", fg="red", bold=True)
            return False

        # 读取配置文件
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)

        # 从配置文件中获取目标引擎版本
        target_version = config_data.get("version")
        if not target_version:
            click.secho("⚠️ 配置文件中未找到引擎版本信息", fg="yellow", bold=True)
            # 如果没有指定版本，使用最新版本

        # 获取游戏引擎目录
        engine_dirs = get_mcs_game_engine_dirs()
        if not engine_dirs:
            click.secho("⚠️ 未找到MC Studio游戏引擎目录", fg="yellow", bold=True)
            return False

        # 选择合适的引擎版本
        selected_engine = None
        if target_version:
            # 查找与目标版本匹配的引擎
            for engine in engine_dirs:
                if engine == target_version:
                    selected_engine = engine
                    break

        # 如果没有找到匹配版本，使用最新版本
        if not selected_engine:
            selected_engine = engine_dirs[0]
            if target_version:
                click.secho(f"⚠️ 未找到指定版本 {target_version}，将使用最新版本 {selected_engine}", fg="yellow")
            else:
                click.secho(f"🎮 使用最新游戏引擎版本: {selected_engine}", fg="green")
        else:
            click.secho(f"🎮 使用指定游戏引擎版本: {selected_engine}", fg="green")

        # 获取下载路径
        download_path = get_mcs_download_path()
        if not download_path:
            click.secho("⚠️ 未找到MC Studio下载路径", fg="yellow", bold=True)
            return False

        # 拼接引擎完整路径
        engine_path = os.path.join(download_path, "game", "MinecraftPE_Netease", selected_engine)
        click.secho(f"📂 引擎路径: {engine_path}", fg="blue")

        # 检查引擎执行文件是否存在
        minecraft_exe = os.path.join(engine_path, "Minecraft.Windows.exe")
        if not os.path.isfile(minecraft_exe):
            click.secho(f"❌ 游戏执行文件不存在: {minecraft_exe}", fg="red", bold=True)
            return False

        click.secho(f"🚀 正在启动游戏...", fg="cyan")

        # 启动游戏程序
        import subprocess

        # 启动游戏
        cmd_str = f'cmd /c start "MC Studio Game Console" "{minecraft_exe}" config="{os.path.abspath(config_path)}"'
        subprocess.Popen(cmd_str, shell=True)

        return SimpleMonitor()

    except json.JSONDecodeError:
        click.secho(f"❌ 配置文件格式错误: {config_path}", fg="red", bold=True)
        return False
    except Exception as e:
        click.secho(f"❌ 启动游戏失败: {str(e)}", fg="red", bold=True)
        return False

def open_safaia():
    """
    启动 Safaia Server，如果已经运行则不再启动新实例

    Returns:
        bool: 启动成功或已在运行返回 True，否则返回 False
    """
    if is_windows():
        # 使用 tasklist 检查 safaia_server.exe 是否已运行
        try:
            result = subprocess.run('tasklist /FI "IMAGENAME eq safaia_server.exe" /NH',
                                    shell=True,
                                    capture_output=True,
                                    text=True)
            if 'safaia_server.exe' in result.stdout:
                click.secho("ℹ️ Safaia Server 已在运行中", fg="blue", bold=True)
                return True
        except Exception as e:
            click.secho(f"⚠️ 检查 Safaia Server 状态时出错: {str(e)}", fg="yellow")
            # 继续执行启动流程

    # 如果未运行或检查出错，继续启动新实例
    install_path = get_mcs_install_location()
    if not install_path:
        click.secho("❌ 未找到 Safaia 安装路径", fg="red", bold=True)
        return False

    # 获取 Safaia Server 可执行文件路径
    safaia_server_path = os.path.join(install_path, 'safaia', 'safaia_server.exe')
    if not os.path.exists(safaia_server_path):
        click.secho("❌ 找不到 Safaia Server 执行文件", fg="red", bold=True)
        return False

    # 构建命令行参数列表
    safaia_server_args = [
        safaia_server_path,
        "0",
        "netease",
        "MCStudio",
        "0"
    ]

    try:
        subprocess.Popen(safaia_server_args)
        click.secho("✅ Safaia Server 启动成功！", fg="green", bold=True)
        return True
    except Exception as e:
        click.secho(f"❌ 启动 Safaia Server 失败: {str(e)}", fg="red", bold=True)
        return False
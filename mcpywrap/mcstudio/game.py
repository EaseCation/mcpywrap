# -*- coding: utf-8 -*-

import os
import json
import subprocess
import click
import threading

from .mcs import is_windows
from .discovery import discover_engines, DiscoveryError, studio_installation

# 添加必要的Windows API支持
try:
    import win32gui
    import win32con
    from ctypes import windll, c_int, byref, sizeof
    HAS_WIN32API = True
except ImportError:
    HAS_WIN32API = False


def open_game(config_path, logging_ip="localhost", logging_port=8678, use_system_color=True, wait=True,
              engine=None, project_dir=None, output_path=None, capture_output=False):
    """
    打开MC Studio游戏引擎

    Args:
        config_path: 游戏配置文件路径
        logging_ip: 日志服务器IP地址
        logging_port: 日志服务器端口号
        use_system_color: 是否使用系统主题色标题栏

    Returns:
        返回本次启动的进程对象；失败返回 False。等待由调用方决定。
    """
    if not is_windows():
        click.secho("❌ 此功能仅支持Windows系统", fg="red", bold=True)
        return False

    try:
        if output_path and capture_output:
            raise ValueError('output_path 与 capture_output 不能同时使用')
        # 检查配置文件是否存在
        if not os.path.isfile(config_path):
            click.secho(f"❌ 配置文件不存在: {config_path}", fg="red", bold=True)
            return False

        # 读取配置文件
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)

        # 已解析的结果直接复用，禁止重新拼接另一个安装根目录。
        if engine is None:
            engine = discover_engines(project_dir, instance_version=config_data.get('version')).require_engine()
        if config_data.get('version'):
            from packaging.version import Version
            if Version(config_data['version']) != Version(engine.version):
                raise DiscoveryError('运行配置版本与选中的引擎不一致，请重新生成运行配置')
        engine_path = engine.engine_dir
        click.secho(f"🎮 使用引擎版本: {engine.version} ({engine.source})", fg="green")
        click.secho(f"📂 引擎路径: {engine_path}", fg="blue")

        # 检查引擎执行文件是否存在
        minecraft_exe = engine.executable
        if not os.path.isfile(minecraft_exe):
            click.secho(f"❌ 游戏执行文件不存在: {minecraft_exe}", fg="red", bold=True)
            return False

        click.secho(f"🚀 正在启动游戏...", fg="cyan")

        # 启动游戏程序
        import subprocess

        # 启动游戏
        import contextlib
        with open(output_path, 'ab') if output_path else contextlib.nullcontext() as output:
            proc = subprocess.Popen(
                [minecraft_exe, 'config=' + os.path.abspath(config_path),
                 'loggingIP=' + logging_ip, 'loggingPort=' + str(logging_port)],
                cwd=engine_path, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if capture_output else output,
                stderr=subprocess.STDOUT if capture_output else output)

        # 如果需要使用系统主题色且Win32API可用，使用定时器异步应用窗口样式
        if use_system_color and HAS_WIN32API and is_windows():
            # 使用定时器在5秒后触发窗口样式修改，避免阻塞主线程
            style_timer1 = threading.Timer(5.0, apply_system_titlebar_style, args=["Minecraft"])
            style_timer1.daemon = True
            style_timer1.start()
            style_timer2 = threading.Timer(10.0, apply_system_titlebar_style, args=["Minecraft"])
            style_timer2.daemon = True
            style_timer2.start()

        return proc

    except json.JSONDecodeError:
        click.secho(f"❌ 配置文件格式错误: {config_path}", fg="red", bold=True)
        return False
    except Exception as e:
        click.secho(f"❌ 启动游戏失败: {str(e)}", fg="red", bold=True)
        return False

def apply_system_titlebar_style(window_title_contains):
    """
    查找包含指定标题的窗口并应用系统主题色标题栏
    
    Args:
        window_title_contains: 窗口标题包含的文本
    """
    if not HAS_WIN32API:
        click.secho("⚠️ 无法应用系统主题色: 缺少win32api模块", fg="yellow")
        return False
    
    def enum_windows_callback(hwnd, results):
        if win32gui.IsWindowVisible(hwnd):
            window_text = win32gui.GetWindowText(hwnd)
            if window_title_contains.lower() in window_text.lower():
                results.append(hwnd)
        return True
    
    window_handles = []
    win32gui.EnumWindows(enum_windows_callback, window_handles)
    
    if not window_handles:
        click.secho(f"⚠️ 未找到标题包含 '{window_title_contains}' 的窗口", fg="yellow")
        return False
    
    # 定义DWM API常量和函数
    DWMWA_USE_IMMERSIVE_DARK_MODE = 20  # Windows 10 1809及以上版本
    DWMWA_CAPTION_COLOR = 35            # Windows 11的标题栏颜色
    DWMWA_SYSTEMBACKDROP_TYPE = 38      # Windows 11的系统背景类型
    DWMWA_USE_MICA = 1029               # Windows 11的Mica效果
    
    # Backdrop类型
    DWMSBT_AUTO = 0                     # 自动
    DWMSBT_DISABLE = 1                  # 禁用
    DWMSBT_MAINWINDOW = 2               # 主窗口样式（通常是Mica）
    DWMSBT_TRANSIENTWINDOW = 3          # 临时窗口样式（通常是亚克力）
    DWMSBT_TABBEDWINDOW = 4             # 标签式窗口样式

    for hwnd in window_handles:
        try:
            # 1. 设置系统主题色标题栏
            try:
                # 尝试使用DWMWA_USE_IMMERSIVE_DARK_MODE
                use_dark_mode = c_int(1)  # 1表示启用
                windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 
                    DWMWA_USE_IMMERSIVE_DARK_MODE, 
                    byref(use_dark_mode), 
                    sizeof(use_dark_mode)
                )
                # click.secho(f"✅ 已设置深色模式标题栏 (句柄: {hwnd})", fg="green")
            except Exception as e:
                click.secho(f"⚠️ 设置深色模式失败: {str(e)}", fg="yellow")
            
            # 2. 尝试设置Windows 11的系统背景类型
            try:
                backdrop_type = c_int(DWMSBT_MAINWINDOW)  # 使用主窗口样式
                windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 
                    DWMWA_SYSTEMBACKDROP_TYPE, 
                    byref(backdrop_type), 
                    sizeof(backdrop_type)
                )
                # click.secho(f"✅ 已设置系统背景类型 (句柄: {hwnd})", fg="green")
            except Exception as e:
                click.secho(f"⚠️ 设置系统背景类型失败: {str(e)}", fg="yellow")
            
            # 3. 尝试设置Mica效果
            try:
                use_mica = c_int(1)  # 1表示启用
                windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 
                    DWMWA_USE_MICA, 
                    byref(use_mica), 
                    sizeof(use_mica)
                )
                # click.secho(f"✅ 已设置Mica效果 (句柄: {hwnd})", fg="green")
            except Exception as e:
                click.secho(f"⚠️ 设置Mica效果失败: {str(e)}", fg="yellow")
            
            # 保留原有的窗口样式修改代码
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            
            # 强制窗口重绘
            win32gui.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 
                                win32con.SWP_FRAMECHANGED | 
                                win32con.SWP_NOMOVE | 
                                win32con.SWP_NOSIZE | 
                                win32con.SWP_NOZORDER)
            
        except Exception as e:
            click.secho(f"⚠️ 修改窗口样式失败 (句柄: {hwnd}): {str(e)}", fg="yellow")
    
    return True

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
    install_path, issues = studio_installation('safaia')
    if not install_path:
        click.secho("❌ 未找到 Safaia 安装资源: " + '; '.join(issues), fg="red", bold=True)
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

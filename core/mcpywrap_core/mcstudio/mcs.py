# -*- coding: utf-8 -*-

def is_windows():
    """
    检查是否是Windows系统
    """
    import os
    return os.name == 'nt'

def get_mcs_version():
    """
    从注册表中获取 MCStudio 的版本信息

    Returns:
        str: MCStudio 的版本，如果不存在则返回 None
    """
    if not is_windows():
        return None

    import winreg
    try:
        registry_path = r"Software\Netease\MCStudio"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path) as key:
            version, _ = winreg.QueryValueEx(key, "DisplayVersion")
            return version
    except Exception:
        return None

def get_mcs_download_path():
    """
    获取统一发现结果关联的 MCStudio 下载路径（兼容接口）

    Returns:
        str: MCStudio 的下载路径，如果不存在则返回 None
    """
    from .discovery import discover_engines
    engine = discover_engines().selected
    return engine.download_dir if engine else None

def get_mcs_install_location():
    """
    从注册表中获取 MCStudio 的安装路径

    Returns:
        str: MCStudio 的安装路径，如果不存在则返回 None
    """
    from .discovery import registry_values
    import os
    return next((path for path, _ in registry_values('InstallLocation')
                 if os.path.isdir(path)), None)

def get_mcs_registry_value(value_name):
    """
    从注册表中获取 MCStudio 的指定键值

    Args:
        value_name (str): 要获取的键名

    Returns:
        任意类型: 键对应的值，如果不存在则返回 None
    """
    if not is_windows():
        return None

    import winreg
    try:
        registry_path = r"Software\Netease\MCStudio"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
            return value
    except Exception:
        return None

def get_mcs_game_engine_dirs():
    """
    获取 MCStudio 的游戏引擎目录，并按版本号倒序排序

    仅返回选中下载根目录下包含游戏 EXE 的有效版本目录。

    Returns:
        list: 按版本号倒序排序的游戏引擎目录列表，如果路径不存在则返回空列表
    """
    from pathlib import Path
    from .discovery import discover_engines, _scan, _sorted
    result = discover_engines()
    if not result.selected or not result.selected.download_dir:
        return []
    candidates = _scan(result.selected.download_dir, result.selected.source, [])
    return [Path(c.engine_dir).name for c in _sorted(candidates)]
    
def get_mcs_game_engine_data_path():
    r"""
    获取 MinecraftPE_Netease 用户数据目录

    返回 AppData\Roaming\MinecraftPE_Netease\ 路径

    Returns:
        str: 用户数据目录路径，如果不存在或不是 Windows 系统则返回 None
    """
    if not is_windows():
        return None

    import os

    try:
        # 获取 AppData\Roaming 目录
        appdata_path = os.environ.get('APPDATA')
        if not appdata_path:
            return None

        # 拼接完整路径
        user_data_path = os.path.join(appdata_path, "MinecraftPE_Netease")

        # 检查目录是否存在
        if os.path.isdir(user_data_path):
            return user_data_path
        return None
    except Exception:
        return None

def get_mcs_game_engine_netease_data_path():
    r"""
    获取 MinecraftPE_Netease 用户数据目录

    返回 AppData\Roaming\MinecraftPE_Netease\games\com.netease 路径

    Returns:
        str: 用户数据目录路径，如果不存在或不是 Windows 系统则返回 None
    """
    if not is_windows():
        return None

    import os

    try:
        # 获取 AppData\Roaming 目录
        appdata_path = os.environ.get('APPDATA')
        if not appdata_path:
            return None

        # 拼接完整路径
        user_data_path = os.path.join(appdata_path, "MinecraftPE_Netease", "games", "com.netease")

        # 检查目录是否存在
        if os.path.isdir(user_data_path):
            return user_data_path
        return None
    except Exception:
        return None

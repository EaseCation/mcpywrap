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
    从注册表中获取 MCStudio 的下载路径

    Returns:
        str: MCStudio 的下载路径，如果不存在则返回 None
    """
    if not is_windows():
        return None

    import winreg
    try:
        registry_path = r"Software\Netease\MCStudio"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path) as key:
            download_path, _ = winreg.QueryValueEx(key, "DownloadPath")
            return download_path
    except Exception:
        return None

def get_mcs_install_location():
    """
    从注册表中获取 MCStudio 的安装路径

    Returns:
        str: MCStudio 的安装路径，如果不存在则返回 None
    """
    if not is_windows():
        return None

    import winreg
    try:
        registry_path = r"Software\Netease\MCStudio"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_path) as key:
            install_location, _ = winreg.QueryValueEx(key, "InstallLocation")
            return install_location
    except Exception:
        return None

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

    基于 MCStudio 下载路径，获取 MinecraftPE_Netease 目录下的所有游戏引擎目录，
    过滤掉以 PCLauncher 开头的目录，并按版本号倒序排序（最新版本在前）

    Returns:
        list: 按版本号倒序排序的游戏引擎目录列表，如果路径不存在则返回空列表
    """
    import os
    from packaging import version

    download_path = get_mcs_download_path()
    if not download_path:
        return []

    engine_path = os.path.join(download_path, "game", "MinecraftPE_Netease")

    if not os.path.isdir(engine_path):
        return []

    # 获取目录列表并过滤掉PCLauncher开头的目录
    engine_dirs = [
        d for d in os.listdir(engine_path)
        if os.path.isdir(os.path.join(engine_path, d)) and not d.startswith("PCLauncher")
    ]

    # 按版本号倒序排序
    try:
        # 使用packaging.version进行版本号比较
        sorted_engine_dirs = sorted(engine_dirs, key=lambda x: version.parse(x), reverse=True)
        return sorted_engine_dirs
    except Exception:
        # 如果解析版本号失败，尝试简单的字符串排序
        return sorted(engine_dirs, reverse=True)
    
def get_mcs_game_engine_data_path():
    """
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
    """
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
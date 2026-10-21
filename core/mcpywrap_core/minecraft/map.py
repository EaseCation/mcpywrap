# -*- coding: utf-8 -*-

"""
Minecraft 地图存档(Map)相关功能模块
"""
import os
import click
from pathlib import Path
from ..utils.utils import ensure_dir

def is_minecraft_map_project(dir_path):
    """
    自动检测是否为Minecraft地图存档项目
    必须同时满足以下条件:
    1. 存在level.dat文件
    2. 存在db目录
    """
    level_dat_exists = os.path.exists(os.path.join(dir_path, "level.dat"))
    db_dir_exists = os.path.isdir(os.path.join(dir_path, "db"))
    
    return level_dat_exists and db_dir_exists

def setup_minecraft_map(base_dir, map_name, map_description=None, game_type=0):
    """设置Minecraft地图存档基础框架"""
    result = {}
    
    # 确保基础目录存在
    ensure_dir(base_dir)
    
    # 创建db目录
    db_dir = os.path.join(base_dir, "db")
    ensure_dir(db_dir)

    # 创建资源包目录
    resource_pack_dir = os.path.join(base_dir, "resource_packs")
    ensure_dir(resource_pack_dir)

    # 创建行为包目录
    behavior_pack_dir = os.path.join(base_dir, "behavior_packs")
    ensure_dir(behavior_pack_dir)
    
    # 创建level.dat文件
    level_dat_path = os.path.join(base_dir, "level.dat")
    
    # 如果已经存在level.dat，先备份
    if os.path.exists(level_dat_path):
        backup_path = level_dat_path + ".bak"
        click.echo(click.style(f"⚠️ 已存在level.dat文件，备份到 {backup_path}", fg='yellow'))
        os.rename(level_dat_path, backup_path)
    
    # 创建新的level.dat
    from .level_dat import BedrockNBT
    nbt = BedrockNBT.create_new(level_name=map_name, game_type=game_type)
    nbt.save_file(level_dat_path, create_backup=False)

    # 创建levelname.txt
    levelname_txt_path = os.path.join(base_dir, "levelname.txt")
    with open(levelname_txt_path, "w", encoding="utf-8") as f:
        f.write(map_name)
    
    # 返回结果
    result["map_path"] = base_dir
    result["level_dat"] = level_dat_path
    result["db_dir"] = db_dir
    
    return result

def get_map_info(map_dir):
    """获取地图信息"""
    from .level_dat import BedrockNBT
    
    level_dat_path = os.path.join(map_dir, "level.dat")
    if not os.path.exists(level_dat_path):
        return None
    
    nbt = BedrockNBT.load_file(level_dat_path)
    if not nbt:
        return None
    
    return {
        "name": nbt.get_level_name(),
        "game_type": nbt.get_game_type(),
        "spawn_pos": nbt.get_spawn_position(),
        "path": map_dir
    }

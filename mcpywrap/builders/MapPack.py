# -*- coding: utf-8 -*-

import os
import shutil
import click
import json

from ..mcstudio.symlinks import setup_map_packs_symlinks

class MapPack(object):

    pkg_name: str
    path: str
    
    behavior_packs_dir: str
    resource_packs_dir: str

    behavior_packs = []
    resource_packs = []

    def __init__(self, pkg_name: str, path: str):
        self.pkg_name = pkg_name
        self.path = path

        # 读取配置文件
        self.behavior_packs_dir = os.path.join(self.path, "behavior_packs")
        self.resource_packs_dir = os.path.join(self.path, "resource_packs")

        if not os.path.exists(self.behavior_packs_dir):
            os.makedirs(self.behavior_packs_dir)

        # 遍历行为包目录
        for pack in os.listdir(self.behavior_packs_dir):
            pack_path = os.path.join(self.behavior_packs_dir, pack)
            if os.path.isdir(pack_path):
                self.behavior_packs.append(pack_path)
        
        if not os.path.exists(self.resource_packs_dir):
            os.makedirs(self.resource_packs_dir)

        # 遍历资源包目录
        for pack in os.listdir(self.resource_packs_dir):
            pack_path = os.path.join(self.resource_packs_dir, pack)
            if os.path.isdir(pack_path):
                self.resource_packs.append(pack_path)

    def copy_level_data_to(self, target_dir: str):
        """
        复制地图数据到目标目录
        """
        # level.dat
        level_dat_path = os.path.join(target_dir, "level.dat")
        if not os.path.exists(level_dat_path):
            origin_level_dat_path = os.path.join(self.path, "level.dat")
            if os.path.exists(origin_level_dat_path):
                shutil.copy2(origin_level_dat_path, level_dat_path)
        # levelname.txt
        levelname_txt_path = os.path.join(target_dir, "levelname.txt")
        if not os.path.exists(levelname_txt_path):
            origin_levelname_txt_path = os.path.join(self.path, "levelname.txt")
            if os.path.exists(origin_levelname_txt_path):
                shutil.copy2(origin_levelname_txt_path, levelname_txt_path)
        # db
        level_db_dir = os.path.join(target_dir, "db")
        if not os.path.exists(level_db_dir) and os.path.exists(os.path.join(self.path, "db")):
            shutil.copytree(os.path.join(self.path, "db"), level_db_dir)

    def copy_resource_packs_to(self, target_map_dir: str):
        """
        复制资源包到目标目录
        """
        for pack in self.resource_packs:
            pack_name = os.path.basename(pack)
            target_pack_dir = os.path.join(target_map_dir, "resource_packs", pack_name)
            # 先删除目标目录下的包
            if os.path.exists(target_pack_dir):
                shutil.rmtree(target_pack_dir)
            shutil.copytree(pack, target_pack_dir)
    
    def copy_behavior_packs_to(self, target_map_dir: str):
        """
        复制行为包到目标目录
        """
        for pack in self.behavior_packs:
            pack_name = os.path.basename(pack)
            target_pack_dir = os.path.join(target_map_dir, "behavior_packs", pack_name)
            # 先删除目标目录下的包
            if os.path.exists(target_pack_dir):
                shutil.rmtree(target_pack_dir)
            shutil.copytree(pack, target_pack_dir)

    
    def setup_packs_symlinks_to(self, level_id: str, target_dir: str):
        """
        设置行为包和资源包的符号链接到目标目录（本体到远程）
        """
        setup_map_packs_symlinks(self.path, level_id, target_dir)

    def setup_world_packs_config(self):
        """根据当前path，生成世界需加载的pack的配置文件"""
        behavior_packs_config = []
        if os.path.exists(self.behavior_packs_dir):
            behavior_packs_config = _find_and_extract_pack_info(self.behavior_packs_dir)
            if behavior_packs_config:
                world_behavior_packs_path = os.path.join(self.path, "world_behavior_packs.json")
                with open(world_behavior_packs_path, 'w', encoding='utf-8') as f:
                    json.dump(behavior_packs_config, f, ensure_ascii=False, indent=4)
        
        resource_packs_config = []
        if os.path.exists(self.resource_packs_dir):
            resource_packs_config = _find_and_extract_pack_info(self.resource_packs_dir)
            if resource_packs_config:
                world_resource_packs_path = os.path.join(self.path, "world_resource_packs.json")
                with open(world_resource_packs_path, 'w', encoding='utf-8') as f:
                    json.dump(resource_packs_config, f, ensure_ascii=False, indent=4)
        
        return behavior_packs_config, resource_packs_config

def _find_and_extract_pack_info(packs_dir):
    """
    搜索指定目录中的所有包，并从manifest.json中提取信息
    
    Args:
        packs_dir: 包目录路径
        
    Returns:
        list: 包配置列表
    """
    packs_config = []
    
    # 遍历目录下的所有子目录
    for pack_name in os.listdir(packs_dir):
        pack_path = os.path.join(packs_dir, pack_name)
        
        # 只处理目录
        if not os.path.isdir(pack_path):
            continue
        
        # 查找manifest.json或pack_manifest.json
        manifest_path = os.path.join(pack_path, "manifest.json")
        if not os.path.exists(manifest_path):
            manifest_path = os.path.join(pack_path, "pack_manifest.json")
            if not os.path.exists(manifest_path):
                continue
        
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            
            # 提取UUID和版本信息
            if 'header' in manifest:
                pack_id = manifest['header'].get('uuid')
                version = manifest['header'].get('version', [0, 0, 1])
                
                # 确保版本是列表格式
                if isinstance(version, list):
                    version_array = version
                elif isinstance(version, dict) and 'major' in version and 'minor' in version and 'patch' in version:
                    version_array = [version['major'], version['minor'], version['patch']]
                else:
                    version_array = [0, 0, 1]  # 默认版本
                
                if pack_id:
                    pack_config = {
                        "pack_id": pack_id,
                        "type": "Addon",
                        "version": version_array
                    }
                    packs_config.append(pack_config)
        except Exception as e:
            click.echo(f"⚠️ 读取包配置失败: {pack_name} - {str(e)}", style="yellow")
    
    return packs_config

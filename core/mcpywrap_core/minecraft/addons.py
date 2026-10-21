# -*- coding: utf-8 -*-

"""
Minecraft Addons 相关功能模块
"""
import os
import json
import uuid
from ..utils.utils import ensure_dir

def is_minecraft_addon_project(dir_path):
    """
    自动检测是否为Minecraft addon项目
    必须同时满足以下条件:
    1. 存在以resource_pack开头的目录
    2. 存在以behavior_pack开头的目录
    3. 这些目录中存在manifest.json或pack_manifest.json文件
    """
    # 查找以resource_pack开头的目录
    resource_pack_found = False
    resource_pack_has_manifest = False
    behavior_pack_found = False
    behavior_pack_has_manifest = False
    
    for item in os.listdir(dir_path):
        item_path = os.path.join(dir_path, item)
        
        # 检查resource_pack目录
        if os.path.isdir(item_path) and (item.startswith('resource_pack') or item.startswith('ResourcePack')):
            resource_pack_found = True
            # 检查manifest文件
            if (os.path.isfile(os.path.join(item_path, 'manifest.json')) or 
                os.path.isfile(os.path.join(item_path, 'pack_manifest.json'))):
                resource_pack_has_manifest = True
        
        # 检查behavior_pack目录
        if os.path.isdir(item_path) and (item.startswith('behavior_pack') or item.startswith('BehaviorPack')):
            behavior_pack_found = True
            # 检查manifest文件
            if (os.path.isfile(os.path.join(item_path, 'manifest.json')) or 
                os.path.isfile(os.path.join(item_path, 'pack_manifest.json'))):
                behavior_pack_has_manifest = True
    
    # 仅当所有条件都满足时返回True
    return resource_pack_found and behavior_pack_found and (resource_pack_has_manifest or behavior_pack_has_manifest)

def create_manifest_json(name, description, version="1.0.0", min_engine_version=None):
    """创建Minecraft包的manifest.json文件"""
    if not min_engine_version:
        min_engine_version = [1, 19, 0]
    
    manifest = {
        "format_version": 2,
        "header": {
            "name": name,
            "description": description,
            "uuid": str(uuid.uuid4()),
            "version": list(map(int, version.split('.')[:3])),
            "min_engine_version": min_engine_version
        },
        "modules": [
            {
                "type": "resources",
                "uuid": str(uuid.uuid4()),
                "version": list(map(int, version.split('.')[:3]))
            }
        ]
    }
    
    return manifest

def setup_minecraft_addon(base_dir, name, description, version):
    """设置Minecraft addon基础框架"""
    result = {}
    
    # 创建并设置resource pack
    resource_pack_dir = os.path.join(base_dir, "resource_pack")
    ensure_dir(resource_pack_dir)
    
    # 创建resource pack文件夹结构
    ensure_dir(os.path.join(resource_pack_dir, "textures"))
    
    # 创建resource pack清单文件
    rp_manifest = create_manifest_json(
        f"{name} Resources",
        f"{description} - Resources",
        version
    )
    
    # 检查是否已经存在manifest文件
    rp_manifest_path = os.path.join(resource_pack_dir, "manifest.json")
    if os.path.exists(rp_manifest_path):
        rp_manifest_path = os.path.join(resource_pack_dir, "pack_manifest.json")
        
    with open(rp_manifest_path, 'w', encoding='utf-8') as f:
        json.dump(rp_manifest, f, indent=4)
        
    result["resource_pack"] = {
        "path": resource_pack_dir,
        "manifest": rp_manifest_path,
        "uuid": rp_manifest["header"]["uuid"]
    }
    
    # 创建并设置behavior pack
    behavior_pack_dir = os.path.join(base_dir, "behavior_pack")
    ensure_dir(behavior_pack_dir)
    
    # 创建behavior pack文件夹结构
    ensure_dir(os.path.join(behavior_pack_dir, "entities"))
    ensure_dir(os.path.join(behavior_pack_dir, "items"))
    
    # 创建behavior pack清单文件
    bp_manifest = create_manifest_json(
        f"{name} Behaviors",
        f"{description}",
        version
    )
    bp_manifest["modules"][0]["type"] = "data"
    
    # 检查是否已经存在manifest文件
    bp_manifest_path = os.path.join(behavior_pack_dir, "manifest.json")
    if os.path.exists(bp_manifest_path):
        bp_manifest_path = os.path.join(behavior_pack_dir, "pack_manifest.json")
    
    with open(bp_manifest_path, 'w', encoding='utf-8') as f:
        json.dump(bp_manifest, f, indent=4)
        
    result["behavior_pack"] = {
        "path": behavior_pack_dir,
        "manifest": bp_manifest_path,
        "uuid": bp_manifest["header"]["uuid"]
    }
    
    return result

def find_behavior_pack_dir(base_dir):
    """
    查找项目中的behavior_pack目录
    支持任意带有behavior_pack前缀的目录名称
    """
    for item in os.listdir(base_dir):
        item_path = os.path.join(base_dir, item)
        if os.path.isdir(item_path) and (item.startswith('behavior_pack') or item.startswith('BehaviorPack')):
            # 确认是有效的behavior pack目录（检查manifest文件）
            if (os.path.isfile(os.path.join(item_path, 'manifest.json')) or 
                os.path.isfile(os.path.join(item_path, 'pack_manifest.json'))):
                return item_path
    return None
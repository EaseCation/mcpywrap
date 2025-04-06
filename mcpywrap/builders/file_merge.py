# -*- coding: utf-8 -*-
import os
import shutil
import json


def _read_json_file(file_path):
    """从文件中读取并解析JSON内容"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.loads(f.read())
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON解析错误: {str(e)}")
    except Exception as e:
        raise ValueError(f"读取文件错误: {str(e)}")


def _write_json_file(file_path, content):
    """将JSON内容写入文件"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(content, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        raise ValueError(f"写入文件错误: {str(e)}")


def try_merge_file(source_file, target_file) -> tuple[bool, str]:
    """合并两个文件的内容"""
    try:
        # 如果是py文件，直接复制即可
        if source_file.endswith('.py'):
            # 直接复制
            shutil.copy2(source_file, target_file)
            return True, f"成功复制 {os.path.basename(source_file)}"
        
        # 获取文件名
        base_name = os.path.basename(source_file)
        
        # 读取源文件和目标文件的JSON内容
        source_json = _read_json_file(source_file)
        target_json = _read_json_file(target_file)
        
        # 根据不同文件类型进行不同处理
        if base_name == "blocks.json":
            merged_json = _merge_dicts_shallow(target_json, source_json)
        elif base_name in ["terrain_texture.json", "item_texture.json"]:
            # 特殊处理texture_data字段
            merged_json = _merge_texture_json(target_json, source_json)
        elif base_name in ["sounds.json", "sound_definitions.json"]:
            # 特殊处理声音定义文件
            merged_json = _merge_sound_json(target_json, source_json)
        elif base_name in ["animations.json", "animation_controllers.json"]:
            # 特殊处理动画相关文件
            merged_json = _merge_animation_json(target_json, source_json)
        elif base_name in ["entity_models.json", "render_controllers.json", 
                          "materials.json", "attachables.json", "particle_effects.json"]:
            # 这些文件通常有顶级命名空间，包含多个注册项
            merged_json = _merge_registry_json(target_json, source_json)
        else:
            # 不支持的JSON文件类型
            return False, f"不支持合并此类型的文件: {base_name}"
        
        # 写入合并后的内容到目标文件
        _write_json_file(target_file, merged_json)
        
        return True, f"成功合并 {base_name} 到 {os.path.basename(target_file)}"
    
    except Exception as e:
        return False, f"合并失败: {str(e)}"


def _merge_texture_json(target_json, source_json):
    """合并含texture_data的文件，如terrain_texture.json和item_texture.json"""
    if 'texture_data' in source_json and 'texture_data' in target_json:
        # 合并texture_data字段
        for texture_key, texture_value in source_json['texture_data'].items():
            target_json['texture_data'][texture_key] = texture_value
        return target_json
    else:
        # 如果没有texture_data字段，进行普通的浅合并
        return _merge_dicts_shallow(target_json, source_json)


def _merge_sound_json(target_json, source_json):
    """合并声音定义文件"""
    # 处理sounds.json和sound_definitions.json
    if 'sound_definitions' in source_json and 'sound_definitions' in target_json:
        # 合并sound_definitions字段
        for sound_key, sound_value in source_json['sound_definitions'].items():
            target_json['sound_definitions'][sound_key] = sound_value
        return target_json
    else:
        # 如果没有特定结构，进行浅合并
        return _merge_dicts_shallow(target_json, source_json)


def _merge_animation_json(target_json, source_json):
    """合并动画文件"""
    # 处理animations.json和animation_controllers.json
    # 这些文件可能有多个顶级节点如animations, animation_controllers等
    for key in source_json:
        if key in target_json and isinstance(source_json[key], dict) and isinstance(target_json[key], dict):
            # 合并animations或animation_controllers等字段
            for anim_key, anim_value in source_json[key].items():
                target_json[key][anim_key] = anim_value
        else:
            # 对于其他字段，直接覆盖
            target_json[key] = source_json[key]
    return target_json


def _merge_registry_json(target_json, source_json):
    """合并包含多个注册项的文件"""
    # 处理entity_models.json, render_controllers.json等
    # 这些文件通常有一个或多个命名空间，每个命名空间下有多个定义
    for key in source_json:
        if key in target_json:
            if isinstance(source_json[key], dict) and isinstance(target_json[key], dict):
                # 如果是嵌套字典，合并子项
                for sub_key, sub_value in source_json[key].items():
                    target_json[key][sub_key] = sub_value
            else:
                # 非字典类型，直接覆盖
                target_json[key] = source_json[key]
        else:
            # 新的顶级字段，直接添加
            target_json[key] = source_json[key]
    return target_json


def _merge_dicts_shallow(dict1, dict2):
    """浅合并两个字典"""
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result and isinstance(result[key], list) and isinstance(value, list):
            # 合并列表
            result[key].extend(value)
        else:
            # 覆盖或添加新键
            result[key] = value
    return result

def _merge_dicts_deep(dict1, dict2):
    """递归合并两个字典"""
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # 递归合并嵌套字典
            result[key] = _merge_dicts_deep(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            # 合并列表
            result[key].extend(value)
        else:
            # 覆盖或添加新键
            result[key] = value
    return result
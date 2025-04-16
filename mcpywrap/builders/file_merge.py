# -*- coding: utf-8 -*-
"""
文件合并模块 - 提供文件合并功能
"""
import os
import shutil
import json
import click
from typing import Dict, Any, Tuple, Optional, List, Set


def _read_json_file(file_path) -> Dict[str, Any]:
    """从文件中读取并解析JSON内容"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.loads(f.read())
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON解析错误: {str(e)}")
    except Exception as e:
        raise ValueError(f"读取文件错误: {str(e)}")


def _write_json_file(file_path, content) -> bool:
    """将JSON内容写入文件"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(content, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        raise ValueError(f"写入文件错误: {str(e)}")


def _merge_ui_defs_json(target_json, source_json) -> Dict[str, Any]:
    """合并 ui_defs.json 文件"""
    if 'ui_defs' in source_json and 'ui_defs' in target_json:
        # 合并 ui_defs 数组，去重
        target_ui_defs = set(target_json['ui_defs'])
        source_ui_defs = set(source_json['ui_defs'])
        target_json['ui_defs'] = list(target_ui_defs.union(source_ui_defs))
        return target_json
    else:
        # 如果没有 ui_defs 字段，进行普通的浅合并
        return _merge_dicts_shallow(target_json, source_json)


def _read_lang_file(file_path) -> Dict[str, str]:
    """从文件中读取并解析.lang内容"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # 将文件内容按行分割
            lines = content.splitlines()
            # 解析键值对
            lang_dict = {}
            for line in lines:
                # 跳过空行和注释
                if not line.strip() or line.strip().startswith('#'):
                    continue
                # 分割键值对
                if '=' in line:
                    key, value = line.split('=', 1)
                    lang_dict[key.strip()] = value.strip()
            return lang_dict
    except Exception as e:
        raise ValueError(f"读取.lang文件错误: {str(e)}")


def _write_lang_file(file_path, content) -> bool:
    """将.lang内容写入文件"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            # 将字典转换为字符串
            lines = [f"{key}={value}" for key, value in content.items()]
            f.write('\n'.join(lines))
        return True
    except Exception as e:
        raise ValueError(f"写入.lang文件错误: {str(e)}")


def _merge_lang_file(target_json, source_json) -> Dict[str, str]:
    """合并.lang文件"""
    # 合并两个字典，源文件的键值对会覆盖目标文件的相同键
    merged = target_json.copy()
    merged.update(source_json)
    return merged


def try_merge_file(source_file, target_file, source_dependency_name=None) -> Tuple[bool, Optional[str]]:
    """
    合并两个文件的内容
    
    Args:
        source_file: 源文件路径
        target_file: 目标文件路径
        source_dependency_name: 源文件所属的依赖包名称（用于日志）
        
    Returns:
        Tuple[bool, Optional[str]]: (是否成功, 错误信息)
    """
    try:
        if os.path.basename(source_file) in ['manifest.json', 'pack_manifest.json']:
            return True, "跳过合并 manifest 文件"
        # 如果是py文件，直接复制即可
        if source_file.endswith('.py'):
            # 直接复制
            shutil.copy2(source_file, target_file)
            return True, f"成功复制 {os.path.basename(source_file)}"
        
        # 获取文件名
        base_name = os.path.basename(source_file)
        
        # 记录操作类型
        dep_info = f"(来自依赖: {source_dependency_name})" if source_dependency_name else ""
        
        # 根据不同文件类型进行不同处理
        if base_name.endswith('.lang'):
            # 处理.lang文件
            source_lang = _read_lang_file(source_file)
            target_lang = _read_lang_file(target_file)
            merged_lang = _merge_lang_file(target_lang, source_lang)
            _write_lang_file(target_file, merged_lang)
            return True, f"成功合并 {base_name} 到 {os.path.basename(target_file)}"
        
        if base_name.endswith('.png') or base_name.endswith('.jpg') or base_name.endswith('.jpeg') or base_name.endswith('.tga'):
            # 直接覆盖，并给出警告
            shutil.copy2(source_file, target_file)
            click.secho(f"⚠️ 警告: {base_name} 图片文件重复，正在覆盖", fg="yellow")
            return True, f"强制覆盖 {base_name} 到 {os.path.basename(target_file)}"
        
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
        elif base_name == "_ui_defs.json":
            # 特殊处理 UI 定义文件
            merged_json = _merge_ui_defs_json(target_json, source_json)
        else:
            # 对于不支持的JSON文件类型，提示不支持
            error_msg = f"不支持的文件类型: {base_name} {dep_info}"
            return False, error_msg
        
        # 写入合并后的内容到目标文件
        _write_json_file(target_file, merged_json)
        
        return True, f"成功合并 {base_name} 到 {os.path.basename(target_file)}"
    
    except Exception as e:
        error_msg = f"合并失败: {str(e)}"
        click.secho(f"❌ {error_msg}", fg="red")
        return False, error_msg


def _merge_texture_json(target_json, source_json) -> Dict[str, Any]:
    """合并含texture_data的文件，如terrain_texture.json和item_texture.json"""
    if 'texture_data' in source_json and 'texture_data' in target_json:
        # 合并texture_data字段
        for texture_key, texture_value in source_json['texture_data'].items():
            target_json['texture_data'][texture_key] = texture_value
        return target_json
    else:
        # 如果没有texture_data字段，进行普通的浅合并
        return _merge_dicts_shallow(target_json, source_json)


def _merge_sound_json(target_json, source_json) -> Dict[str, Any]:
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


def _merge_animation_json(target_json, source_json) -> Dict[str, Any]:
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


def _merge_registry_json(target_json, source_json) -> Dict[str, Any]:
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


def _merge_dicts_shallow(dict1, dict2) -> Dict[str, Any]:
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


def _merge_dicts_deep(dict1, dict2) -> Dict[str, Any]:
    """递归合并两个字典"""
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # 递归合并嵌套字典
            result[key] = _merge_dicts_deep(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            # 合并列表，尝试去重
            combined_list = result[key].copy()
            for item in value:
                if isinstance(item, dict) and any(isinstance(existing, dict) and 
                                              all(existing.get(k) == item.get(k) for k in item) 
                                              for existing in combined_list):
                    # 如果是具有相同键值的字典，则不添加
                    continue
                combined_list.append(item)
            result[key] = combined_list
        else:
            # 覆盖或添加新键
            result[key] = value
    return result
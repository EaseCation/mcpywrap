# -- coding: utf-8 -*-
import os

def try_merge_file(source_file, target_file):
    """合并两个JSON文件的内容"""
    # 如果文件名为blocks.json
    if os.path.basename(source_file) == "blocks.json":
        # TODO
        pass
    # 直接复制
    
    """ # 读取源文件
    with open(source_file, 'r', encoding='utf-8') as f:
        source_data = json.load(f)
    
    # 读取目标文件（如果存在）
    target_data = {}
    if os.path.exists(target_file):
        with open(target_file, 'r', encoding='utf-8') as f:
            target_data = json.load(f)
    
    # 合并数据（对于列表，进行拼接；对于字典，进行深度合并）
    if isinstance(source_data, list) and isinstance(target_data, list):
        # 简单列表合并
        merged_data = target_data + source_data
    elif isinstance(source_data, dict) and isinstance(target_data, dict):
        # 递归字典合并
        merged_data = _merge_dicts(target_data, source_data)
    else:
        # 类型不一致，无法合并
        return False, f"文件类型不一致，无法合并: {source_file} 与 {target_file}"
    
    # 写回目标文件
    with open(target_file, 'w', encoding='utf-8') as f:
        json.dump(merged_data, f, indent=2, ensure_ascii=False)
    
    return True, f"成功合并 {os.path.basename(source_file)}" """

def _merge_dicts(dict1, dict2):
    """递归合并两个字典"""
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # 递归合并嵌套字典
            result[key] = _merge_dicts(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            # 合并列表
            result[key].extend(value)
        else:
            # 覆盖或添加新键
            result[key] = value
    return result
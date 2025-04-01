# -*- coding: utf-8 -*-
import os
import shutil


def try_merge_file(source_file, target_file) -> tuple[bool, str]:
    """合并两个JSON文件的内容"""
    # 如果是py文件，直接复制即可
    if source_file.endswith('.py'):
        # 直接复制
        shutil.copy2(source_file, target_file)
        return True, f"成功复制 {os.path.basename(source_file)}"
    else:
        # 读取源文件内容
        with open(source_file, 'r', encoding='utf-8') as f:
            source_content = f.read()

        # 读取目标文件内容
        with open(target_file, 'r', encoding='utf-8') as f:
            target_content = f.read()

        # 合并两个JSON对象
        try:
            source_json = eval(source_content)
            target_json = eval(target_content)
            merged_json = _merge_dicts(target_json, source_json)

            # 写入合并后的内容到目标文件
            with open(target_file, 'w', encoding='utf-8') as f:
                f.write(str(merged_json))

            return True, f"成功合并 {os.path.basename(source_file)} 到 {os.path.basename(target_file)}"
        except Exception as e:
            return False, f"合并失败: {str(e)}"

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
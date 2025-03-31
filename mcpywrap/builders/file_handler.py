# -*- coding: utf-8 -*-
"""
文件处理模块 - 负责单个文件的复制和转换
"""

import os
import shutil
from ..utils.utils import ensure_dir, run_command

def is_python_file(file_path):
    """判断是否为Python文件"""
    return file_path.endswith('.py')

def copy_file(src_path, dest_path):
    """复制文件，确保目标目录存在"""
    dest_dir = os.path.dirname(dest_path)
    ensure_dir(dest_dir)
    shutil.copy2(src_path, dest_path)
    return dest_path

def convert_py3_to_py2(file_path):
    """将Python 3文件转换为Python 2"""
    success, output = run_command(["3to2", "-w", "-n", file_path])
    return success, output

def process_file(src_path, source_dir, target_dir):
    """处理单个文件（复制并根据文件类型处理）"""
    # 计算相对路径和目标路径
    rel_path = os.path.relpath(src_path, source_dir)
    dest_path = os.path.join(target_dir, rel_path)
    
    # 复制文件
    copy_file(src_path, dest_path)
    
    # 如果是Python文件，进行转换
    if is_python_file(src_path):
        success, output = convert_py3_to_py2(dest_path)
        return success, output, dest_path
    
    # 如果是其他类型文件，直接返回成功
    return True, "", dest_path

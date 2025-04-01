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
    """将某个Python文件转换为Python 2"""
    try:
        # 首先尝试使用直接的Python API调用
        from lib3to2.main import main
        # main函数接受包名和参数列表
        # 第一个参数是包名 'lib3to2' (这是3to2所有修复器的位置)
        # 第二个参数是命令行参数列表
        exit_code = main('lib3to2.fixes', ['-w', '-n', '--no-diffs', file_path])
        return exit_code == 0, "转换完成" if exit_code == 0 else f"转换失败，错误代码: {exit_code}"
    except Exception as e:
        # 如果直接调用失败，则尝试命令行方式（作为备选）
        try:
            # 方法1：直接命令行调用
            success, output = run_command(["3to2", "-w", "-n", file_path])
            if not success:
                # 方法2：使用shell=True参数
                success, output = run_command(["3to2", "-w", "-n", file_path], shell=True)
            
            return success, output
        except Exception as cmd_e:
            return False, f"Python API调用失败: {str(e)}\n命令行调用也失败: {str(cmd_e)}"

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

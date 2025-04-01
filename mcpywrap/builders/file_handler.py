# -*- coding: utf-8 -*-
"""
文件处理模块 - 负责单个文件的复制和转换
"""

import os
import shutil

from ..utils.py3to2_util import py3_to_2
from ..utils.utils import ensure_dir, run_command
from .file_merge import try_merge_file

def is_python_file(file_path):
    """判断是否为Python文件"""
    return file_path.endswith('.py')

def copy_file(src_path, dest_path):
    """复制文件，确保目标目录存在"""
    dest_dir = os.path.dirname(dest_path)
    ensure_dir(dest_dir)
    print(f"复制文件: {src_path} 到 {dest_path}")
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
        exit_code = main('lib3to2.fixes', ['-w', '-n', '--no-diffs', file_path, '--nofix=metaclass'])
        # exit_code = py3_to_2(file_path)
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

def process_file(src_path, source_dir, target_dir, is_dependency=False, dependency_name=None):
    """处理单个文件（复制并根据文件类型处理）"""
    # 计算相对路径和目标路径
    rel_path = os.path.relpath(src_path, source_dir)
    
    # 如果是依赖项，需要特殊处理目标路径
    if is_dependency:
        # 确定是属于行为包还是资源包
        if "behavior_pack" in src_path.lower() or "behaviorpack" in src_path.lower():
            # 在路径中定位behavior_pack部分
            parts = src_path.split(os.sep)
            for i, part in enumerate(parts):
                if "behavior_pack" in part.lower() or "behaviorpack" in part.lower():
                    # 获取behavior_pack后的相对路径
                    sub_path = os.path.join(*parts[i+1:])
                    # 目标路径应该是behavior_pack目录
                    for item in os.listdir(target_dir):
                        if "behavior_pack" in item.lower() or "behaviorpack" in item.lower():
                            dest_path = os.path.join(target_dir, item, sub_path)
                            break
                    else:
                        # 如果找不到behavior_pack目录，创建一个
                        dest_path = os.path.join(target_dir, "behavior_pack", sub_path)
                    break
        elif "resource_pack" in src_path.lower() or "resourcepack" in src_path.lower():
            # 在路径中定位resource_pack部分
            parts = src_path.split(os.sep)
            for i, part in enumerate(parts):
                if "resource_pack" in part.lower() or "resourcepack" in part.lower():
                    # 获取resource_pack后的相对路径
                    sub_path = os.path.join(*parts[i+1:])
                    # 目标路径应该是resource_pack目录
                    for item in os.listdir(target_dir):
                        if "resource_pack" in item.lower() or "resourcepack" in item.lower():
                            dest_path = os.path.join(target_dir, item, sub_path)
                            break
                    else:
                        # 如果找不到resource_pack目录，创建一个
                        dest_path = os.path.join(target_dir, "resource_pack", sub_path)
                    break
        else:
            # 如果不在行为包或资源包中，忽略该文件
            return False, "不在行为包或资源包中的文件将被忽略", None
    else:
        dest_path = os.path.join(target_dir, rel_path)

    # 检查目标文件是否已存在，如果存在且来自依赖，尝试合并
    if is_dependency and os.path.exists(dest_path):
        suc, reason = try_merge_file(src_path, dest_path)
        if not suc:
            # 如果合并失败或有冲突，直接返回
            msg = f"文件合并失败或存在冲突" if reason is None else reason
            return False, msg, dest_path
    else:
        # 复制文件
        copy_file(src_path, dest_path)

    # 如果是Python文件，进行转换
    if is_python_file(src_path):
        success, output = convert_py3_to_py2(dest_path)
        return success, output, dest_path

    # 如果是其他类型文件，直接返回成功
    return True, "", dest_path
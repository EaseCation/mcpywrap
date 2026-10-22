# -*- coding: utf-8 -*-

"""
通用工具函数
"""
import subprocess
from pathlib import Path
import sys
import click

def validate_path(path_str):
    """验证路径是否有效"""
    path = Path(path_str).expanduser().resolve()
    return path.exists()

def ensure_dir(path_str):
    """确保目录存在，如果不存在则创建"""
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        path.mkdir(parents=True)
    return str(path)

def run_command(cmd, cwd=None, shell=False):
    """运行系统命令"""
    try:
        result = subprocess.run(
            cmd, 
            cwd=cwd, 
            shell=shell,
            check=True, 
            text=True, 
            capture_output=True
        )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr

# 移除DynamicOutput类的定义

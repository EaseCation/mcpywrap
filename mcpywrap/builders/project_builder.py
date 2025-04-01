# -*- coding: utf-8 -*-
"""
项目构建模块 - 负责整个项目的构建过程
"""

import os
import shutil
import sys
import json
from pathlib import Path
from .file_merge import try_merge_file
import click

from ..utils.utils import ensure_dir, run_command
from ..config import get_project_dependencies, read_config
from .file_handler import process_file, is_python_file

# Python 包管理和其他应该忽略的文件和目录
EXCLUDED_PATTERNS = [
    # Python 包管理
    ".egg-info",
    "__pycache__",
    ".pyc",
    ".pyo",
    ".pyd",
    ".so",
    ".dll",
    ".eggs",
    ".pytest_cache",
    ".tox",
    ".coverage",
    ".coverage.*",
    "htmlcov",
    # 版本控制
    ".git",
    ".hg",
    ".svn",
    ".bzr",
    # 项目特定
    "manifest.json",
    "pack_manifest.json",
    # 其他临时文件
    ".DS_Store",
    "Thumbs.db"
]

def should_exclude(path):
    """判断文件或目录是否应该被排除"""
    for pattern in EXCLUDED_PATTERNS:
        if pattern in path:
            return True
    return False


class AddonsPack(object):

    pkg_name: str
    path: str
    behavior_pack_dir: str
    resource_pack_dir: str

    def __init__(self, pkg_name, path):
        self.pkg_name = pkg_name
        self.path = path
        self.behavior_pack_dir = None
        self.resource_pack_dir = None
        # 进入此目录，查找内部的行为包和资源包的路径
        os.chdir(self.path)
        for item in os.listdir(self.path):
            item_path = os.path.join(self.path, item)
            if os.path.isdir(item_path):
                if item.startswith("behavior_pack") or item.startswith("BehaviorPack"):
                    self.behavior_pack_dir = item_path
                elif item.startswith("resource_pack") or item.startswith("ResourcePack"):
                    self.resource_pack_dir = item_path
        if not self.behavior_pack_dir:
            self.behavior_pack_dir = os.path.join(self.path, "behavior_pack")
        if not self.resource_pack_dir:
            self.resource_pack_dir = os.path.join(self.path, "resource_pack")

    def copy_behavior_to(self, target_dir: str):
        """复制行为包和资源包到目标目录"""
        if self.behavior_pack_dir:
            target_path = os.path.join(target_dir, os.path.basename(self.behavior_pack_dir))
            os.makedirs(target_path, exist_ok=True)
            
            # 使用自定义复制函数而不是shutil.copytree
            for root, dirs, files in os.walk(self.behavior_pack_dir):
                # 过滤掉应该排除的目录
                dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d))]
                
                # 计算相对路径
                rel_path = os.path.relpath(root, self.behavior_pack_dir)
                # 计算目标目录
                target_root = os.path.join(target_path, rel_path) if rel_path != '.' else target_path
                ensure_dir(target_root)
                
                # 复制文件
                for file in files:
                    src_file = os.path.join(root, file)
                    if not should_exclude(src_file):
                        dest_file = os.path.join(target_root, file)
                        shutil.copy2(src_file, dest_file)
    
    def copy_resource_to(self, target_dir: str):
        """复制资源包到目标目录"""
        if self.resource_pack_dir:
            target_path = os.path.join(target_dir, os.path.basename(self.resource_pack_dir))
            os.makedirs(target_path, exist_ok=True)
            
            # 使用自定义复制函数而不是shutil.copytree
            for root, dirs, files in os.walk(self.resource_pack_dir):
                # 过滤掉应该排除的目录
                dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d))]
                
                # 计算相对路径
                rel_path = os.path.relpath(root, self.resource_pack_dir)
                # 计算目标目录
                target_root = os.path.join(target_path, rel_path) if rel_path != '.' else target_path
                ensure_dir(target_root)
                
                # 复制文件
                for file in files:
                    src_file = os.path.join(root, file)
                    if not should_exclude(src_file):
                        dest_file = os.path.join(target_root, file)
                        shutil.copy2(src_file, dest_file)

    def merge_behavior_into(self, target_behavior_dir: str):
        """合并行为包到目标行为包目录"""
        if self.behavior_pack_dir:
            for root, dirs, files in os.walk(self.behavior_pack_dir):
                # 过滤掉应该排除的目录
                dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d))]
                
                # 计算相对路径
                rel_path = os.path.relpath(root, self.behavior_pack_dir)
                # 计算目标目录
                target_root = os.path.join(target_behavior_dir, rel_path) if rel_path != '.' else target_behavior_dir
                ensure_dir(target_root)
                
                # 复制文件
                for file in files:
                    src_file = os.path.join(root, file)
                    if should_exclude(src_file):
                        continue
                        
                    dest_file = os.path.join(target_root, file)
                    # 处理文件冲突
                    if os.path.exists(dest_file):
                        result = try_merge_file(src_file, dest_file)
                        if result is not None:
                            click.secho(f"❌ 未处理的文件冲突: {src_file} -> {dest_file}", fg="red")
                    else:
                        shutil.copy2(src_file, dest_file)
    
    def merge_resource_into(self, target_resource_dir: str):
        """合并资源包到目标资源包目录"""
        if self.resource_pack_dir:
            for root, dirs, files in os.walk(self.resource_pack_dir):
                # 过滤掉应该排除的目录
                dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d))]
                
                # 计算相对路径
                rel_path = os.path.relpath(root, self.resource_pack_dir)
                # 计算目标目录
                target_root = os.path.join(target_resource_dir, rel_path) if rel_path != '.' else target_resource_dir
                ensure_dir(target_root)
                
                # 复制文件
                for file in files:
                    src_file = os.path.join(root, file)
                    if should_exclude(src_file):
                        continue
                        
                    dest_file = os.path.join(target_root, file)
                    # 处理文件冲突
                    if os.path.exists(dest_file):
                        result = try_merge_file(src_file, dest_file)
                        if result is None:
                            # try_merge_file 返回 None 的情况
                            click.secho(f"⚠️ 警告: 文件合并函数返回值异常 {src_file} -> {dest_file}", fg="yellow")
                            shutil.copy2(src_file, dest_file)
                        else:
                            success, msg = result
                            if not success:
                                click.secho(f"❌ 文件冲突: {src_file} -> {dest_file}", fg="red")
                                click.secho(f"   {msg}", fg="red")
                    else:
                        shutil.copy2(src_file, dest_file)


def clear_directory(directory):
    """清空目录内容但保留目录本身"""
    for item in os.listdir(directory):
        item_path = os.path.join(directory, item)
        if os.path.isdir(item_path):
            shutil.rmtree(item_path)
        else:
            os.remove(item_path)

def convert_project_py3_to_py2(directory):
    """将整个项目中的Python文件转换为Python 2"""
    try:
        # 首先尝试使用直接的Python API调用
        from lib3to2.main import main
        # main函数接受包名和参数列表
        # 第一个参数是包名 'lib3to2' (这是3to2所有修复器的位置)
        # 第二个参数是命令行参数列表
        print(f"正在转换目录: {directory}")
        exit_code = main('lib3to2.fixes', ['-w', '-n', '-j', '8', '--no-diffs', directory])
        return exit_code == 0, "转换完成" if exit_code == 0 else f"转换失败，错误代码: {exit_code}"
    except Exception as e:
        # 如果直接调用失败，则尝试命令行方式（作为备选）
        try:
            # 方法1：直接命令行调用
            success, output = run_command(["3to2", "-w", "-n", directory])
            if not success:
                # 方法2：使用shell=True参数
                success, output = run_command(["3to2", "-w", "-n", directory], shell=True)
            
            return success, output
        except Exception as cmd_e:
            return False, f"Python API调用失败: {str(e)}\n命令行调用也失败: {str(cmd_e)}"

def find_mcpywrap_dependencies(dependencies: list[str]) -> dict[str, AddonsPack]:
    """
    查找依赖包的真实路径，支持常规安装和 pip install -e（编辑安装）。
    """
    # 记录依赖包的路径
    dep_paths = {}
    # 得到site-packages路径
    site_packages = Path(__import__('site').getsitepackages()[0])
    for dist_info in site_packages.glob("*.dist-info"):
        # 读取METADATA文件获取真实包名
        metadata_path = dist_info / "METADATA"
        if metadata_path.exists():
            pkg_name = None
            with open(metadata_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith("Name:"):
                        pkg_name = line.split(":", 1)[1].strip()
                        break
            
            if not pkg_name or pkg_name not in dependencies:
                continue
                
            # 处理direct_url.json获取包路径
            direct_url_path = dist_info / "direct_url.json"
            if direct_url_path.exists():
                with open(direct_url_path, 'r', encoding='utf-8') as f:
                    direct_url = json.load(f)
                    # 读取其中的url
                    if "url" in direct_url:
                        url = direct_url["url"]
                        # 处理file://开头的路径
                        if url.startswith("file://"):
                            url = url[7:]
                            url = os.path.abspath(url)
                            if sys.platform == "win32":
                                url = url.replace("\\", "/")
                        dep_paths[pkg_name] = AddonsPack(pkg_name, url)
                    else:
                        print(f"⚠️ 警告: {pkg_name} 的direct_url.json中没有url字段")
            else:
                print(f"⚠️ 警告: {pkg_name} 没有找到direct_url.json文件")
        
    return dep_paths

def build_project(source_dir, target_dir):
    """
    构建整个项目：
    1. 复制所有项目文件
    2. 复制并合并所有依赖项的文件
    3. 转换所有Python文件
    4. 报告冲突
    """
    # 先清空
    clear_directory(target_dir)

    # 复制项目文件
    config = read_config()
    project_name = config.get('project', {}).get('name', 'current_project')
    current_addons = AddonsPack(project_name, source_dir)

    # 复制基础
    current_addons.copy_behavior_to(target_dir)
    current_addons.copy_resource_to(target_dir)

    target_addons = AddonsPack(project_name, target_dir)
    
    # 查找并处理所有mcpywrap依赖
    dependencies_list = config.get('project', {}).get('dependencies', [])
    dependencies = find_mcpywrap_dependencies(dependencies_list)
    click.secho(f"✅ 找到 {len(dependencies)} 个依赖包", fg="green")
    for dep in dependencies:
        click.secho(f" 📦 {dep} → {dependencies[dep].path}", fg="green")
    
    for dep in dependencies:
        dependencies[dep].merge_behavior_into(target_addons.behavior_pack_dir)
        dependencies[dep].merge_resource_into(target_addons.resource_pack_dir)
    
    # 转换Python文件
    success, output = convert_project_py3_to_py2(target_dir)
    
    return success, output

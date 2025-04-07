# -*- coding: utf-8 -*-
"""
项目构建模块 - 负责整个项目的构建过程
"""

import os
import shutil
import sys
import json
from pathlib import Path
import click

from ..utils.py3to2_util import py3_to_2
from ..utils.utils import run_command
from ..config import read_config, CONFIG_FILE, get_use_3to2
from .AddonsPack import AddonsPack


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
        exit_code = main('lib3to2.fixes', ['-w', '-n', '-j', '4', '--no-diffs', directory, '--nofix=metaclass'])
        #exit_code = py3_to_2(directory)
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
    for site_package_dir in __import__('site').getsitepackages():
        site_packages = Path(site_package_dir)
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
                            if url.startswith("file:///"):
                                # 移除file:/// 前缀
                                if sys.platform == "win32":
                                    # Windows 路径处理 (例如 file:///D:/path)
                                    url = url[8:]  # 去除 file:///
                                else:
                                    url = "/" + url[8:]  # 保留根目录斜杠
                                url = os.path.abspath(url)
                            # 兼容处理旧格式 file://
                            elif url.startswith("file://"):
                                url = url[7:]
                            # 对URL进行解码，处理%编码的特殊字符
                            from urllib.parse import unquote
                            url = unquote(url)
                            url = os.path.abspath(url)

                            # 确保路径格式一致
                            if sys.platform == "win32":
                                url = url.replace("\\", "/")

                            dep_paths[pkg_name] = AddonsPack(pkg_name, url)
                        else:
                            click.secho(f"⚠️ 警告: {pkg_name} 的direct_url.json中没有url字段", fg="yellow")
                else:
                    click.secho(f"⚠️ 警告: {pkg_name} 没有找到direct_url.json文件", fg="yellow")

    # 检查是否所有依赖都已找到
    missing_deps = [dep for dep in dependencies if dep not in dep_paths]
    if missing_deps:
        click.secho(f"⚠️ 警告: 未找到以下依赖包: {', '.join(missing_deps)}", fg="yellow")

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
    config = read_config(os.path.join(source_dir, CONFIG_FILE))
    project_name = config.get('project', {}).get('name', 'current_project')
    origin_addons = AddonsPack(project_name, source_dir, is_origin=True)

    # 复制基础
    origin_addons.copy_behavior_to(target_dir)
    origin_addons.copy_resource_to(target_dir)

    target_addons = AddonsPack(project_name, target_dir)

    # 查找并处理所有mcpywrap依赖
    dependencies_list = config.get('project', {}).get('dependencies', [])
    dependencies = find_mcpywrap_dependencies(dependencies_list)
    click.secho(f"✅ 找到 {len(dependencies)} 个依赖包", fg="green")
    for dep in dependencies:
        click.secho(f" 📦 {dep} → {dependencies[dep].path}", fg="green")
    for origin, dep in dependencies.items():
        if origin not in dependencies:
            click.secho(f"⚠️ 警告: 找不到依赖包 {origin}", fg="yellow")
            continue

    for dep in dependencies:
        dependencies[dep].merge_behavior_into(target_addons.behavior_pack_dir)
        dependencies[dep].merge_resource_into(target_addons.resource_pack_dir)

    # 转换Python文件
    if get_use_3to2():
        success, output = convert_project_py3_to_py2(target_dir)
        return success, output

    return True, None

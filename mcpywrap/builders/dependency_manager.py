# -*- coding: utf-8 -*-
"""
依赖管理模块 - 负责处理项目依赖关系和依赖树构建
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set
import click

from ..config import CONFIG_FILE, check_has_mcpywrap_config
from .AddonsPack import AddonsPack

class DependencyNode:
    """依赖树节点"""
    def __init__(self, name: str, addon_pack: AddonsPack, parent=None):
        self.name = name
        self.addon_pack: AddonsPack = addon_pack
        self.parent = parent
        self.children: List[DependencyNode] = []
        
    def add_child(self, child_node):
        """添加子节点"""
        self.children.append(child_node)
        
    def __str__(self):
        return f"{self.name} -> {[child.name for child in self.children]}"
        
    def __repr__(self):
        return self.__str__()
    

def _decode_direct_url(direct_url_path: str) -> Optional[str]:
    with open(direct_url_path, 'r', encoding='utf-8') as f:
        try:
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

                return url
        except json.JSONDecodeError:
            logging.warning(f"无法解析 {direct_url_path} 的JSON内容")

class DependencyManager:
    """依赖管理器"""
    def __init__(self):
        self.dependency_map: Dict[str, AddonsPack] = {}
        self.root_node: Optional[DependencyNode] = None
        self.processed_deps: Set[str] = set()

    def find_dependency_path(self, package_name: str) -> Optional[str]:
        """
        查找依赖包的真实路径，支持常规安装和pip install -e (编辑安装)
        """
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

                    if not pkg_name or pkg_name != package_name:
                        continue

                    # 处理direct_url.json获取包路径
                    direct_url_path = dist_info / "direct_url.json"
                    if direct_url_path.exists():
                        origin_path = _decode_direct_url(str(direct_url_path))
                        if origin_path:
                            # 返回绝对路径
                            return origin_path
                        continue
        return None
    
    def build_dependency_tree(self, project_name: str, project_path: str, dependencies: List[str]) -> DependencyNode:
        """
        构建依赖树
        
        Args:
            project_name: 主项目名称
            project_path: 主项目路径
            dependencies: 依赖列表
            
        Returns:
            DependencyNode: 依赖树根节点
        """
        # 创建根节点(主项目)
        root_addon = AddonsPack(project_name, project_path, is_origin=True)
        self.root_node = DependencyNode(project_name, root_addon)
        self.processed_deps = {project_name}  # 防止循环依赖
        
        # 递归构建依赖树
        self._process_dependencies(self.root_node, dependencies)
        
        return self.root_node
    
    def _process_dependencies(self, parent_node: DependencyNode, dependencies: List[str]):
        """
        递归处理依赖
        
        Args:
            parent_node: 父节点
            dependencies: 依赖列表
        """
        for dep_name in dependencies:
            # 防止循环依赖
            if dep_name in self.processed_deps:
                continue
                
            # 查找依赖路径
            dep_path = self.find_dependency_path(dep_name)
            if not dep_path:
                click.secho(f"⚠️ 警告: 未找到依赖包: {dep_name}", fg="yellow")
                continue
                
            # 创建依赖的AddonsPack
            dep_addon = AddonsPack(dep_name, dep_path)
            self.dependency_map[dep_name] = dep_addon
            
            # 创建依赖节点并添加到父节点
            dep_node = DependencyNode(dep_name, dep_addon, parent_node)
            parent_node.add_child(dep_node)
            
            # 标记为已处理
            self.processed_deps.add(dep_name)
            
            # 读取子依赖的配置文件，并递归处理子依赖
            try:
                from ..config import read_config, CONFIG_FILE
                config_file_path = os.path.join(dep_path, CONFIG_FILE)
                if os.path.exists(config_file_path):
                    config = read_config(config_file_path)
                    sub_dependencies = config.get('project', {}).get('dependencies', [])
                    if sub_dependencies:
                        click.secho(f"🔍 找到 {dep_name} 的子依赖: {', '.join(sub_dependencies)}", fg="cyan")
                        # 递归处理子依赖
                        self._process_dependencies(dep_node, sub_dependencies)
                    else:
                        click.secho(f"📦 {dep_name} 没有子依赖", fg="cyan")
                else:
                    click.secho(f"⚠️ 警告: 依赖包 {dep_name} 中未找到配置文件", fg="yellow")
            except Exception as e:
                click.secho(f"⚠️ 警告: 处理 {dep_name} 的子依赖时出错: {str(e)}", fg="yellow")
            
    def get_all_dependencies(self) -> Dict[str, AddonsPack]:
        """获取所有依赖"""
        return self.dependency_map
        
    def get_dependency_tree(self) -> Optional[DependencyNode]:
        """获取依赖树"""
        return self.root_node


def find_all_mcpywrap_packages() -> List[str]:
        packages = []
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
                    if pkg_name is None:
                        continue
                    # 处理direct_url.json获取包路径
                    direct_url_path = dist_info / "direct_url.json"
                    if direct_url_path.exists():
                        origin_path = _decode_direct_url(str(direct_url_path))
                        if origin_path:
                            if check_has_mcpywrap_config(os.path.join(origin_path, CONFIG_FILE)):
                                packages.append(pkg_name)
        return packages
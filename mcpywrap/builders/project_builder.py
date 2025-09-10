# -*- coding: utf-8 -*-
"""
项目构建模块 - 负责整个项目的构建过程
"""

import os
import shutil
import click
from typing import Dict, List, Tuple, Optional

from ..config import read_config, CONFIG_FILE
from .AddonsPack import AddonsPack
from .MapPack import MapPack
from .dependency_manager import DependencyManager, DependencyNode
from ..utils.utils import run_command


class AddonProjectBuilder:
    """项目构建器"""
    def __init__(self, source_dir: str, target_dir: str):
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.config = read_config(os.path.join(source_dir, CONFIG_FILE))
        self.project_name = self.config.get('project', {}).get('name', 'current_project')
        self.dependency_manager = DependencyManager()
        self.dependency_tree = None
        self.origin_addon = None
        self.target_addon = None
        
    def initialize(self) -> bool:
        """初始化构建环境"""
        # 验证目标目录
        if not self.target_dir:
            click.secho('❌ 错误: 未指定目标目录。', fg="red")
            return False
            
        # 确保目标目录存在
        if not os.path.exists(self.target_dir):
            os.makedirs(self.target_dir)
            click.secho(f'🔧 创建目标目录: {self.target_dir}', fg="yellow")
            
        # 清空目标目录
        _clear_directory(self.target_dir)
        
        # 创建源项目的AddonsPack对象
        self.origin_addon = AddonsPack(self.project_name, self.source_dir, is_origin=True)
        
        # 获取依赖列表
        dependencies_list = self.config.get('project', {}).get('dependencies', [])
        
        # 构建依赖树
        self.dependency_tree = self.dependency_manager.build_dependency_tree(
            self.project_name, 
            self.source_dir, 
            dependencies_list
        )
        
        return True
                
    def build(self) -> Tuple[bool, Optional[str]]:
        """
        执行构建过程
        
        Returns:
            Tuple[bool, Optional[str]]: (是否成功, 错误信息)
        """
        click.secho(f'📂 正在将源代码从 ', fg="bright_blue", nl=False)
        click.secho(f'{self.source_dir}', fg="bright_cyan", nl=False)
        click.secho(' 复制到 ', fg="bright_blue", nl=False)
        click.secho(f'{self.target_dir}', fg="bright_cyan", nl=False)
        click.secho('...', fg="bright_blue")
        
        click.secho('🔄 正在构建项目与代码...', fg="yellow")
        
        # 初始化构建环境
        if not self.initialize():
            return False, "初始化构建环境失败"
            
        # 复制原始项目文件
        self.origin_addon.copy_behavior_to(self.target_dir)
        self.origin_addon.copy_resource_to(self.target_dir)
        
        # 获取目标AddonsPack对象
        self.target_addon = AddonsPack(self.project_name, self.target_dir)
        
        # 处理依赖
        dependencies = self.dependency_manager.get_all_dependencies()
        if dependencies:
            dep_count = len(dependencies)
            click.secho(f"✅ 找到 {dep_count} 个依赖包", fg="green")
            
            # 得到依赖树
            dep_tree = self.dependency_manager.get_dependency_tree()
            if dep_tree:
                click.secho(f"📊 依赖树结构:", fg="cyan")
                _print_dependency_tree(dep_tree, 0)
                
                # 按层次合并依赖，从最底层开始
                ordered_deps: List[List[DependencyNode]] = _get_ordered_dependencies(dep_tree)
                for level, deps in enumerate(ordered_deps):
                    if deps:
                        click.secho(f"🔄 合并第 {level+1} 层依赖: {', '.join([dep.name for dep in deps])}", fg="yellow")
                        for dep_node in deps:
                            # 合并依赖文件
                            dep_addon = dep_node.addon_pack
                            click.secho(f" 📦 {dep_node.name} → {dep_addon.path}", fg="green")
                            dep_addon.merge_behavior_into(self.target_addon.behavior_pack_dir)
                            dep_addon.merge_resource_into(self.target_addon.resource_pack_dir)
            else:
                # 如果没有依赖树（异常情况），则按照扁平方式处理
                click.secho(f"⚠️ 警告: 无法构建依赖树，将按扁平方式处理依赖", fg="yellow")
                for dep_name, dep_addon in dependencies.items():
                    click.secho(f"🔄 合并依赖包: {dep_name} → {dep_addon.path}", fg="yellow")
                    dep_addon.merge_behavior_into(self.target_addon.behavior_pack_dir)
                    dep_addon.merge_resource_into(self.target_addon.resource_pack_dir)
        
        
        return True, None
    

class MapProjectBuilder:
    """项目构建器"""
    def __init__(self, source_dir: str, target_dir: str, merge: bool = False):
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.merge = merge
        self.config = read_config(os.path.join(source_dir, CONFIG_FILE))
        self.project_name = self.config.get('project', {}).get('name', 'current_project')
        self.dependency_manager = DependencyManager()
        self.dependency_tree = None
        
    def initialize(self) -> bool:
        """初始化构建环境"""
        # 验证目标目录
        if not self.target_dir:
            click.secho('❌ 错误: 未指定目标目录。', fg="red")
            return False
            
        # 确保目标目录存在
        if not os.path.exists(self.target_dir):
            os.makedirs(self.target_dir)
            click.secho(f'🔧 创建目标目录: {self.target_dir}', fg="yellow")
            
        # 清空目标目录
        _clear_directory(self.target_dir)
        
        # 获取依赖列表
        dependencies_list = self.config.get('project', {}).get('dependencies', [])
        
        # 构建依赖树
        self.dependency_tree = self.dependency_manager.build_dependency_tree(
            self.project_name, 
            self.source_dir, 
            dependencies_list
        )
        
        return True
        
    def build(self) -> Tuple[bool, Optional[str]]:
        """
        执行地图项目构建过程
        
        Returns:
            Tuple[bool, Optional[str]]: (是否成功, 错误信息)
        """
        click.secho(f'📂 正在构建地图项目从 ', fg="bright_blue", nl=False)
        click.secho(f'{self.source_dir}', fg="bright_cyan", nl=False)
        click.secho(' 到 ', fg="bright_blue", nl=False)
        click.secho(f'{self.target_dir}', fg="bright_cyan", nl=False)
        click.secho('...', fg="bright_blue")
        
        click.secho('🔄 正在构建地图与代码...', fg="yellow")
        
        # 初始化构建环境
        if not self.initialize():
            return False, "初始化构建环境失败"
        
        # 创建地图包对象
        source_map = MapPack(self.project_name, self.source_dir)
        target_map = MapPack(self.project_name, self.target_dir)
        self.target_map = target_map
        
        # 复制地图核心数据
        click.secho('📦 复制地图核心数据...', fg="yellow")
        source_map.copy_level_data_to(self.target_dir)

        main_behavior_pack_dir = None
        main_resource_pack_dir = None
        
        # 复制原始行为包和资源包
        click.secho('📦 复制地图行为包和资源包...', fg="yellow")
        source_map.copy_behavior_packs_to(self.target_dir)
        source_map.copy_resource_packs_to(self.target_dir)

        if source_map.behavior_packs:
            main_behavior_pack_dir = os.path.join(self.target_dir, "behavior_packs", os.path.basename(source_map.behavior_packs[0]))
        if source_map.resource_packs:
            main_resource_pack_dir = os.path.join(self.target_dir, "resource_packs", os.path.basename(source_map.resource_packs[0]))
        
        # 处理依赖
        dependencies = self.dependency_manager.get_all_dependencies()
        if dependencies:
            dep_count = len(dependencies)
            click.secho(f"✅ 找到 {dep_count} 个依赖包", fg="green")
            
            # 得到依赖树
            dep_tree = self.dependency_manager.get_dependency_tree()
            if dep_tree:
                click.secho(f"📊 依赖树结构:", fg="cyan")
                _print_dependency_tree(dep_tree, 0)
                
                # 按层次合并依赖，从最底层开始
                ordered_deps: List[List[DependencyNode]] = _get_ordered_dependencies(dep_tree)
                for level, deps in enumerate(ordered_deps):
                    if deps:
                        click.secho(f"🔄 合并第 {level+1} 层依赖: {', '.join([dep.name for dep in deps])}", fg="yellow")
                        for dep_node in deps:
                            # 合并依赖文件到地图的包目录
                            dep_addon = dep_node.addon_pack
                            dep_addon.is_origin = True
                            click.secho(f" 📦 {dep_node.name}: {dep_addon.path}", fg="green")
                            # 合并到地图特定的包目录结构
                            # 避免重名
                            if self.merge and main_behavior_pack_dir:
                                dep_addon.merge_behavior_into(main_behavior_pack_dir)
                            else:
                                rename_behavior = os.path.basename(dep_addon.behavior_pack_dir) + "_" + dep_addon.pkg_name if os.path.basename(dep_addon.behavior_pack_dir) == "behavior_pack" or os.path.basename(dep_addon.behavior_pack_dir) == "BehaviorPack" else None
                                dep_addon.copy_behavior_to(target_map.behavior_packs_dir, rename=rename_behavior)
                                main_behavior_pack_dir = os.path.join(target_map.behavior_packs_dir, rename_behavior if rename_behavior else os.path.basename(dep_addon.behavior_pack_dir))
                            if self.merge and main_resource_pack_dir:
                                dep_addon.merge_resource_into(main_resource_pack_dir)
                            else:
                                rename_resource = os.path.basename(dep_addon.resource_pack_dir) + "_" + dep_addon.pkg_name if os.path.basename(dep_addon.resource_pack_dir) == "resource_pack" or os.path.basename(dep_addon.resource_pack_dir) == "ResourcePack" else None
                                dep_addon.copy_resource_to(target_map.resource_packs_dir, rename=rename_resource)
                                main_resource_pack_dir = os.path.join(target_map.resource_packs_dir, rename_resource if rename_resource else os.path.basename(dep_addon.resource_pack_dir))
            else:
                # 如果没有依赖树（异常情况），则按照扁平方式处理
                click.secho(f"⚠️ 警告: 无法构建依赖树，将按扁平方式处理依赖", fg="yellow")
                for dep_name, dep_addon in dependencies.items():
                    click.secho(f"🔄 合并依赖包: {dep_name}: {dep_addon.path}", fg="yellow")
                    dep_addon.is_origin = True
                    # 避免重名
                    rename_behavior = os.path.basename(dep_addon.behavior_pack_dir) + "_" + dep_addon.pkg_name if os.path.basename(dep_addon.behavior_pack_dir) == "behavior_pack" or os.path.basename(dep_addon.behavior_pack_dir) == "BehaviorPack" else None
                    dep_addon.copy_behavior_to(target_map.behavior_packs_dir, rename=rename_behavior)
                    rename_resource = os.path.basename(dep_addon.resource_pack_dir) + "_" + dep_addon.pkg_name if os.path.basename(dep_addon.resource_pack_dir) == "resource_pack" or os.path.basename(dep_addon.resource_pack_dir) == "ResourcePack" else None
                    dep_addon.copy_resource_to(target_map.resource_packs_dir, rename=rename_resource)
        
        # 设置地图包配置
        click.secho('📝 配置地图包加载设置...', fg="yellow")
        behavior_packs_config, resource_packs_config = target_map.setup_world_packs_config()
        if behavior_packs_config:
            click.secho(f"✅ 配置了 {len(behavior_packs_config)} 个行为包", fg="green")
        if resource_packs_config:
            click.secho(f"✅ 配置了 {len(resource_packs_config)} 个资源包", fg="green")
        
        
        return True, None

# 工具函数

def _clear_directory(directory):
        """清空目录内容但保留目录本身"""
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)

def _print_dependency_tree(node: DependencyNode, level: int):
    """打印依赖树结构（用于调试）"""
    indent = "  " * level
    if level == 0:
        click.secho(f"{indent}└─ {node.name} (主项目)", fg="bright_cyan")
    else:
        click.secho(f"{indent}└─ {node.name}", fg="cyan")
    
    for child in node.children:
        _print_dependency_tree(child, level + 1)
        
def _get_ordered_dependencies(root_node: DependencyNode) -> List[List[DependencyNode]]:
    """
    获取按层次排序的依赖列表，从最底层开始
    
    Args:
        root_node: 依赖树根节点
        
    Returns:
        List[List[DependencyNode]]: 按层次排序的依赖节点列表，索引0是最底层依赖
    """
    # 使用BFS按层次遍历依赖树
    levels = []
    current_level = [root_node]
    
    while current_level:
        next_level = []
        for node in current_level:
            next_level.extend(node.children)
        
        if next_level:  # 只添加非空层
            levels.append(next_level)
        current_level = next_level
    
    # 反转层次，使最底层依赖（没有子依赖的）在前面
    levels.reverse()
    return levels


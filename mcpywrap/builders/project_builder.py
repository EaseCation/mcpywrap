# -*- coding: utf-8 -*-
"""
项目构建模块 - 负责整个项目的构建过程
"""

import os
import shutil
import click
from typing import Dict, List, Tuple, Optional

from ..config import read_config, CONFIG_FILE, get_use_3to2
from .AddonsPack import AddonsPack
from .dependency_manager import DependencyManager, DependencyNode
from ..utils.py3to2_util import py3_to_2
from ..utils.utils import run_command


class ProjectBuilder:
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
        self._clear_directory(self.target_dir)
        
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
        
    def _clear_directory(self, directory):
        """清空目录内容但保留目录本身"""
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)
                
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
                self._print_dependency_tree(dep_tree, 0)
                
                # 按层次合并依赖，从最底层开始
                ordered_deps = self._get_ordered_dependencies(dep_tree)
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
        
        # 转换Python文件(如果需要)
        if get_use_3to2():
            click.secho("🔄 将Python 3代码转换为Python 2...", fg="yellow")
            success, output = self._convert_project_py3_to_py2(self.target_dir)
            if not success:
                return False, output
        
        return True, None
        
    def _print_dependency_tree(self, node: DependencyNode, level: int):
        """打印依赖树结构（用于调试）"""
        indent = "  " * level
        if level == 0:
            click.secho(f"{indent}└─ {node.name} (主项目)", fg="bright_cyan")
        else:
            click.secho(f"{indent}└─ {node.name}", fg="cyan")
        
        for child in node.children:
            self._print_dependency_tree(child, level + 1)
            
    def _get_ordered_dependencies(self, root_node: DependencyNode) -> List[List[DependencyNode]]:
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
    
    def _convert_project_py3_to_py2(self, directory):
        """将整个项目中的Python文件转换为Python 2"""
        try:
            # 首先尝试使用直接的Python API调用
            from lib3to2.main import main
            # main函数接受包名和参数列表
            # 第一个参数是包名 'lib3to2' (这是3to2所有修复器的位置)
            # 第二个参数是命令行参数列表
            exit_code = main('lib3to2.fixes', ['-w', '-n', '-j', '4', '--no-diffs', directory, '--nofix=metaclass'])
            
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

# -*- coding: utf-8 -*-
"""
文件监控模块 - 负责监控文件变化并触发处理
"""

import os
import time
import pdb
from typing import Callable, Dict, List, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from ..utils.utils import ensure_dir

from .dependency_manager import DependencyManager, DependencyNode
from .AddonsPack import AddonsPack

class FileChangeHandler(FileSystemEventHandler):
    """文件变化处理器"""
    def __init__(self, source_dir, target_dir, callback=None, is_dependency=False, dependency_name=None, project_watcher=None, addon_pack=None):
        self.source_dir = source_dir
        self.target_dir = target_dir
        print(f"监控目录: {self.source_dir} -> {self.target_dir}")
        self.last_event_time = 0
        self.cooldown = 0  # 冷却时间（秒）
        self.callback = callback
        self.is_dependency = is_dependency  # 是否是依赖项目
        self.dependency_name = dependency_name  # 依赖项目名称
        self.project_watcher: ProjectWatcher = project_watcher  # ProjectWatcher 对象
        self.addon_pack: AddonsPack = addon_pack  # AddonsPack 对象
        # 存储最近处理的事件，用于防止重复处理
        self.recent_events = {}
        
        if not self.addon_pack:
            raise ValueError("必须提供 AddonsPack 对象，不再支持旧的文件处理方式")

    def _should_ignore_path(self, path):
        """判断是否应该忽略该路径"""
        basename = os.path.basename(path)
        
        # 检查路径是否在目标目录中
        if os.path.normpath(self.target_dir) in os.path.normpath(path):
            return True
            
        return (basename.startswith('.') or
                path.endswith('~') or
                basename.startswith('.#') or
                basename.endswith('.swp') or  # vim临时文件
                basename.endswith('.tmp'))    # 其他临时文件

    def _process_event(self, event, event_type):
        """处理事件的通用方法"""
        if not hasattr(event, 'src_path'):
            return

        src_path = event.src_path
        
        # 忽略目录事件（如果不需要直接处理目录事件）和需要忽略的文件
        if event.is_directory or self._should_ignore_path(src_path):
            return

        # 对于删除事件，不检查文件是否存在
        if event_type != 'deleted' and not os.path.exists(src_path):
            return

        # 使用事件类型和路径作为键来防止短时间内重复处理相同事件
        event_key = f"{event_type}:{src_path}"
        current_time = time.time()
        
        # 检查冷却时间
        if event_key in self.recent_events and current_time - self.recent_events[event_key] < self.cooldown:
            return
        
        self.recent_events[event_key] = current_time

        # 使用 AddonsPack 判断文件类型
        is_in_pack, pack_type, src_rel_path = self.addon_pack.get_relative_path_in_pack(src_path)
        
        if not is_in_pack:
            # 文件不在行为包或资源包中
            return
            
        # 初始化变量
        success = False
        output = ""
        dest_path = None
        
        # 查找目标目录中对应的包目录
        if pack_type == "behavior":
            dest_path = os.path.join(self.target_dir, os.path.basename(self.project_watcher.target_addon_pack.behavior_pack_dir), src_rel_path)
        elif pack_type == "resource":
            dest_path = os.path.join(self.target_dir, os.path.basename(self.project_watcher.target_addon_pack.resource_pack_dir), src_rel_path)
        
        if not dest_path:
            success = False
            output = f"错误: 无法计算{src_path}的目标路径"
            return
        
        # 处理删除事件
        if os.path.exists(dest_path):
            os.remove(dest_path)
        
        # 处理创建/修改事件
        try:
            # 确保目标目录存在
            ensure_dir(os.path.dirname(dest_path))
            if pack_type == "behavior":
                self.project_watcher.main_addon_pack.merge_behavior_single_file_to(src_rel_path, dest_path)
                for dep in self.project_watcher.dependency_manager.dependency_map.values():
                    dep.merge_behavior_single_file_to(src_rel_path, dest_path)
            elif pack_type == "resource":
                self.project_watcher.main_addon_pack.merge_resource_single_file_to(src_rel_path, dest_path)
                for dep in self.project_watcher.dependency_manager.dependency_map.values():
                    dep.merge_resource_single_file_to(src_rel_path, dest_path)
            # 处理完成
            success = True
            pack_name = "行为包" if pack_type == "behavior" else "资源包"
            output = f"{pack_name}文件已合并: {src_path}"
        except Exception as e:
            success = False
            output = f"合并文件失败: {str(e)}"

        # 如果有回调函数，调用它
        if self.callback:
            is_py = src_path.endswith('.py')
            self.callback(src_path, dest_path, success, output, is_py, 
                         self.is_dependency, self.dependency_name, event_type=event_type)

    def on_created(self, event):
        """处理创建事件"""
        self._process_event(event, 'created')
        
    def on_deleted(self, event):
        """处理删除事件"""
        self._process_event(event, 'deleted')
        
    def on_modified(self, event):
        """处理修改事件"""
        self._process_event(event, 'modified')
        
    def on_moved(self, event):
        """处理移动事件"""
        # 处理移动事件为删除+创建
        if hasattr(event, 'dest_path'):
            # 先处理源文件删除
            self._process_event(event, 'deleted')
            
            # 构造一个创建事件对象来处理目标文件
            class TempEvent:
                def __init__(self, src_path, is_directory):
                    self.src_path = src_path
                    self.is_directory = is_directory
                    
            create_event = TempEvent(event.dest_path, event.is_directory)
            self._process_event(create_event, 'created')

class FileWatcher:
    """文件监控器"""
    def __init__(self, source_dir, target_dir, callback=None, is_dependency=False, dependency_name=None, project_watcher=None, addon_pack=None):
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.observer = None
        self.callback = callback
        self.is_dependency = is_dependency
        self.dependency_name = dependency_name
        self.project_watcher: ProjectWatcher = project_watcher
        self.addon_pack: AddonsPack = addon_pack
        
    def start(self):
        """开始监控"""
        event_handler = FileChangeHandler(
            self.source_dir, 
            self.target_dir,
            self.callback,
            self.is_dependency,
            self.dependency_name,
            self.project_watcher,
            self.addon_pack
        )
        self.observer = Observer()
        self.observer.schedule(event_handler, path=self.source_dir, recursive=True)
        self.observer.start()
        
    def stop(self):
        """停止监控"""
        if self.observer:
            self.observer.stop()
            self.observer.join()

class MultiWatcher:
    """多项目文件监控器，用于同时监控主项目和依赖项目"""
    def __init__(self):
        self.watchers: List[FileWatcher] = []
        
    def add_watcher(self, watcher: FileWatcher):
        """添加一个监视器"""
        self.watchers.append(watcher)
        
    def start_all(self):
        """启动所有监视器"""
        for watcher in self.watchers:
            watcher.start()
            
    def stop_all(self):
        """停止所有监视器"""
        for watcher in self.watchers:
            watcher.stop()
            
class ProjectWatcher:
    """项目监视器，封装了对项目及其依赖的监视"""
    def __init__(self, source_dir: str, target_dir: str, callback: Callable = None):
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.callback = callback
        self.multi_watcher = MultiWatcher()
        self.dependency_manager = DependencyManager()
        self.main_addon_pack: AddonsPack = None
        self.target_addon_pack: AddonsPack = None
        
    def setup_from_config(self, project_name: str, dependencies: List[str]):
        """根据配置设置监视器"""
        try:
            # 创建目标目录结构
            os.makedirs(self.target_dir, exist_ok=True)
            
            # 为主项目创建AddonsPack并添加监视器
            self.main_addon_pack = AddonsPack(project_name, self.source_dir, is_origin=True)
            
            # 创建目标目录中的行为包和资源包目录
            if self.main_addon_pack.behavior_pack_dir:
                behavior_dir_name = os.path.basename(self.main_addon_pack.behavior_pack_dir)
                os.makedirs(os.path.join(self.target_dir, behavior_dir_name), exist_ok=True)
            
            if self.main_addon_pack.resource_pack_dir:
                resource_dir_name = os.path.basename(self.main_addon_pack.resource_pack_dir)
                os.makedirs(os.path.join(self.target_dir, resource_dir_name), exist_ok=True)

            self.target_addon_pack = AddonsPack(project_name, self.target_dir, is_origin=False)
            
            # 添加主项目监视器
            main_watcher = FileWatcher(
                self.source_dir, 
                self.target_dir, 
                self.callback,
                project_watcher=self,
                addon_pack=self.main_addon_pack
            )
            self.multi_watcher.add_watcher(main_watcher)
            
            # 构建依赖树
            self.dependency_manager.build_dependency_tree(
                project_name,
                self.source_dir,
                dependencies
            )
            
            # 为依赖添加监视器
            dependencies_map = self.dependency_manager.get_all_dependencies()
            for dep_name, dep_addon in dependencies_map.items():
                dep_watcher = FileWatcher(
                    dep_addon.path,
                    self.target_dir,
                    self.callback,
                    is_dependency=True,
                    dependency_name=dep_name,
                    project_watcher=self,
                    addon_pack=dep_addon
                )
                self.multi_watcher.add_watcher(dep_watcher)
            
            return len(dependencies_map)
        except Exception as e:
            import click
            click.secho(f"❌ 设置监视器时出错: {str(e)}", fg="red")
            return 0
        
    def start(self):
        """开始监视"""
        try:
            # 开始文件监视
            self.multi_watcher.start_all()
        except Exception as e:
            import click
            click.secho(f"❌ 启动监视器时出错: {str(e)}", fg="red")
        
    def stop(self):
        """停止监视"""
        self.multi_watcher.stop_all()
        
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

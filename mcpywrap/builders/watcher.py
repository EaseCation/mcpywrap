# -*- coding: utf-8 -*-
"""
文件监控模块 - 负责监控文件变化并触发处理
"""

import os
import time
from typing import Callable, Dict, List, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .file_handler import process_file, is_python_file
from .dependency_manager import DependencyManager, DependencyNode

class FileChangeHandler(FileSystemEventHandler):
    """文件变化处理器"""
    def __init__(self, source_dir, target_dir, callback=None, is_dependency=False, dependency_name=None):
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.last_event_time = 0
        self.cooldown = 2  # 冷却时间（秒）
        self.callback = callback
        self.is_dependency = is_dependency  # 是否是依赖项目
        self.dependency_name = dependency_name  # 依赖项目名称
        # 存储最近处理的事件，用于防止重复处理
        self.recent_events = {}

    def _should_ignore_path(self, path):
        """判断是否应该忽略该路径"""
        basename = os.path.basename(path)
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

        # 根据事件类型进行处理
        if event_type == 'deleted':
            # 对于删除的文件，生成目标路径并通知回调
            rel_path = os.path.relpath(src_path, self.source_dir)
            dest_path = os.path.join(self.target_dir, rel_path)
            
            if self.callback:
                is_py = is_python_file(src_path)
                self.callback(src_path, dest_path, False, f"文件已删除: {src_path}", is_py, 
                             self.is_dependency, self.dependency_name, event_type='deleted')
        else:
            # 对于其他事件（创建、修改），使用process_file处理
            success, output, dest_path = process_file(
                src_path,
                self.source_dir,
                self.target_dir,
                is_dependency=self.is_dependency,
                dependency_name=self.dependency_name
            )

            # 如果有回调函数，调用它
            if self.callback and dest_path:
                is_py = is_python_file(src_path)
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
    def __init__(self, source_dir, target_dir, callback=None, is_dependency=False, dependency_name=None):
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.observer = None
        self.callback = callback
        self.is_dependency = is_dependency
        self.dependency_name = dependency_name
        
    def start(self):
        """开始监控"""
        event_handler = FileChangeHandler(
            self.source_dir, 
            self.target_dir,
            self.callback,
            self.is_dependency,
            self.dependency_name
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
        
    def setup_from_config(self, project_name: str, dependencies: List[str]):
        """根据配置设置监视器"""
        # 为主项目添加监视器
        main_watcher = FileWatcher(self.source_dir, self.target_dir, self.callback)
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
                dependency_name=dep_name
            )
            self.multi_watcher.add_watcher(dep_watcher)
        
        return len(dependencies_map)
        
    def start(self):
        """开始监视"""
        self.multi_watcher.start_all()
        
    def stop(self):
        """停止监视"""
        self.multi_watcher.stop_all()

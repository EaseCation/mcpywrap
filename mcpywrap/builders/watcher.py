# -*- coding: utf-8 -*-
"""
文件监控模块 - 负责监控文件变化并触发处理
"""

import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from .file_handler import process_file, is_python_file

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

    def on_any_event(self, event):
        # 检查路径是否有效
        if not hasattr(event, 'src_path'):
            return

        src_path = event.src_path

        # 忽略目录事件、隐藏文件和临时文件
        if (event.is_directory or
                os.path.basename(src_path).startswith('.') or
                src_path.endswith('~') or
                os.path.basename(src_path).startswith('.#') or
                os.path.basename(src_path).endswith('.swp') or  # vim临时文件
                os.path.basename(src_path).endswith('.tmp')):  # 其他临时文件
            return

        # 检查文件是否存在
        if not os.path.exists(src_path):
            return

        current_time = time.time()
        if current_time - self.last_event_time > self.cooldown:
            self.last_event_time = current_time

            # 处理文件变化
            success, output, dest_path = process_file(
                src_path,
                self.source_dir,
                self.target_dir,
                is_dependency=self.is_dependency,
                dependency_name=self.dependency_name
            )

            # 如果有回调函数，调用它
            if self.callback and dest_path:  # 确保dest_path存在
                is_py = is_python_file(src_path)
                self.callback(src_path, dest_path, success, output, is_py, self.is_dependency, self.dependency_name)

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
        self.watchers = []
        
    def add_watcher(self, watcher):
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

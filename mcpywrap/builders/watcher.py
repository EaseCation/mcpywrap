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
    def __init__(self, source_dir, target_dir, callback=None):
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.last_event_time = 0
        self.cooldown = 2  # 冷却时间（秒）
        self.callback = callback
        
    def on_any_event(self, event):
        # 忽略目录事件和隐藏文件
        if event.is_directory or os.path.basename(event.src_path).startswith('.'):
            return
            
        current_time = time.time()
        if current_time - self.last_event_time > self.cooldown:
            self.last_event_time = current_time
            
            # 处理文件变化
            if hasattr(event, 'src_path') and os.path.exists(event.src_path):
                success, output, dest_path = process_file(
                    event.src_path, 
                    self.source_dir, 
                    self.target_dir
                )
                
                # 如果有回调函数，调用它
                if self.callback:
                    is_py = is_python_file(event.src_path)
                    self.callback(event.src_path, dest_path, success, output, is_py)

class FileWatcher:
    """文件监控器"""
    def __init__(self, source_dir, target_dir, callback=None):
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.observer = None
        self.callback = callback
        
    def start(self):
        """开始监控"""
        event_handler = FileChangeHandler(
            self.source_dir, 
            self.target_dir,
            self.callback
        )
        self.observer = Observer()
        self.observer.schedule(event_handler, path=self.source_dir, recursive=True)
        self.observer.start()
        
    def stop(self):
        """停止监控"""
        if self.observer:
            self.observer.stop()
            self.observer.join()

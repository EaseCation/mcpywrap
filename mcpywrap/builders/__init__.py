# -*- coding: utf-8 -*-
"""
构建模块包，提供项目构建、文件处理和监控功能
"""

from .project_builder import ProjectBuilder
from .file_handler import process_file, is_python_file
from .watcher import ProjectWatcher, FileWatcher
from .dependency_manager import DependencyManager

__all__ = ['ProjectBuilder', 'process_file', 'is_python_file', 
           'ProjectWatcher', 'FileWatcher', 'DependencyManager']

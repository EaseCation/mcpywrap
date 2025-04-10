# -*- coding: utf-8 -*-
"""
构建模块包，提供项目构建、文件处理和监控功能
"""

from .project_builder import AddonProjectBuilder
from .watcher import ProjectWatcher, FileWatcher
from .dependency_manager import DependencyManager

__all__ = ['AddonProjectBuilder', 'ProjectWatcher', 'FileWatcher', 'DependencyManager']

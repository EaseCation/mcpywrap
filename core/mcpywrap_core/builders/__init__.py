# -*- coding: utf-8 -*-
"""
构建模块包，提供项目构建、文件处理和监控功能
"""

from .project_builder import AddonProjectBuilder
from .dependency_manager import DependencyManager

__all__ = ['AddonProjectBuilder', 'ProjectWatcher', 'FileWatcher', 'DependencyManager']


def __getattr__(name):
    # Offline assembly does not need a filesystem observer. Keep the public
    # watcher exports, loading their platform dependency only when requested.
    if name in ('ProjectWatcher', 'FileWatcher'):
        from . import watcher
        value = getattr(watcher, name)
        globals()[name] = value
        return value
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')

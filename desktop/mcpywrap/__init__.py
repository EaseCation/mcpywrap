"""Compatibility imports for the complete distribution; implementation lives in core.

Alias modules retain their canonical identity, so old imports and patches do not
create a second dependency graph, class hierarchy or global runtime state.
"""
import importlib
import importlib.abc
import importlib.util
import sys

from mcpywrap_core import __version__


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, target, spec):
        self.target, self.spec = target, spec

    def create_module(self, spec):
        module = importlib.import_module(self.target)
        self.original_spec, self.original_loader = module.__spec__, module.__loader__
        return module

    def exec_module(self, module):
        module.__spec__, module.__loader__ = self.original_spec, self.original_loader

    def get_code(self, fullname):
        return self.spec.loader.get_code(self.target)


class _AliasFinder(importlib.abc.MetaPathFinder):
    _mcpy_compat = True

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith('mcpywrap.'):
            return None
        canonical = 'mcpywrap_core' + fullname[len('mcpywrap'):]
        spec = importlib.util.find_spec(canonical)
        if spec is None:
            return None
        alias = importlib.util.spec_from_loader(fullname, _AliasLoader(canonical, spec), origin=spec.origin,
                                               is_package=spec.submodule_search_locations is not None)
        alias.has_location = spec.has_location
        return alias


if not any(getattr(finder, '_mcpy_compat', False) for finder in sys.meta_path):
    sys.meta_path.insert(0, _AliasFinder())

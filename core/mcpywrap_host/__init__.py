"""Stable host bootstrap. Import this BEFORE mcpywrap in a fresh core process.

One engine package (mcpywrap), one API. This module only verifies, selects and
loads versions; it contains no project or build implementation. Embedded hosts
pin this bootstrap and must not replace it during a Python-core-only update.
"""
from .store import CoreStore, UpdateError

__all__ = ['CoreStore', 'UpdateError']

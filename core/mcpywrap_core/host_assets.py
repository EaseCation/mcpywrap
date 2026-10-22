"""Locate host binaries without putting them in the independently updatable core."""
from importlib.util import find_spec
from pathlib import Path


def asset_directory(name):
    if name not in ('bridge_payload', 'window_capture', 'window_activation'):
        raise ValueError('Unknown host resource group')
    spec = find_spec('mcpywrap_assets')
    if spec and spec.submodule_search_locations:
        return Path(next(iter(spec.submodule_search_locations))) / name
    # Preserve an inspectable missing path for the existing diagnostics. Never
    # download or fabricate native resources while importing the core library.
    return Path(__file__).parent / '_unavailable_host_assets' / name

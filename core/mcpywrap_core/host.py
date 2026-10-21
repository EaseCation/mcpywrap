"""Host capabilities for the single engineering implementation.

No platform-name routing: a desktop process and an embedded interpreter supply
the same contract. Missing capabilities fail explicitly instead of falling back.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Callable, Optional, Protocol


HOST_API = 1


class CapabilityUnavailable(ValueError):
    code = 'host_capability_unavailable'

    def __init__(self, capability, hint=None):
        super().__init__('当前宿主未提供能力：' + capability)
        self.hint = hint or '请由宿主提供此能力；不会切换到其他 Python 核心执行。'
        self.details = {'capability': capability}


class EnvironmentProvider(Protocol):
    """Project tool environments, not the interpreter running the mcpy core.

    Records use the existing environment schema (state/python/version/
    requirements/override). identity must return a stable JSON value which
    changes whenever the interpreter or installed environment changes.
    """
    def inspect(self, project, requirements, override): ...
    def ensure(self, project, requirements, override): ...
    def identity(self, environment): ...


@dataclass(frozen=True)
class HostServices:
    api_version: int = HOST_API
    lock_directory: Optional[Path] = None
    cache_directory: Optional[Path] = None
    python_executable: Optional[str] = sys.executable
    allow_processes: bool = True
    command_runner: Optional[Callable] = None
    script_runner: Optional[Callable] = None
    environment_provider: Optional[EnvironmentProvider] = None
    event_sink: Optional[Callable] = None

    def capabilities(self):
        from importlib.util import find_spec
        scripts = bool(self.script_runner or (self.allow_processes and self.python_executable and find_spec('psutil')))
        return {'process_execution': self.allow_processes,
                'tool_python_process': bool(self.allow_processes and self.python_executable),
                'project_scripts': scripts,
                'project_environments': bool(self.environment_provider or (scripts and self.allow_processes)),
                'private_lock_storage': self.lock_directory is not None}


_current = ContextVar('mcpy_host_services', default=None)


def current_host():
    return _current.get() or HostServices()


@contextmanager
def host_scope(host):
    if host.api_version != HOST_API:
        raise ValueError('不兼容的宿主 API：' + str(host.api_version))
    from .utils.locks import lock_storage
    from contextlib import nullcontext
    token = _current.set(host)
    try:
        with lock_storage(host.lock_directory) if host.lock_directory is not None else nullcontext():
            yield host
    finally:
        _current.reset(token)


def tool_python():
    host = current_host()
    if not host.python_executable or not host.allow_processes:
        raise CapabilityUnavailable('tool_python_process')
    return host.python_executable


def run_command(*args, **kwargs):
    host = current_host()
    if not host.allow_processes:
        raise CapabilityUnavailable('process_execution')
    return (host.command_runner or subprocess.run)(*args, **kwargs)

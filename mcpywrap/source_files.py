"""源码依赖共用的路径、内容摘要与Git进程基础设施。"""
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from .dependencies import DependencyError


def long_path(path):
    """内部缓存使用Windows扩展路径，不依赖机器的LongPathsEnabled设置。"""
    path = Path(path).absolute()
    value = str(path)
    if os.name == 'nt' and not value.startswith('\\\\?\\'):
        value = '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
    return Path(value)


def _relative(value, label):
    if not isinstance(value, str) or not value or '\\' in value:
        raise DependencyError(f'{label} 必须为非空 POSIX 相对路径')
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ('', '.', '..') or ':' in p or p.endswith((' ', '.')) or
                                re.search(r'[\x00-\x1f<>"|?*]', p) or
                                re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?', p, re.I)
                                for p in value.split('/')):
        raise DependencyError(f'{label} 不得越界: {value}')
    return path.as_posix()



def digest(directory):
    h = hashlib.sha256()
    for path in sorted(Path(directory).rglob('*'), key=lambda p: p.relative_to(directory).as_posix()):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise DependencyError(f'代码库不允许链接: {path}')
        if path.is_file():
            rel = path.relative_to(directory).as_posix().encode('utf-8')
            data = path.read_bytes()
            h.update(len(rel).to_bytes(8, 'big') + rel + len(data).to_bytes(8, 'big') + data)
    return h.hexdigest()


def windows_checkout_digest(directory, crlf=True):
    """只重算旧 Windows 排序/可选 CRLF 摘要，不改写任何源码。"""
    root = Path(directory)
    h = hashlib.sha256()
    for path in sorted(root.rglob('*'), key=lambda p: tuple(part.lower() for part in p.relative_to(root).parts)):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise DependencyError(f'代码库不允许链接: {path}')
        if path.is_file():
            rel = path.relative_to(root).as_posix().encode('utf-8')
            data = path.read_bytes()
            if crlf and b'\0' not in data:
                data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            h.update(len(rel).to_bytes(8, 'big') + rel + len(data).to_bytes(8, 'big') + data)
    return h.hexdigest()


def _git(*args):
    def argument(value):
        value = str(value)
        # Git for Windows的命令参数使用普通路径，由core.longpaths处理底层访问。
        if os.name == 'nt' and value.startswith('\\\\?\\UNC\\'):
            return '\\\\' + value[8:]
        if os.name == 'nt' and value.startswith('\\\\?\\'):
            return value[4:]
        return value
    try:
        result = subprocess.run(['git', '-c', 'core.hooksPath=', '-c', 'core.longpaths=true', *map(argument, args)],
                                capture_output=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DependencyError(f'无法获取代码库: {exc}') from exc
    if result.returncode:
        raise DependencyError(result.stderr.decode('utf-8', errors='replace').strip())
    return result.stdout

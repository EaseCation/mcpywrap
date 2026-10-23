"""进程交接只报告真实身份；窗口标题是提示，不是观测结果。"""
import os
import subprocess

import psutil


class ProcessReused(ValueError):
    """The recorded process ended and its PID now belongs to a newer process."""


from .._process_identity import identity


def checked_process(record):
    try:
        process = psutil.Process(record['pid'])
        if 'start_ticks' in record:
            from .._process_identity import proc_stat
            same = proc_stat(record['pid'])['start_ticks'] == record['start_ticks']
        else:
            same = abs(process.create_time() - record['created_at']) <= 0.01
        if not same:
            raise ProcessReused('进程身份不匹配；拒绝操作可能复用的 PID')
        if (os.path.normcase(os.path.realpath(process.exe())) !=
                os.path.normcase(os.path.realpath(record['executable']))):
            raise ValueError('进程身份不匹配；拒绝操作可能复用的 PID')
        return (process if process.status() != psutil.STATUS_ZOMBIE else None) if 'start_ticks' in record else (process if process.is_running() else None)
    except (psutil.NoSuchProcess, FileNotFoundError, ProcessLookupError):
        return None
    except psutil.AccessDenied as exc:
        raise ValueError('无法核对进程身份，拒绝操作') from exc


def observed_process(record):
    """Reused PIDs prove the old process ended; access errors remain unknown."""
    try:
        return checked_process(record)
    except ProcessReused:
        return None


def background_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}

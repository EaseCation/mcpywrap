"""进程交接只报告真实身份；窗口标题是提示，不是观测结果。"""
import os
import subprocess

import psutil


def identity(pid):
    process = psutil.Process(pid)
    return {'pid': pid, 'created_at': process.create_time(), 'executable': process.exe()}


def checked_process(record):
    try:
        process = psutil.Process(record['pid'])
        if (abs(process.create_time() - record['created_at']) > 0.01 or
                os.path.normcase(os.path.realpath(process.exe())) !=
                os.path.normcase(os.path.realpath(record['executable']))):
            raise ValueError('进程身份不匹配；拒绝操作可能复用的 PID')
        return process if process.is_running() else None
    except psutil.NoSuchProcess:
        return None
    except psutil.AccessDenied as exc:
        raise ValueError('无法核对进程身份，拒绝操作') from exc


def background_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}

"""Private finite-script supervisor. Invoked by absolute path; never a public CLI."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import psutil


def identity(pid):
    p = psutil.Process(pid)
    return {'pid': pid, 'created_at': p.create_time(), 'executable': p.exe()}


def alive(record):
    try:
        p = psutil.Process(record['pid'])
        return abs(p.create_time() - record['created_at']) < .01 and p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def save(path, data):
    temporary = path.with_suffix('.writing')
    temporary.write_text(json.dumps(data, ensure_ascii=True), encoding='utf-8')
    for attempt in range(10):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if os.name != 'nt' or attempt == 9: raise
            time.sleep(.02)


class WindowsJob:
    """Closing the supervisor's handle terminates its assigned command tree."""
    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w
        class Basic(c.Structure):
            _fields_ = [('PerProcessUserTimeLimit', c.c_longlong), ('PerJobUserTimeLimit', c.c_longlong),
                        ('LimitFlags', w.DWORD), ('MinimumWorkingSetSize', c.c_size_t),
                        ('MaximumWorkingSetSize', c.c_size_t), ('ActiveProcessLimit', w.DWORD),
                        ('Affinity', c.c_size_t), ('PriorityClass', w.DWORD), ('SchedulingClass', w.DWORD)]
        class IO(c.Structure):
            _fields_ = [(name, c.c_ulonglong) for name in ('ReadOperationCount', 'WriteOperationCount',
                       'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]
        class Extended(c.Structure):
            _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', IO),
                        ('ProcessMemoryLimit', c.c_size_t), ('JobMemoryLimit', c.c_size_t),
                        ('PeakProcessMemoryUsed', c.c_size_t), ('PeakJobMemoryUsed', c.c_size_t)]
        class Accounting(c.Structure):
            _fields_ = [(name, c.c_longlong) for name in ('TotalUserTime', 'TotalKernelTime',
                        'ThisPeriodTotalUserTime', 'ThisPeriodTotalKernelTime')] + [
                        (name, w.DWORD) for name in ('TotalPageFaultCount', 'TotalProcesses',
                        'ActiveProcesses', 'TotalTerminatedProcesses')]
        self.accounting_type = Accounting
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = w.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.kernel.QueryInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p]
        self.kernel.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.kernel.OpenThread.restype = w.HANDLE
        self.kernel.ResumeThread.argtypes = [w.HANDLE]
        self.kernel.ResumeThread.restype = w.DWORD
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle: raise c.WinError(c.get_last_error())
        info = Extended(); info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, c.byref(info), c.sizeof(info)):
            error = c.WinError(c.get_last_error()); self.close(); raise error

    def assign(self, process):
        import ctypes as c
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise c.WinError(c.get_last_error())
        # The command was created suspended: no child can escape before job assignment.
        threads = psutil.Process(process.pid).threads()
        if not threads:
            raise RuntimeError('脚本主线程不存在')
        thread = self.kernel.OpenThread(0x0002, False, threads[0].id)
        if not thread:
            raise c.WinError(c.get_last_error())
        try:
            if self.kernel.ResumeThread(thread) == 0xffffffff:
                raise c.WinError(c.get_last_error())
        finally:
            self.kernel.CloseHandle(thread)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def active_count(self):
        import ctypes as c
        info = self.accounting_type()
        # JobObjectBasicAccountingInformation survives the original parent's
        # exit and includes descendants missed between process-tree samples.
        if not self.kernel.QueryInformationJobObject(self.handle, 1, c.byref(info), c.sizeof(info), None):
            raise c.WinError(c.get_last_error())
        return info.ActiveProcesses

    def terminate(self):
        import ctypes as c
        if not self.kernel.TerminateJobObject(self.handle, 1):
            raise c.WinError(c.get_last_error())


def members(process, known):
    try:
        for p in psutil.Process(process.pid).children(recursive=True):
            known[p.pid] = identity(p.pid)
    except psutil.NoSuchProcess:
        pass
    if os.name != 'nt':
        for p in psutil.process_iter(['pid', 'status']):
            try:
                if p.info['status'] != psutil.STATUS_ZOMBIE and os.getpgid(p.pid) == process.pid:
                    known[p.pid] = identity(p.pid)
            except (ProcessLookupError, PermissionError, psutil.NoSuchProcess):
                pass
    return [r for r in known.values() if alive(r)]


def finish_tree(process, known, job):
    if job:
        # Keep the job handle until exit is verified, including descendants
        # never observed by psutil. Closing it alone only requests termination.
        job.terminate()
        if process.poll() is None:
            process.kill()  # Also handles failure to assign a suspended child.
        process.wait(timeout=3)
        deadline = time.monotonic() + 2
        while job.active_count():
            if time.monotonic() >= deadline:
                raise RuntimeError('脚本后代进程尚未确认退出')
            time.sleep(.05)
        return
    if os.name != 'nt':
        try: os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError: pass
    pending = members(process, known)
    for record in pending:
        try: psutil.Process(record['pid']).terminate()
        except psutil.NoSuchProcess: pass
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and any(alive(r) for r in pending):
        process.poll()
        time.sleep(.05)
    remaining = members(process, known)
    if not remaining:
        process.wait(timeout=3)
        return
    if os.name != 'nt':
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
    for record in remaining:
        if alive(record):
            try: psutil.Process(record['pid']).kill()
            except psutil.NoSuchProcess: pass
    process.wait(timeout=3)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if not any(alive(r) for r in known.values()): return
        time.sleep(.05)
    raise RuntimeError('脚本后代进程尚未确认退出')


def main():
    spec = json.loads(sys.stdin.buffer.read())
    path = Path(spec.pop('result'))
    command, timeout = spec.pop('command'), spec.pop('timeout')
    cancel, parent = Path(spec.pop('cancel')), spec.pop('parent')
    state = dict(spec, supervisor=identity(os.getpid()), state='starting')
    process, job, known = None, None, {}
    started = time.monotonic()
    try:
        save(path, state)
        if not alive(parent) or cancel.exists():
            state.update(state='cancelled', code='script_cancelled')
            return
        if os.name == 'nt': job = WindowsJob()
        state['state'] = 'spawning'; save(path, state)
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                   **({'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000004}
                                      if os.name == 'nt' else {'start_new_session': True}))
        try:
            child = identity(process.pid)
        except psutil.ZombieProcess:
            child = {'pid': process.pid, 'created_at': psutil.Process(process.pid).create_time(), 'executable': command[0]}
        state.update(child=child, group=process.pid if os.name != 'nt' else None, state='running')
        known[process.pid] = child
        save(path, state)
        if job: job.assign(process)
        while process.poll() is None:
            members(process, known)
            if cancel.exists() or not alive(parent):
                state.update(state='cancelled', code='script_cancelled', error='操作已取消或调用进程已退出')
                break
            if time.monotonic() - started >= timeout:
                state.update(state='timed_out', code='script_timeout', error='执行超时')
                break
            time.sleep(.05)
        else:
            descendants = [r for r in members(process, known) if r['pid'] != process.pid]
            state.update(state='completed' if process.returncode == 0 else 'failed',
                         code=None if process.returncode == 0 else 'script_failed', exit_code=process.returncode)
            if descendants or (job and job.active_count()):
                state.update(state='failed', code='script_background_process', error='有限任务不能遗留后台进程')
    except BaseException as exc:
        state.update(state='failed', code='script_start_failed', error=str(exc))
    finally:
        if process:
            try:
                finish_tree(process, known, job)
            except BaseException as exc:
                import traceback
                traceback.print_exc()
                state.update(state='recovery_required', code='script_recovery_required', error=str(exc))
            state.setdefault('exit_code', process.returncode)
        if job: job.close()
        state['duration'] = time.monotonic() - started
        state['finished_at'] = time.time()
        save(path, state)


if __name__ == '__main__':
    main()

"""Windows 本地客机的进程内 LAN 默认值适配；不修改磁盘引擎。"""
from contextlib import contextmanager
import ctypes as C
from ctypes import wintypes as W
import struct
import time

from .processes import checked_process
from .lan_locator import LocatorError, locate_port


class ProcessImage:
    def __init__(self, identity):
        import pefile
        self.identity = identity
        if not checked_process(identity):
            raise LocatorError('游戏进程已退出。')
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.psapi = C.WinDLL('psapi', use_last_error=True)
        k = self.kernel
        k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        k.OpenProcess.restype = W.HANDLE
        k.CloseHandle.argtypes = [W.HANDLE]
        k.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
        k.WriteProcessMemory.argtypes = k.ReadProcessMemory.argtypes
        k.VirtualProtectEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)]
        k.FlushInstructionCache.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t]
        self.psapi.EnumProcessModulesEx.argtypes = [W.HANDLE, C.POINTER(C.c_void_p), W.DWORD, C.POINTER(W.DWORD), W.DWORD]
        self.handle = k.OpenProcess(0x438 | 0x800, False, identity['pid'])
        if not self.handle:
            raise C.WinError(C.get_last_error())
        try:
            modules = (C.c_void_p * 1024)()
            needed = W.DWORD()
            if not self.psapi.EnumProcessModulesEx(self.handle, modules, C.sizeof(modules), C.byref(needed), 3):
                raise C.WinError(C.get_last_error())
            self.base = modules[0]
            self.limit = 65536
            pe = pefile.PE(data=self.read(0, 65536), fast_load=True)
            if pe.FILE_HEADER.Machine != 0x8664 or not 65536 <= pe.OPTIONAL_HEADER.SizeOfImage <= 1024**3:
                raise LocatorError('自动联机仅支持可识别的 Windows x64 引擎映像。')
            self.limit = pe.OPTIONAL_HEADER.SizeOfImage
            # 加壳入口和可写数据不是引擎代码候选；只取映像主体的可执行节。
            self.sections = [(s.VirtualAddress, s.Misc_VirtualSize, bool(s.Characteristics & 0x20000000))
                             for s in pe.sections if s.Name.rstrip(b'\0') not in (b'.boot', b'.winlice', b'.reloc')]
            directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
            if not directory.Size or directory.Size % 12 or directory.Size > 32*1024**2:
                raise LocatorError('引擎缺少有效的 x64 展开表。')
            self.functions = [(start, end) for start, end, unwind in struct.iter_unpack(
                '<III', self.read(directory.VirtualAddress, directory.Size)) if 0 < start < end < self.limit]
            if not self.functions:
                raise LocatorError('引擎代码尚未解包或展开表不可识别。')
        except BaseException:
            self.close()
            raise

    def read(self, rva, size):
        if rva < 0 or size < 0 or rva+size > self.limit:
            raise LocatorError('引擎映像地址超出边界。')
        buffer = C.create_string_buffer(size)
        count = C.c_size_t()
        if not self.kernel.ReadProcessMemory(self.handle, self.base+rva, buffer, size, C.byref(count)) or count.value != size:
            raise LocatorError('引擎映像尚不可完整读取。')
        return buffer.raw

    @contextmanager
    def suspended(self):
        ntdll = C.WinDLL('ntdll')
        ntdll.NtSuspendProcess.argtypes = [W.HANDLE]
        ntdll.NtResumeProcess.argtypes = [W.HANDLE]
        if not checked_process(self.identity) or ntdll.NtSuspendProcess(self.handle) < 0:
            raise LocatorError('无法暂停本次游戏以原子更新 LAN 配置。')
        try:
            yield
        finally:
            if ntdll.NtResumeProcess(self.handle) < 0:
                raise LocatorError('游戏恢复执行失败，需要停止本次客机。')

    def patch(self, site, port):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('无效的 LAN 端口')
        with self.suspended():
            if self.read(site.instruction_rva, len(site.expected)) != site.expected:
                raise LocatorError('目标指令已变化，未写入。')
            address = self.base+site.operand_rva
            original = self.read(site.operand_rva, 4)
            previous = W.DWORD()
            if not self.kernel.VirtualProtectEx(self.handle, address, 4, 0x40, C.byref(previous)):
                raise C.WinError(C.get_last_error())
            try:
                count = C.c_size_t()
                replacement = struct.pack('<I', port)
                if not self.kernel.WriteProcessMemory(self.handle, address, replacement, 4, C.byref(count)) or count.value != 4:
                    raise LocatorError('LAN 端口写入失败。')
                self.kernel.FlushInstructionCache(self.handle, address, 4)
                if self.read(site.operand_rva, 4) != replacement:
                    raise LocatorError('LAN 端口读回校验失败。')
            except BaseException:
                self.kernel.WriteProcessMemory(self.handle, address, original, 4, C.byref(count))
                self.kernel.FlushInstructionCache(self.handle, address, 4)
                raise
            finally:
                ignored = W.DWORD()
                if not self.kernel.VirtualProtectEx(self.handle, address, 4, previous.value, C.byref(ignored)):
                    raise LocatorError('无法恢复引擎内存页属性。')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def adapt(identity, port, cancelled=lambda: False, timeout=35):
    """等待解包后按结构定位；失败由调用者结束自己刚创建的客机。"""
    if port == 7551:
        return {'strategy': 'engine-default', 'port': port, 'modified': False}
    deadline = time.monotonic()+timeout
    error = None
    while time.monotonic() < deadline:
        if cancelled() or not checked_process(identity):
            raise LocatorError('客机启动已取消或进程退出。')
        image = None
        try:
            image = ProcessImage(identity)
            site = locate_port(image)
        except (LocatorError, OSError) as exc:
            error = exc
        else:
            # 一旦找到唯一候选，写入错误不重试，不允许重复变更未知状态。
            try:
                if cancelled():
                    raise LocatorError('客机启动已取消，未写入。')
                image.patch(site, port)
                return {'strategy': 'nethernet-configuration-v1', 'port': port, 'modified': True,
                        'instruction_rva': site.instruction_rva, 'function_rva': site.function_rva}
            finally:
                image.close()
        finally:
            if image:
                image.close()
        time.sleep(.1)
    raise LocatorError('自动定位 LAN 配置失败：' + str(error))

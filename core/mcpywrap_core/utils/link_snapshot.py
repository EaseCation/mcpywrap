"""Capture directory links themselves, including dangling Windows junctions."""

import base64
import ctypes
import os
from pathlib import Path


def _reparse(path, data=None):
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.DeviceIoControl.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    kernel.DeviceIoControl.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(
        str(Path(path).absolute()),
        0x40000000 if data is not None else 0,
        7,
        None,
        3,
        0x02200000,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        returned = wintypes.DWORD()
        output = ctypes.create_string_buffer(16384)
        source = ctypes.create_string_buffer(data) if data is not None else None
        ok = kernel.DeviceIoControl(
            handle,
            0x900A4 if data is not None else 0x900A8,
            source,
            len(data) if data is not None else 0,
            output,
            0 if data is not None else len(output),
            ctypes.byref(returned),
            None,
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return output.raw[: returned.value]
    finally:
        kernel.CloseHandle(handle)


def capture(path):
    from .paths import is_link

    if not is_link(path):
        raise ValueError("只能保存目录链接")
    if Path(path).is_symlink():
        return {"type": "symlink", "target": os.readlink(path)}
    data = _reparse(path)
    if int.from_bytes(data[:4], "little") != 0xA0000003:
        raise ValueError("仅支持目录 junction")
    return {"type": "junction", "data": base64.b64encode(data).decode("ascii")}


def validate(path, state):
    if state.get("type") == "symlink":
        target = state.get("target")
        if not isinstance(target, str) or not target:
            raise ValueError("符号链接恢复记录无效")
        # readlink() may return a Windows namespace prefix even when the
        # publication used a normal drive/UNC path. Compare the same spelling;
        # retain state['target'] verbatim for restore().
        if os.name == "nt":
            for prefix in ("\\\\?\\", "\\??\\"):
                if target.startswith(prefix):
                    target = target[len(prefix) :]
                    if target[:4].upper() == "UNC\\":
                        target = "\\\\" + target[4:]
                    break
        return str(Path(path).parent / target)
    if state.get("type") != "junction":
        raise ValueError("目录链接恢复类型无效")
    data = base64.b64decode(state["data"], validate=True)
    if (
        len(data) < 16
        or len(data) > 16384
        or int.from_bytes(data[:4], "little") != 0xA0000003
        or int.from_bytes(data[4:6], "little") + 8 != len(data)
    ):
        raise ValueError("junction 恢复记录无效")
    offset = int.from_bytes(data[8:10], "little")
    length = int.from_bytes(data[10:12], "little")
    if length % 2 or offset % 2 or 16 + offset + length > len(data):
        raise ValueError("junction 目标记录无效")
    target = data[16 + offset : 16 + offset + length].decode("utf-16-le")
    if target.startswith("\\??\\UNC\\"):
        target = "\\\\" + target[8:]
    elif target.startswith("\\??\\"):
        target = target[4:]
    return target


def restore(path, state):
    validate(path, state)
    if state["type"] == "symlink":
        os.symlink(state["target"], path, target_is_directory=True)
        return
    data = base64.b64decode(state["data"], validate=True)
    if len(data) < 8 or int.from_bytes(data[:4], "little") != 0xA0000003:
        raise ValueError("junction 恢复记录无效")
    Path(path).mkdir()
    try:
        _reparse(path, data)
    except BaseException:
        Path(path).rmdir()
        raise

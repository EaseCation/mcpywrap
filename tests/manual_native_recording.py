"""Native desktop fixture for opt-in WGC tests; paints known colors and accepts window messages."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    user = C.WinDLL('user32', use_last_error=True)
    user.SetProcessDpiAwarenessContext.argtypes = [W.HANDLE]
    user.SetProcessDpiAwarenessContext(C.c_void_p(-4))
    kernel = C.WinDLL('kernel32', use_last_error=True)
    gdi = C.WinDLL('gdi32', use_last_error=True)
    callback = C.WINFUNCTYPE(C.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
    class WindowClass(C.Structure):
        _fields_ = [('style', W.UINT), ('proc', callback), ('class_extra', C.c_int), ('window_extra', C.c_int),
                    ('instance', W.HINSTANCE), ('icon', W.HANDLE), ('cursor', W.HANDLE),
                    ('background', W.HANDLE), ('menu', W.LPCWSTR), ('name', W.LPCWSTR)]
    signatures = [(kernel, 'GetModuleHandleW', W.HMODULE, [W.LPCWSTR]),
        (user, 'DefWindowProcW', C.c_ssize_t, [W.HWND, W.UINT, W.WPARAM, W.LPARAM]),
        (user, 'CreateWindowExW', W.HWND, [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int, C.c_int,
                                         C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p]),
        (user, 'GetDC', W.HDC, [W.HWND]), (user, 'ReleaseDC', C.c_int, [W.HWND, W.HDC]),
        (gdi, 'CreateSolidBrush', W.HANDLE, [W.DWORD]), (gdi, 'DeleteObject', W.BOOL, [W.HANDLE]),
        (user, 'FillRect', C.c_int, [W.HDC, C.POINTER(W.RECT), W.HANDLE]),
        (user, 'SetTimer', C.c_size_t, [W.HWND, C.c_size_t, W.UINT, C.c_void_p]),
        (user, 'ShowWindow', W.BOOL, [W.HWND, C.c_int]),
        (user, 'GetClientRect', W.BOOL, [W.HWND, C.POINTER(W.RECT)]),
        (user, 'PostQuitMessage', None, [C.c_int]),
        (user, 'RegisterClassW', W.ATOM, [C.POINTER(WindowClass)])]
    for library, name, result, parameters in signatures:
        function = getattr(library, name)
        function.restype, function.argtypes = result, parameters
    state = {'ticks': 0, 'black': False}
    def paint(hwnd):
        dc = user.GetDC(hwnd)
        bounds = W.RECT()
        user.GetClientRect(hwnd, C.byref(bounds))
        for rect, color in ((W.RECT(0, 0, bounds.right, bounds.bottom // 2), 0x0000FF),
                            (W.RECT(0, bounds.bottom // 2, bounds.right, bounds.bottom), 0xFF0000),
                            (W.RECT(0, 0, 16, bounds.bottom), 0x00FF00 if state['ticks'] % 2 else 0x00FFFF)):
            brush = gdi.CreateSolidBrush(0 if state['black'] else color)
            user.FillRect(dc, C.byref(rect), brush)
            gdi.DeleteObject(brush)
        user.ReleaseDC(hwnd, dc)
    def procedure(hwnd, message, wparam, lparam):
        if message == 0x113:
            state['ticks'] += 1
            paint(hwnd)
            return 0
        if message == 0x8001:
            state['black'] = bool(wparam)
            paint(hwnd)
            return 0
        if message == 0x2:
            user.PostQuitMessage(0)
            return 0
        return user.DefWindowProcW(hwnd, message, wparam, lparam)
    proc = callback(procedure)
    instance = kernel.GetModuleHandleW(None)
    window_class = WindowClass(proc=proc, instance=instance, name='McpyRecordingFixture')
    if not user.RegisterClassW(C.byref(window_class)):
        raise C.WinError(C.get_last_error())
    hwnd = user.CreateWindowExW(0, window_class.name, 'mcpywrap native recording acceptance',
                               0x00CF0000, 100, 100, 337, 282, None, None, instance, None)
    if not hwnd:
        raise C.WinError(C.get_last_error())
    user.ShowWindow(hwnd, 5)
    paint(hwnd)
    user.SetTimer(hwnd, 1, 50, None)
    bounds = W.RECT()
    user.GetClientRect(hwnd, C.byref(bounds))
    args.state.write_text(json.dumps({'hwnd': int(hwnd), 'width': bounds.right, 'height': bounds.bottom}), encoding='utf-8')
    message = W.MSG()
    while user.GetMessageW(C.byref(message), None, 0, 0) > 0:
        user.TranslateMessage(C.byref(message))
        user.DispatchMessageW(C.byref(message))


if __name__ == '__main__':
    main()

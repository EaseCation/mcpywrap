"""Windows 游戏会话的键盘输入与客户区截图，仅依赖 Python 标准库。"""
import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import struct
import time
import zlib
from typing import NamedTuple


KEYS = {'ESC': 0x1B, 'ESCAPE': 0x1B, 'ENTER': 0x0D, 'TAB': 9, 'SPACE': 0x20,
        'BACKSPACE': 8, 'UP': 0x26, 'DOWN': 0x28, 'LEFT': 0x25, 'RIGHT': 0x27}
KEYS.update({chr(n): n for n in range(ord('A'), ord('Z') + 1)})
KEYS.update({str(n): ord(str(n)) for n in range(10)})
KEYS.update({f'F{n}': 0x6F + n for n in range(1, 25)})
KEYS.update({f'NUMPAD{n}': 0x60 + n for n in range(10)})
KEYS.update({
    'CLEAR': 0x0C, 'PAUSE': 0x13, 'CAPSLOCK': 0x14, 'KANA': 0x15,
    'IME_ON': 0x16, 'JUNJA': 0x17, 'FINAL': 0x18, 'KANJI': 0x19, 'IME_OFF': 0x1A,
    'CONVERT': 0x1C, 'NONCONVERT': 0x1D, 'ACCEPT': 0x1E, 'MODECHANGE': 0x1F,
    'PAGEUP': 0x21, 'PAGEDOWN': 0x22, 'END': 0x23, 'HOME': 0x24,
    'SELECT': 0x29, 'PRINT': 0x2A, 'EXECUTE': 0x2B, 'PRINTSCREEN': 0x2C,
    'INSERT': 0x2D, 'DELETE': 0x2E, 'HELP': 0x2F,
    'LWIN': 0x5B, 'RWIN': 0x5C, 'APPS': 0x5D, 'SLEEP': 0x5F,
    'MULTIPLY': 0x6A, 'ADD': 0x6B, 'SEPARATOR': 0x6C, 'SUBTRACT': 0x6D,
    'DECIMAL': 0x6E, 'DIVIDE': 0x6F, 'NUMLOCK': 0x90, 'SCROLLLOCK': 0x91,
    'LSHIFT': 0xA0, 'RSHIFT': 0xA1, 'LCTRL': 0xA2, 'RCTRL': 0xA3,
    'LALT': 0xA4, 'RALT': 0xA5,
    'BROWSER_BACK': 0xA6, 'BROWSER_FORWARD': 0xA7, 'BROWSER_REFRESH': 0xA8,
    'BROWSER_STOP': 0xA9, 'BROWSER_SEARCH': 0xAA, 'BROWSER_FAVORITES': 0xAB,
    'BROWSER_HOME': 0xAC, 'VOLUME_MUTE': 0xAD, 'VOLUME_DOWN': 0xAE, 'VOLUME_UP': 0xAF,
    'MEDIA_NEXT': 0xB0, 'MEDIA_PREV': 0xB1, 'MEDIA_STOP': 0xB2, 'MEDIA_PLAY_PAUSE': 0xB3,
    'LAUNCH_MAIL': 0xB4, 'LAUNCH_MEDIA': 0xB5, 'LAUNCH_APP1': 0xB6, 'LAUNCH_APP2': 0xB7,
    'OEM_1': 0xBA, 'OEM_PLUS': 0xBB, 'OEM_COMMA': 0xBC, 'OEM_MINUS': 0xBD,
    'OEM_PERIOD': 0xBE, 'OEM_2': 0xBF, 'OEM_3': 0xC0,
    'OEM_4': 0xDB, 'OEM_5': 0xDC, 'OEM_6': 0xDD, 'OEM_7': 0xDE, 'OEM_8': 0xDF,
    'OEM_102': 0xE2, 'PROCESSKEY': 0xE5, 'ATTN': 0xF6, 'CRSEL': 0xF7,
    'EXSEL': 0xF8, 'EREOF': 0xF9, 'PLAY': 0xFA, 'ZOOM': 0xFB, 'PA1': 0xFD, 'OEM_CLEAR': 0xFE,
})
ALIASES = {
    'SHIFT': 'LSHIFT', 'CTRL': 'LCTRL', 'CONTROL': 'LCTRL', 'ALT': 'LALT',
    'WIN': 'LWIN', 'RETURN': 'ENTER', 'PGUP': 'PAGEUP', 'PGDN': 'PAGEDOWN',
    'INS': 'INSERT', 'DEL': 'DELETE', 'BACK': 'BACKSPACE', 'PRTSC': 'PRINTSCREEN',
    'NUMPAD_ADD': 'ADD', 'NUMPAD_SUBTRACT': 'SUBTRACT', 'NUMPAD_MULTIPLY': 'MULTIPLY',
    'NUMPAD_DIVIDE': 'DIVIDE', 'NUMPAD_DECIMAL': 'DECIMAL',
    'SEMICOLON': 'OEM_1', 'EQUALS': 'OEM_PLUS', 'PLUS': 'OEM_PLUS', 'COMMA': 'OEM_COMMA',
    'MINUS': 'OEM_MINUS', 'PERIOD': 'OEM_PERIOD', 'SLASH': 'OEM_2', 'BACKTICK': 'OEM_3',
    'LBRACKET': 'OEM_4', 'BACKSLASH': 'OEM_5', 'RBRACKET': 'OEM_6', 'QUOTE': 'OEM_7',
}
EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E,
            0x5B, 0x5C, 0x5D, 0x6F, 0x90, 0xA3, 0xA5}
MODIFIERS = {0x10, 0x11, 0x12, 0x5B, 0x5C, *range(0xA0, 0xA6)}


class Key(NamedTuple):
    name: str
    vk: int
    scan: int = 0
    extended: bool = False


def parse_keys(value):
    """键名、组合键及 VK/扫描码兜底；一次调用总会释放全部按键。"""
    tokens = value if isinstance(value, (list, tuple)) else [value]
    parsed = []
    for token in tokens:
        for name in token.upper().split('+'):
            name = ALIASES.get(name.strip(), name.strip())
            if name == 'NUMPAD_ENTER':
                key = Key(name, 0x0D, extended=True)
            elif name in KEYS:
                key = Key(name, KEYS[name], extended=KEYS[name] in EXTENDED)
            elif name.startswith(('VK:', 'SC:', 'E0:')):
                kind, number = name.split(':', 1)
                try:
                    code = int(number, 0)
                except ValueError as exc:
                    raise ValueError(f'无效键码: {name}；十六进制请使用 0x 前缀') from exc
                if kind == 'VK':
                    if not 0x08 <= code <= 0xFE or code == 0xE7:
                        raise ValueError('VK 必须是 0x08–0xFE 的键盘虚拟键；不支持鼠标键或 VK_PACKET')
                    key = Key(name, code, extended=code in EXTENDED)
                else:
                    if not 1 <= code <= 0x7F:
                        raise ValueError('SC/E0 扫描码必须是 0x01–0x7F 的按下码')
                    key = Key(name, 0, code, kind == 'E0')
            else:
                raise ValueError(f'未知按键: {name}；见 key --help，其他键可使用 VK:0xNN 或 SC:0xNN')
            if (key.vk, key.scan, key.extended) in {(k.vk, k.scan, k.extended) for k in parsed}:
                raise ValueError(f'重复按键或别名: {name}')
            parsed.append(key)
    if not parsed:
        raise ValueError('至少指定一个按键')
    # 命名修饰键先按下；扫描码保持用户指定次序，调用方应把修饰键写在前。
    return sorted(parsed, key=lambda k: k.vk not in MODIFIERS)


def session_game(project, session):
    from . import sessions
    data = sessions.read(project, session)
    if data.get('state') != 'running' or not data.get('game'):
        raise ValueError(f"会话未运行: {data.get('state')}")
    if Path(data.get('project', project)).resolve() != Path(project).resolve():
        raise ValueError('会话项目路径不匹配')
    if Path(data['game']['executable']).name.casefold() != 'minecraft.windows.exe':
        raise ValueError('会话目标不是 Minecraft.Windows.exe')
    return data['game']


def desktop_state():
    if os.name != 'nt':
        return {'available': False, 'reason': '游戏桌面仅支持 Windows'}
    user = C.WinDLL('user32', use_last_error=True)
    user.OpenInputDesktop.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    user.OpenInputDesktop.restype = W.HANDLE
    user.CloseDesktop.argtypes = [W.HANDLE]
    user.GetUserObjectInformationW.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
    handle = user.OpenInputDesktop(0, False, 1)
    if not handle:
        return {'available': False, 'reason': '桌面不可访问，请保持登录且未锁屏'}
    try:
        name, needed = C.create_unicode_buffer(256), W.DWORD()
        available = bool(user.GetUserObjectInformationW(handle, 2, name, C.sizeof(name), C.byref(needed)))
        available = available and name.value.casefold() == 'default'
        return {'available': available, 'reason': None if available else '当前不是可操作的用户桌面'}
    finally:
        user.CloseDesktop(handle)


def png_bytes(width, height, bgra):
    """将顶向下的 BGRA DIB 编码为 PNG；不保存桌面或其他窗口。"""
    if width <= 0 or height <= 0 or len(bgra) != width * height * 4:
        raise ValueError('截图像素尺寸无效')
    rgb = bytearray(width * height * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
    rows = b''.join(b'\0' + rgb[n:n + width * 3] for n in range(0, len(rgb), width * 3))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))

    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


class Keyboard(C.Structure):
    _fields_ = [('vk', W.WORD), ('scan', W.WORD), ('flags', W.DWORD),
                ('time', W.DWORD), ('extra', C.c_size_t)]


class Mouse(C.Structure):
    _fields_ = [('dx', W.LONG), ('dy', W.LONG), ('data', W.DWORD),
                ('flags', W.DWORD), ('time', W.DWORD), ('extra', C.c_size_t)]


class InputUnion(C.Union):
    _fields_ = [('keyboard', Keyboard), ('mouse', Mouse)]


class Input(C.Structure):
    _anonymous_ = ('value',)
    _fields_ = [('kind', W.DWORD), ('value', InputUnion)]


class BitmapHeader(C.Structure):
    _fields_ = [('size', W.DWORD), ('width', W.LONG), ('height', W.LONG),
                ('planes', W.WORD), ('bits', W.WORD), ('compression', W.DWORD),
                ('image_size', W.DWORD), ('xppm', W.LONG), ('yppm', W.LONG),
                ('used', W.DWORD), ('important', W.DWORD)]


class GameWindow:
    def __init__(self, game, cancel=None):
        if os.name != 'nt':
            raise ValueError('游戏窗口脚本仅支持 Windows')
        state = desktop_state()
        if not state['available']:
            raise ValueError(state['reason'])
        self.cancel = cancel
        self.game = game
        self.user = C.WinDLL('user32', use_last_error=True)
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.gdi = C.WinDLL('gdi32', use_last_error=True)
        self.dwm = C.WinDLL('dwmapi')
        self.callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        signatures = [
            (self.kernel, 'OpenProcess', W.HANDLE, [W.DWORD, W.BOOL, W.DWORD]),
            (self.kernel, 'CloseHandle', W.BOOL, [W.HANDLE]),
            (self.kernel, 'GetProcessTimes', W.BOOL, [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4),
            (self.kernel, 'QueryFullProcessImageNameW', W.BOOL, [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]),
            (self.kernel, 'GetExitCodeProcess', W.BOOL, [W.HANDLE, C.POINTER(W.DWORD)]),
            (self.user, 'EnumWindows', W.BOOL, [self.callback_type, W.LPARAM]),
            (self.user, 'GetWindowThreadProcessId', W.DWORD, [W.HWND, C.POINTER(W.DWORD)]),
            (self.user, 'IsWindowVisible', W.BOOL, [W.HWND]),
            (self.user, 'IsIconic', W.BOOL, [W.HWND]),
            (self.user, 'ShowWindow', W.BOOL, [W.HWND, C.c_int]),
            (self.user, 'SetForegroundWindow', W.BOOL, [W.HWND]),
            (self.user, 'GetForegroundWindow', W.HWND, []),
            (self.user, 'GetClientRect', W.BOOL, [W.HWND, C.POINTER(W.RECT)]),
            (self.user, 'GetWindowRect', W.BOOL, [W.HWND, C.POINTER(W.RECT)]),
            (self.user, 'ClientToScreen', W.BOOL, [W.HWND, C.POINTER(W.POINT)]),
            (self.user, 'GetWindowTextW', C.c_int, [W.HWND, W.LPWSTR, C.c_int]),
            (self.user, 'GetSystemMetrics', C.c_int, [C.c_int]),
            (self.user, 'GetAsyncKeyState', C.c_short, [C.c_int]),
            (self.user, 'MapVirtualKeyW', W.UINT, [W.UINT, W.UINT]),
            (self.user, 'SendInput', W.UINT, [W.UINT, C.POINTER(Input), C.c_int]),
            (self.user, 'SetThreadDpiAwarenessContext', W.HANDLE, [W.HANDLE]),
            (self.user, 'GetDC', W.HDC, [W.HWND]),
            (self.user, 'ReleaseDC', C.c_int, [W.HWND, W.HDC]),
            (self.gdi, 'CreateCompatibleDC', W.HDC, [W.HDC]),
            (self.gdi, 'CreateCompatibleBitmap', W.HBITMAP, [W.HDC, C.c_int, C.c_int]),
            (self.gdi, 'SelectObject', W.HANDLE, [W.HDC, W.HANDLE]),
            (self.gdi, 'BitBlt', W.BOOL, [W.HDC, C.c_int, C.c_int, C.c_int, C.c_int, W.HDC, C.c_int, C.c_int, W.DWORD]),
            (self.gdi, 'GetDIBits', C.c_int, [W.HDC, W.HBITMAP, W.UINT, W.UINT, C.c_void_p, C.c_void_p, W.UINT]),
            (self.gdi, 'DeleteObject', W.BOOL, [W.HANDLE]),
            (self.gdi, 'DeleteDC', W.BOOL, [W.HDC]),
            (self.dwm, 'DwmGetWindowAttribute', C.c_long, [W.HWND, W.DWORD, C.c_void_p, W.DWORD]),
        ]
        for library, name, result, args in signatures:
            function = getattr(library, name)
            function.restype, function.argtypes = result, args
        # 仅查询身份，不请求注入或调试权限。
        self.process = self.kernel.OpenProcess(0x1000, False, game['pid'])
        if not self.process:
            raise ValueError('无法访问游戏进程，请确认当前会话和权限')
        self.dpi = None
        try:
            self.validate_process()
            self.dpi = self.user.SetThreadDpiAwarenessContext(C.c_void_p(-4))
            if not self.dpi:
                raise ValueError('无法设置截图 DPI 上下文')
            windows = [h for h in self.windows() if self.owner(h) == game['pid'] and self.usable(h)]
            if len(windows) != 1:
                raise ValueError(f'游戏可见窗口不是唯一目标（{len(windows)} 个）；请关闭模态窗口或等待加载')
            self.hwnd = windows[0]
        except Exception:
            self.close()
            raise

    def windows(self):
        found = []
        callback = self.callback_type(lambda hwnd, _: found.append(hwnd) or True)
        self.user.EnumWindows(callback, 0)
        return found

    def owner(self, hwnd):
        pid = W.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, C.byref(pid))
        return pid.value

    def usable(self, hwnd):
        cloaked = W.DWORD()
        self.dwm.DwmGetWindowAttribute(hwnd, 14, C.byref(cloaked), C.sizeof(cloaked))
        return self.user.IsWindowVisible(hwnd) and not cloaked.value

    def validate_process(self):
        times = [W.FILETIME() for _ in range(4)]
        size = W.DWORD(32768)
        name = C.create_unicode_buffer(size.value)
        code = W.DWORD()
        if not (self.kernel.GetProcessTimes(self.process, *(C.byref(t) for t in times))
                and self.kernel.QueryFullProcessImageNameW(self.process, 0, name, C.byref(size))
                and self.kernel.GetExitCodeProcess(self.process, C.byref(code))):
            raise ValueError('无法核对游戏进程身份')
        created = ((times[0].dwHighDateTime << 32) + times[0].dwLowDateTime) / 10**7 - 11644473600
        if code.value != 259:
            raise ValueError('游戏进程已退出')
        if (abs(created - self.game['created_at']) > 0.01 or
                os.path.normcase(os.path.realpath(name.value)) != os.path.normcase(os.path.realpath(self.game['executable']))):
            raise ValueError('游戏进程身份不匹配，拒绝操作复用的 PID')

    def foreground(self):
        self.validate_process()
        if self.owner(self.hwnd) != self.game['pid']:
            raise ValueError('游戏窗口归属已改变')
        if self.user.IsIconic(self.hwnd):
            self.user.ShowWindow(self.hwnd, 9)
        if self.user.GetForegroundWindow() != self.hwnd:
            self.user.SetForegroundWindow(self.hwnd)
        deadline = time.monotonic() + 2
        while self.user.GetForegroundWindow() != self.hwnd and time.monotonic() < deadline:
            time.sleep(0.05)
        self.check_foreground()
        time.sleep(0.15)

    def check_foreground(self):
        if getattr(self, 'cancel', None) is not None and self.cancel.is_set():
            raise ValueError('桌面操作已取消')
        self.validate_process()
        if self.owner(self.hwnd) != self.game['pid'] or self.user.GetForegroundWindow() != self.hwnd:
            raise ValueError('无法确认游戏为前台窗口；请手动激活游戏后重试')

    def press(self, key, hold_ms):
        keys = parse_keys(key)
        if not 20 <= hold_ms <= 60000:
            raise ValueError('--hold-ms 必须在 20–60000 之间')
        self.foreground()
        virtual_keys = [k.vk or self.user.MapVirtualKeyW(k.scan | (0xE000 if k.extended else 0), 3)
                        for k in keys]
        for modifier in MODIFIERS | set(virtual_keys):
            if self.user.GetAsyncKeyState(modifier) & 0x8000:
                raise ValueError('目标键或修饰键当前被按住，请松开后重试')
        pressed, release_failed = [], False
        try:
            for item in keys:
                self.check_foreground()
                flags = (1 if item.extended else 0) | (8 if item.scan else 0)
                event = Input(kind=1, keyboard=Keyboard(item.vk, item.scan, flags, 0, 0))
                # 先记录再调用，保证 SendInput 返回期间中断也会尝试释放。
                pressed.append(event)
                if self.user.SendInput(1, C.byref(event), C.sizeof(event)) != 1:
                    raise ValueError('按键未完整发送，可能被 Windows 权限限制')
            deadline = time.monotonic() + hold_ms / 1000
            while time.monotonic() < deadline:
                self.check_foreground()
                time.sleep(min(0.02, max(0, deadline - time.monotonic())))
        finally:
            # 逆序释放全部按键；单键释放失败也继续释放其他键。
            for event in reversed(pressed):
                event.keyboard.flags |= 2
                try:
                    if self.user.SendInput(1, C.byref(event), C.sizeof(event)) != 1:
                        release_failed = True
                except BaseException:
                    release_failed = True
            if release_failed:
                raise ValueError('部分按键释放结果未知；请松开本次按键并检查游戏')
        self.check_foreground()
        names = [item.name for item in keys]
        return {'key': '+'.join(names), 'keys': names, 'hold_ms': hold_ms,
                'sent': True, 'released': True, 'effect_verified': False}

    def client_area(self):
        rect, point = W.RECT(), W.POINT()
        if not self.user.GetClientRect(self.hwnd, C.byref(rect)) or not self.user.ClientToScreen(self.hwnd, C.byref(point)):
            raise ValueError('无法获取游戏客户区')
        width, height = rect.right, rect.bottom
        if not 1 <= width * height <= 32_000_000:
            raise ValueError('游戏窗口尺寸无效或超过 3200 万像素')
        left, top = self.user.GetSystemMetrics(76), self.user.GetSystemMetrics(77)
        if not (left <= point.x and top <= point.y and point.x + width <= left + self.user.GetSystemMetrics(78)
                and point.y + height <= top + self.user.GetSystemMetrics(79)):
            raise ValueError('游戏客户区部分位于屏幕外，无法可靠截图')
        # 可见截图要求无上层窗口覆盖；宁可拒绝，也不截取其他应用内容。
        for hwnd in self.windows():
            if hwnd == self.hwnd:
                break
            if self.usable(hwnd) and not self.user.IsIconic(hwnd):
                other = W.RECT()
                if self.user.GetWindowRect(hwnd, C.byref(other)) and (
                    max(other.left, point.x) < min(other.right, point.x + width) and
                    max(other.top, point.y) < min(other.bottom, point.y + height)):
                    raise ValueError('游戏客户区被其他窗口覆盖，请移开后重试')
        self.check_foreground()
        return width, height, point

    def screenshot(self):
        self.foreground()
        width, height, point = self.client_area()
        screen = self.user.GetDC(None)
        memory = self.gdi.CreateCompatibleDC(screen)
        bitmap = self.gdi.CreateCompatibleBitmap(screen, width, height)
        old = None
        try:
            if not screen or not memory or not bitmap:
                raise ValueError('无法分配截图资源')
            old = self.gdi.SelectObject(memory, bitmap)
            if not self.gdi.BitBlt(memory, 0, 0, width, height, screen, point.x, point.y, 0x00CC0020):
                raise ValueError('游戏客户区截图失败')
            self.gdi.SelectObject(memory, old)
            old = None
            header = BitmapHeader(size=C.sizeof(BitmapHeader), width=width, height=-height, planes=1, bits=32)
            buffer = C.create_string_buffer(width * height * 4)
            if self.gdi.GetDIBits(memory, bitmap, 0, height, buffer, C.byref(header), 0) != height:
                raise ValueError('无法读取截图像素')
            self.check_foreground()
            after_rect, after_point = W.RECT(), W.POINT()
            if (not self.user.GetClientRect(self.hwnd, C.byref(after_rect)) or
                    not self.user.ClientToScreen(self.hwnd, C.byref(after_point)) or
                    (after_rect.right, after_rect.bottom, after_point.x, after_point.y) !=
                    (width, height, point.x, point.y)):
                raise ValueError('截图期间窗口位置或尺寸变化，请重试')
            if not any(buffer.raw[0::4]) and not any(buffer.raw[1::4]) and not any(buffer.raw[2::4]):
                raise ValueError('截图全黑；请使用窗口化模式或 Computer Use 截图')
            return png_bytes(width, height, buffer.raw), width, height
        finally:
            if old:
                self.gdi.SelectObject(memory, old)
            if bitmap:
                self.gdi.DeleteObject(bitmap)
            if memory:
                self.gdi.DeleteDC(memory)
            if screen:
                self.user.ReleaseDC(None, screen)

    def mouse(self, action, *, x=None, y=None, width=None, height=None, to_x=None, to_y=None,
              dx=0, dy=0, delta=0, button='left', duration_ms=80, keys=()):
        if action not in ('move', 'click', 'double-click', 'scroll', 'drag', 'relative'):
            raise ValueError('未知鼠标动作')
        if type(duration_ms) is not int or not 20 <= duration_ms <= 60000:
            raise ValueError('duration-ms 必须在 20–60000 之间')
        if button not in ('left', 'right', 'middle'):
            raise ValueError('未知鼠标按钮')
        modifiers = parse_keys(keys) if keys else []
        if any(k.vk not in MODIFIERS for k in modifiers):
            raise ValueError('鼠标组合键只能使用命名修饰键')
        for value in (dx, dy, delta):
            if type(value) is not int or abs(value) > 100000:
                raise ValueError('相对位移或滚轮数值超出范围')
        self.foreground()
        area_width, area_height, origin = self.client_area()
        if action != 'relative':
            if type(width) is not int or type(height) is not int or (width, height) != (area_width, area_height):
                raise ValueError('客户区尺寸与截图不一致，请重新截图')
            for px, py in [(x, y)] + ([(to_x, to_y)] if action == 'drag' else []):
                if type(px) is not int or type(py) is not int or not (0 <= px < width and 0 <= py < height):
                    raise ValueError('鼠标坐标不在游戏客户区内')
        for vk in MODIFIERS | {1, 2, 4}:
            if self.user.GetAsyncKeyState(vk) & 0x8000:
                raise ValueError('鼠标按钮或修饰键已被按住，请松开后重试')
        down, up = {'left': (2, 4), 'right': (8, 16), 'middle': (32, 64)}[button]
        pressed, release_failed = [], False

        def send(event):
            if self.user.SendInput(1, C.byref(event), C.sizeof(event)) != 1:
                raise ValueError('鼠标或修饰键未完整发送')

        def guard():
            self.check_foreground()
            aw, ah, pt = self.client_area()
            if (aw, ah, pt.x, pt.y) != (area_width, area_height, origin.x, origin.y):
                raise ValueError('操作期间窗口位置或尺寸变化，请重新截图')

        def absolute(px, py):
            guard()
            left, top = self.user.GetSystemMetrics(76), self.user.GetSystemMetrics(77)
            vw, vh = self.user.GetSystemMetrics(78), self.user.GetSystemMetrics(79)
            if vw <= 1 or vh <= 1:
                raise ValueError('无效的虚拟桌面尺寸')
            ax = round((origin.x + px - left) * 65535 / (vw - 1))
            ay = round((origin.y + py - top) * 65535 / (vh - 1))
            send(Input(kind=0, mouse=Mouse(ax, ay, 0, 0xC001, 0, 0)))

        def pause(seconds):
            until = time.monotonic() + seconds
            while time.monotonic() < until:
                guard()
                time.sleep(min(.02, max(0, until-time.monotonic())))

        try:
            for key in modifiers:
                guard()
                event = Input(kind=1, keyboard=Keyboard(key.vk, 0, int(key.extended), 0, 0))
                pressed.append(Input(kind=1, keyboard=Keyboard(key.vk, 0, int(key.extended) | 2, 0, 0)))
                send(event)
            if action != 'relative':
                absolute(x, y)
            if action in ('click', 'double-click', 'drag'):
                repeats = 2 if action == 'double-click' else 1
                for repeat in range(repeats):
                    guard()
                    pressed.append(Input(kind=0, mouse=Mouse(0, 0, 0, up, 0, 0)))
                    send(Input(kind=0, mouse=Mouse(0, 0, 0, down, 0, 0)))
                    if action == 'drag':
                        started = time.monotonic()
                        while True:
                            fraction = min(1.0, (time.monotonic()-started)/(duration_ms/1000))
                            absolute(round(x+(to_x-x)*fraction), round(y+(to_y-y)*fraction))
                            if fraction >= 1:
                                break
                            time.sleep(.02)
                    else:
                        pause(duration_ms/1000/repeats/2)
                    send(pressed[-1])
                    pressed.pop()
                    if repeat+1 < repeats:
                        pause(min(.1, duration_ms/1000/4))
            elif action == 'relative':
                started = time.monotonic()
                last_x = last_y = 0
                while True:
                    guard()
                    fraction = min(1.0, (time.monotonic()-started)/(duration_ms/1000))
                    px, py = round(dx*fraction), round(dy*fraction)
                    send(Input(kind=0, mouse=Mouse(px-last_x, py-last_y, 0, 1, 0, 0)))
                    last_x, last_y = px, py
                    if fraction >= 1:
                        break
                    time.sleep(.02)
            elif action == 'scroll':
                guard()
                send(Input(kind=0, mouse=Mouse(0, 0, delta & 0xFFFFFFFF, 0x800, 0, 0)))
        finally:
            for event in reversed(pressed):
                try:
                    send(event)
                except BaseException:
                    release_failed = True
            if release_failed:
                raise ValueError('输入释放失败，请检查鼠标和键盘状态')
        self.check_foreground()
        return {'action': action, 'sent': True, 'released': True, 'effect_verified': False}

    def details(self):
        title = C.create_unicode_buffer(1024)
        self.user.GetWindowTextW(self.hwnd, title, len(title))
        return {'pid': self.game['pid'], 'window': self.hwnd, 'window_title': title.value}

    def close(self):
        if self.dpi:
            self.user.SetThreadDpiAwarenessContext(self.dpi)
            self.dpi = None
        if self.process:
            self.kernel.CloseHandle(self.process)
            self.process = None



def operate(project, session, action, parameters=None, cancel=None):
    window = GameWindow(session_game(project, session), cancel=cancel)
    try:
        if action == 'screenshot':
            content, width, height = window.screenshot()
            result = {'content': content, 'width': width, 'height': height, 'capture': 'visible-client-area'}
        elif action == 'key':
            result = window.press(parameters['keys'], parameters.get('hold_ms', 80))
        elif action == 'mouse':
            result = window.mouse(**parameters)
        else:
            raise ValueError('未知桌面操作')
        return {'session': session, **window.details(), **result}
    finally:
        window.close()

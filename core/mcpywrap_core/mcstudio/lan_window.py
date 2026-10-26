"""后台采集菜单文字；不移动系统指针、不激活窗口。"""
import hashlib
import json
import subprocess

from .window import GameWindow


def helper():
    from ..host_assets import asset_directory
    root = asset_directory('window_capture')
    path = root/'mcpy-window-capture.exe'
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('ocr_protocol') != 1 or hashlib.sha256(path.read_bytes()).hexdigest() != manifest.get('executable_sha256'):
        raise ValueError('自动加入需要新版 Windows 菜单识别组件；请更新完整 mcpywrap，或使用 --join-mode manual。')
    return path


def observe(game):
    window = GameWindow(game)
    try:
        result = subprocess.run([str(helper()), '--hwnd',str(window.hwnd),'--ocr'],
                                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                creationflags=subprocess.CREATE_NO_WINDOW,timeout=12)
        window.validate_process()
        if result.returncode:
            raise ValueError('菜单识别不可用：'+result.stderr.decode('utf-8','replace'))
        if len(result.stdout)>512*1024:
            raise ValueError('菜单识别结果过大')
        data=json.loads(result.stdout)
        if data.get('protocol') != 1:
            raise ValueError('菜单识别协议不兼容')
        return data
    finally:
        window.close()

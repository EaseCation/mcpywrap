"""Discover official developer APK versions through NetEase's moving channels."""
import json
import re
from urllib.parse import urlsplit
from urllib.request import urlopen
from urllib.error import URLError
from http.client import HTTPException
from .host import EngineError

ENDPOINT = 'https://mc-launcher.webapp.163.com/users/get/download/'
CHANNELS = ('pe', 'pe_old')


def check_updates():
    from .install import selected
    current = selected()
    installed = current['catalog']['profile']['apk']['version'] if current else None
    versions, errors = [], []
    for channel in CHANNELS:
        try:
            with urlopen(ENDPOINT + channel, timeout=20) as response:
                raw = response.read(65537)
            if len(raw) > 65536: raise ValueError('响应过大')
            data = json.loads(raw)
            if data.get('status') != 'ok': raise ValueError('官方接口未返回成功状态')
            url = data['data']['url']
            parsed = urlsplit(url)
            match = re.fullmatch(r'/dev_launcher_([0-9]+(?:\.[0-9]+)+)\.apk', parsed.path)
            if (parsed.scheme != 'https' or parsed.hostname != 'g79.gdl.netease.com'
                    or parsed.username or parsed.password or parsed.port not in (None, 443)
                    or parsed.fragment or not match):
                raise ValueError('官方接口返回了无法识别的开发者 APK 地址')
            version = match.group(1)
            newer = tuple(map(int, version.split('.'))) > tuple(map(int, installed.split('.'))) if installed else None
            versions.append({'channel': channel, 'version': version, 'url': url,
                             'newer_than_installed': newer,
                             'compatibility': 'installed' if version == installed else 'not_checked'})
        except (OSError, URLError, HTTPException, ValueError, KeyError, TypeError, AttributeError) as error:
            errors.append({'channel': channel, 'error': str(error)})
    if not versions:
        raise EngineError('无法获取网易开发者版信息。', 'version_check_failed',
                          '请检查网络后重试；已安装版本仍可使用。', channel_errors=errors)
    return {'ok': not errors, 'installed_version': installed, 'versions': versions,
            'channel_errors': errors, 'error': '部分版本信息获取失败。' if errors else None,
            'hint': '检查网络后重试。' if errors else None}

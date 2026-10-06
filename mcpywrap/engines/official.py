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


def discover(channel='pe'):
    if channel not in CHANNELS:
        raise EngineError('未知的网易版本频道。', 'invalid_channel')
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
        return {'channel': channel, 'version': version, 'url': url}
    except (OSError, URLError, HTTPException, ValueError, KeyError, TypeError, AttributeError) as error:
        raise EngineError('无法获取网易 ' + channel + ' 版本信息：' + str(error), 'version_check_failed',
                          '请检查网络后重试；本地已安装版本仍可使用。') from None


def check_updates():
    from .install import selected
    current = selected()
    installed = current['catalog']['profile']['apk']['version'] if current else None
    versions, errors = [], []
    for channel in CHANNELS:
        try:
            item = discover(channel)
            version, url = item['version'], item['url']
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


def signed_url(url):
    """Sign the exact CDN path returned by NetEase; never construct a version path."""
    import hashlib
    import time
    from urllib.parse import urlencode, urlunsplit
    from .install import CDN_CONSTANT
    parsed = urlsplit(url)
    expiry = format(int(time.time()) + 43200, 'x')
    key = hashlib.md5((CDN_CONSTANT + parsed.path + expiry).encode()).hexdigest()
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
                      urlencode({'key1': key, 'key2': expiry}), ''))


def prepare_latest(root, progress=None):
    from pathlib import Path
    from urllib.request import Request
    import shutil
    from . import install
    from .apk_profile import inspect_apk
    install._phase(progress, '查询网易最新开发者版')
    item = discover('pe')
    url = signed_url(item['url'])
    try:
        with urlopen(Request(url, headers={'Range': 'bytes=0-0'}), timeout=30) as response:
            value = response.headers.get('Content-Range', '')
            match = re.fullmatch(r'bytes 0-0/([0-9]+)', value)
            if response.status != 206 or not match: raise ValueError('Invalid download size response')
            size = int(match.group(1))
            validator = response.headers.get('ETag') or response.headers.get('Last-Modified')
            if not validator or not 0 < size <= 16*1024**3: raise ValueError('Invalid download identity')
    except (OSError, URLError, HTTPException, ValueError) as error:
        raise EngineError('无法连接网易下载服务器：'+str(error), 'download_failed',
                          '请检查网络后重新运行；本地已安装版本仍可使用。') from None
    filename = Path(urlsplit(item['url']).path).name
    cache = Path(root)/'cache'; cache.mkdir(parents=True, exist_ok=True)
    target = cache/filename
    receipt = target.with_suffix('.apk.official.json')
    identity = {'url': item['url'], 'validator': validator}
    cached = False
    if target.is_file() and receipt.is_file():
        try:
            record = install.read_json(receipt)
            cached = (all(record.get(k) == v for k,v in identity.items()) and target.stat().st_size == size
                      and install.digest(target) == record.get('sha256'))
        except (ValueError, TypeError, AttributeError): pass
    # A previously verified pinned download is still reusable, but only for the
    # exact version currently returned by pe. Never offer an absent older APK.
    if not cached and target.is_file():
        current = install.selected()
        known = current['catalog']['profile']['apk'] if current else None
        if known and known['filename'] == filename and known['size'] == size:
            cached = install.digest(target) == known['sha256']
    if not cached:
        part = target.with_suffix('.apk.part')
        allocated = min(size, getattr(part.stat(), 'st_blocks', 0)*512) if part.is_file() else 0
        if shutil.disk_usage(cache).free < size-allocated+128*1024*1024:
            raise EngineError('可用空间不足，无法下载游戏资源。', 'disk_space', '释放磁盘空间后重试。')
        install._phase(progress, '下载游戏资源 '+item['version'])
        install._fetch_ranges(url, target, None, size, progress, source_identity=identity)
    install._phase(progress, '校验开发者 APK')
    try:
        profile = inspect_apk(target, item['version'])
    except EngineError:
        # Unverified cache is not a usable installation. Force a fresh download
        # next time; leave all installed versions and world directories intact.
        receipt.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise
    install.write_json(receipt, dict(identity, sha256=profile['apk']['sha256']))
    return profile, target

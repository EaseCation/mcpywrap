"""Opt-in MCS identity snapshot through the locally built, one-shot x86 bridge."""
import base64
from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit
import uuid

import psutil


class AuthError(ValueError):
    def __init__(self, message, code='identity_unavailable'):
        super().__init__(message)
        self.code = code
        self.hint = '按提示处理后重试；不需要账号身份时，去掉 --mcs-auth 仍可使用普通测试。'


@dataclass(repr=False)
class AuthContext:
    token: str = field(repr=False)
    player_info: dict = field(repr=False)
    auth_server_url: str
    web_server_url: str
    core_server_url: str
    mcs_pid: int

    @classmethod
    def parse(cls, data, pid):
        try:
            token = data['token']
            player = data['player_info']
            valid = (data['schema_version'] == 1 and data['mcs_pid'] == pid and
                     isinstance(token, str) and len(base64.b64decode(token, validate=True)) == 16 and
                     isinstance(player, dict) and all(isinstance(player.get(k), (str, int)) and
                     bool(player[k]) for k in ('user_id', 'user_name', 'urs')))
            for key in ('auth_server_url', 'web_server_url', 'core_server_url'):
                url = urlsplit(data[key])
                valid = valid and url.scheme == 'https' and bool(url.hostname) and not url.username and not url.password
            if not valid:
                raise ValueError()
            return cls(token, {k: player[k] for k in ('user_id', 'user_name', 'urs')},
                       data['auth_server_url'], data['web_server_url'], data['core_server_url'], pid)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise AuthError('未能读取可用的登录身份，请确认 MC Studio 已完成登录后重试。') from None

    def apply(self, config):
        config['room_info']['token'] = self.token
        config['player_info'] = dict(self.player_info)
        config.setdefault('misc', {'multiplayer_game_type': 0})['auth_server_url'] = self.auth_server_url
        config['web_server_url'] = self.web_server_url
        config['core_server_url'] = self.core_server_url

    def secrets(self):
        raw = base64.b64decode(self.token)
        return [self.token, raw.hex(), raw.hex().upper()] + [str(v) for v in self.player_info.values()]

    def to_payload(self):
        return {'schema_version': 1, 'mcs_pid': self.mcs_pid, 'token': self.token,
                'player_info': self.player_info, 'auth_server_url': self.auth_server_url,
                'web_server_url': self.web_server_url, 'core_server_url': self.core_server_url}


@contextmanager
def bridge_lock(directory):
    import msvcrt
    # A shared request file is safe only while this process holds the bridge lock.
    with (directory/'capture.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise AuthError('MCS 身份桥接正在被另一个调用使用，请稍后重试') from None
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def running_studio():
    found = []
    for process in psutil.process_iter(['name', 'exe', 'create_time']):
        if (process.info['name'] or '').casefold() == 'mcstudio.exe' and process.info['exe']:
            found.append(process)
    if len(found) != 1:
        raise AuthError('请先打开并登录 MC Studio；如果同时开了多个，请只保留要使用的一个，再重试。'
                        '不需要登录身份时，可以去掉 --mcs-auth。', 'studio_unavailable')
    return found[0]


def capture_identity():
    try:
        return _capture_identity()
    except psutil.Error:
        raise AuthError('MC Studio 在读取身份时退出或无法访问。请重新打开并登录后再试。', 'studio_unavailable') from None
    except OSError:
        raise AuthError('无法准备或读取本机登录组件。请检查当前用户是否能访问组件缓存，或重新安装 mcpywrap。',
                        'component_unavailable') from None


def _capture_identity():
    if os.name != 'nt':
        raise AuthError('MCS 身份桥接仅支持 Windows')
    studio = running_studio()
    from .bridge_assets import bridge_directory
    try:
        directory = bridge_directory()
    except (ValueError, OSError) as exc:
        raise AuthError(str(exc), 'component_unavailable') from None
    executable, created = studio.exe(), studio.create_time()
    with bridge_lock(directory):
        request = directory/'request.json'
        status = directory/'loader-status.txt'
        status.unlink(missing_ok=True)
        (directory/'bridge-status.txt').unlink(missing_ok=True)
        request.write_text(json.dumps({'pipe': 'mcpy-mcs-auth-'+uuid.uuid4().hex,
                                       'nonce': uuid.uuid4().hex}), encoding='utf-8')
        try:
            result = subprocess.run([str(directory/'Injector.exe'), str(studio.pid), executable,
                                     str(directory/'Loader.dll')], capture_output=True, timeout=40,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                bridge_status = directory/'bridge-status.txt'
                if bridge_status.is_file() and bridge_status.read_text().startswith('error:'):
                    raise AuthError('无法从 MC Studio 读取当前身份。请确认已经登录；升级登录组件后可重启 MC Studio 再试。'
                                    '仍然失败时，请保留普通测试方式并向项目反馈 MCS 版本。')
                raise AuthError('Windows 或 MC Studio 未允许登录组件启用。普通测试仍可使用；'
                                '可去掉 --mcs-auth，或请管理员检查应用控制策略。', 'component_blocked')
            try:
                data = json.loads(result.stdout.decode('utf-8-sig'))
            except (ValueError, UnicodeError):
                raise AuthError('MCS 身份桥接返回了无效响应') from None
            deadline = time.monotonic()+5
            while not status.is_file() and time.monotonic() < deadline:
                time.sleep(.05)
            if not status.is_file() or status.read_text() != 'HRESULT=0x00000000; managed_result=0':
                raise AuthError('MCS 身份桥接未正常结束')
            if not studio.is_running() or studio.create_time() != created:
                raise AuthError('读取身份时 MCS 已退出或被替换')
            return AuthContext.parse(data, studio.pid)
        except subprocess.TimeoutExpired:
            raise AuthError('MCS 身份桥接超时；未回退到匿名连接') from None
        except OSError as exc:
            if getattr(exc, 'winerror', None) in (5, 577, 1260, 4551):
                raise AuthError('Windows 阻止了登录组件。普通游戏测试不受影响；'
                                '如由组织管理此电脑，请联系管理员。', 'component_blocked') from None
            raise AuthError('登录组件无法启动，请重新安装 mcpywrap 后重试。', 'component_unavailable') from None
        finally:
            request.unlink(missing_ok=True)


def acquire_identity(interactive=None):
    """Try first, offer a narrowly scoped human recovery once, and never fall back silently."""
    if interactive is None:
        from ..command_context import human_interaction
        interactive = human_interaction()
    try:
        return capture_identity()
    except AuthError as first:
        if not interactive:
            raise
        from . import auth_interaction as ui
        try:
            if first.code == 'component_blocked':
                from .bridge_assets import bridge_directory, trusted_certificate_candidate
                directory = bridge_directory()
                certificate = trusted_certificate_candidate(directory)
                if certificate and ui.certificate_can_help(directory, certificate):
                    if not ui.confirm_certificate(certificate):
                        raise AuthError('已取消启用登录身份。去掉 --mcs-auth 即可继续普通测试。', 'cancelled')
                    # Validate the cached payload again after the user has made a decision.
                    if trusted_certificate_candidate(directory) != certificate:
                        raise AuthError('登录组件在确认期间发生了变化，请重新安装后重试。')
                    ui.install_certificate(certificate)
                    try:
                        return capture_identity()
                    except AuthError as retry_error:
                        if retry_error.code != 'component_blocked':
                            raise AuthError('证书已安装，但'+str(retry_error), retry_error.code) from None
                        raise AuthError('证书已安装，但登录组件仍无法启用。Windows 智能应用控制或组织策略可能仍在阻止它；'
                                        '证书安装不能覆盖这些限制。你仍可去掉 --mcs-auth 使用普通测试。', 'component_blocked') from None
            raise first
        except (AuthError, OSError, ValueError, subprocess.TimeoutExpired) as error:
            if getattr(error, 'code', None) != 'cancelled':
                ui.show_failure(str(error))
            if isinstance(error, AuthError):
                raise
            raise AuthError('登录身份未能启用。请稍后重试，或去掉 --mcs-auth 继续普通测试。') from None

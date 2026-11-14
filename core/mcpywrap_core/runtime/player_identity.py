"""离线开发身份：由玩家名确定的匿名身份，不是认证账号。

中国版允许中文昵称，玩家名可用汉字、英文字母、数字和下划线，最长 16 个字符；
不含空白、引号或控制字符，写入 cppconfig 或游戏内表达式时不需要额外转义规则。
user_id 由名称稳定派生，同名在不同会话、世界和平台上得到同一身份，服务端或存档
按 ID 识别玩家时不会因重启而变化。
"""
import hashlib
import re

NAME_PATTERN = re.compile('[A-Za-z0-9_\u3400-\u4dbf\u4e00-\u9fff]{1,16}')
ASCII_PATTERN = re.compile(r'[A-Za-z0-9_]{1,16}')
NAME_RULE = '1–16 个汉字、英文字母、数字或下划线'


def valid_name(name):
    return isinstance(name, str) and NAME_PATTERN.fullmatch(name) is not None


def ascii_name(name):
    """旧运行包（0.4.9/0.4.10）的联机身份只接受英文名。"""
    return ASCII_PATTERN.fullmatch(name) is not None


def player_identity(name):
    """返回 {'user_name', 'user_id'}；名称无效时抛出 ValueError。"""
    if not valid_name(name):
        raise ValueError('玩家名需为' + NAME_RULE + '：' + repr(name))
    digest = hashlib.sha256(('mcpy-player:' + name).encode('utf-8')).digest()
    return {'user_name': name, 'user_id': int.from_bytes(digest[:4], 'big') % (2**31 - 1) + 1}


def requested_players(names, clients=1):
    """把 CLI 的 --player-name 列表转换为每个客户端的身份；未指定返回 None。"""
    names = list(names or ())
    if not names:
        return None
    if len(names) != clients:
        raise ValueError('--player-name 需要为每个客户端各指定一次（当前 %d 个客户端，收到 %d 个）'
                         % (clients, len(names)))
    players = [player_identity(name) for name in names]
    # 服务器通常不区分玩家名大小写，同名会被判为重复登录。
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError('两个客户端的玩家名不能相同（不区分大小写）')
    return players


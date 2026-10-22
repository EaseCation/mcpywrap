"""Wire constants and validation; importing the client never loads a game host."""
import re

PROTOCOL = 1
ID = re.compile(r'^[0-9a-f]{32}$')


class RemoteError(ValueError):
    def __init__(self, message, code='execution_failed', status=400, hint=None):
        super().__init__(message)
        self.code, self.status, self.hint = code, status, hint


def fields(data, allowed):
    if not isinstance(data, dict) or data.keys() - set(allowed):
        raise RemoteError('请求包含未知字段或不是 JSON 对象', 'invalid_request')


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise RemoteError('无效的会话或请求 ID', 'invalid_request')
    return value

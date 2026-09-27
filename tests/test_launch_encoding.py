"""非 UTF-8 重定向输出不应阻断启动。"""
import io
import unittest
from unittest.mock import patch
from mcpywrap.mcstudio.game import _launch_message


class LaunchEncoding(unittest.TestCase):
    def test_gbk_stream_keeps_diagnostic_text(self):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding='gbk')
        with patch('sys.stdout', stream):
            _launch_message('🎮 使用引擎版本: 3.9', fg='green')
        stream.flush()
        self.assertIn('使用引擎版本: 3.9', buffer.getvalue().decode('gbk'))

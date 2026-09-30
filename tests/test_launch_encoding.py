"""非 UTF-8 重定向输出不应阻断启动。"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
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

    def test_real_cli_init_under_gbk_and_utf8_pipes(self):
        root = Path(__file__).resolve().parents[1]
        for encoding in ('gbk', 'utf-8'):
            for structured in (False, True):
                with self.subTest(encoding=encoding, json=structured), tempfile.TemporaryDirectory() as tmp:
                    project = Path(tmp)/'中文项目'
                    project.mkdir()
                    command = [sys.executable, '-m', 'mcpywrap', '--local', '--project', str(project),
                               '--non-interactive', 'init', '--name', 'encoding-test', '--type', 'addon']
                    if structured:
                        command.append('--json')
                    result = subprocess.run(command, cwd=root, capture_output=True, timeout=30,
                                            env=dict(os.environ, PYTHONIOENCODING=encoding,
                                                     PYTHONUTF8='0', QT_QPA_PLATFORM='offscreen'))
                    stdout = result.stdout.decode(encoding)
                    stderr = result.stderr.decode(encoding)
                    self.assertEqual(result.returncode, 0, stdout+stderr)
                    self.assertNotIn('UnicodeEncodeError', stderr)
                    self.assertTrue((project/'pyproject.toml').is_file())
                    if structured:
                        self.assertTrue(json.loads(stdout)['ok'])

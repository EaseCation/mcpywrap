"""Shared Studio log formatting rules, independent of Qt and transport."""
import os
import re
import sys


class LogColorizer:
    # ANSI 颜色代码
    ANSI_RESET = "\033[0m"
    ANSI_BLACK = "\033[30m"
    ANSI_RED = "\033[31m"
    ANSI_GREEN = "\033[32m"
    ANSI_YELLOW = "\033[33m"
    ANSI_BLUE = "\033[34m"
    ANSI_MAGENTA = "\033[35m"
    ANSI_CYAN = "\033[36m"
    ANSI_WHITE = "\033[37m"
    ANSI_BRIGHT_BLACK = "\033[90m"
    ANSI_BRIGHT_RED = "\033[91m"
    ANSI_BRIGHT_GREEN = "\033[92m"
    ANSI_BRIGHT_YELLOW = "\033[93m"
    ANSI_BRIGHT_BLUE = "\033[94m"
    ANSI_BRIGHT_MAGENTA = "\033[95m"
    ANSI_BRIGHT_CYAN = "\033[96m"
    ANSI_BRIGHT_WHITE = "\033[97m"

    # Shared palette; Qt widgets construct QColor only when rendering.
    COLORS = {
        'reset': None,  # 使用默认颜色
        'black': "#000000",
        'red': "#CC0000",
        'green': "#00CC00",
        'yellow': "#CCCC00",
        'blue': "#0000CC",
        'magenta': "#CC00CC",
        'cyan': "#00CCCC",
        'white': "#CCCCCC",
        'bright_black': "#666666",
        'bright_red': "#FF0000",
        'bright_green': "#00FF00",
        'bright_yellow': "#FFFF00",
        'bright_blue': "#0088FF",
        'bright_magenta': "#FF00FF",
        'bright_cyan': "#00FFFF",
        'bright_white': "#FFFFFF"
    }

    def __init__(self, use_qt_colors=False):
        self.use_qt_colors = use_qt_colors
        self.ansi_colors = self._get_ansi_colors()

        # 编译常用的正则表达式模式
        self.patterns = {
            'server_status': re.compile(r'^\[\+\]|^\[-\]'),
            'server_error': re.compile(r'^\[!\]'),
            'timestamp_log': re.compile(r'^\[\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d+\]'),
            'log_prefix': re.compile(r'\[[A-Za-z0-9_]+\]'),  # 匹配所有格式为[xxx]的前缀
            'log_level_info': re.compile(r'\[INFO\]'),
            'log_level_error': re.compile(r'\[ERROR\]'),
            'log_level_warning': re.compile(r'\[WARNING\]|\[WARN\]'),
            'log_level_debug': re.compile(r'\[DEBUG\]'),
            'log_level_developer': re.compile(r'\[Developer\]'),
            'log_level_engine': re.compile(r'\[Engine\]'),
            'client_event': re.compile(r'onRoom|callback|event|listener'),
            'custom_log_tag': re.compile(r'^\[\w+\]'),
            'load_message': re.compile(r'^LoadWindowsAddonPy|^ECRLMaya|^MayaCraft'),
            'success_message': re.compile(r'success|succeeded|complete|done', re.IGNORECASE),
            'command_response': re.compile(r'^{.+}$')
        }

    def _get_ansi_colors(self):
        """获取ANSI颜色代码"""
        # 如果终端不支持彩色，则使用空字符串
        if not self._supports_color():
            no_color = ""
            return {k: no_color for k in [
                'reset', 'black', 'red', 'green', 'yellow', 'blue',
                'magenta', 'cyan', 'white', 'bright_black', 'bright_red',
                'bright_green', 'bright_yellow', 'bright_blue',
                'bright_magenta', 'bright_cyan', 'bright_white'
            ]}

        return {
            'reset': self.ANSI_RESET,
            'black': self.ANSI_BLACK,
            'red': self.ANSI_RED,
            'green': self.ANSI_GREEN,
            'yellow': self.ANSI_YELLOW,
            'blue': self.ANSI_BLUE,
            'magenta': self.ANSI_MAGENTA,
            'cyan': self.ANSI_CYAN,
            'white': self.ANSI_WHITE,
            'bright_black': self.ANSI_BRIGHT_BLACK,
            'bright_red': self.ANSI_BRIGHT_RED,
            'bright_green': self.ANSI_BRIGHT_GREEN,
            'bright_yellow': self.ANSI_BRIGHT_YELLOW,
            'bright_blue': self.ANSI_BRIGHT_BLUE,
            'bright_magenta': self.ANSI_BRIGHT_MAGENTA,
            'bright_cyan': self.ANSI_BRIGHT_CYAN,
            'bright_white': self.ANSI_BRIGHT_WHITE
        }

    def _supports_color(self):
        """检查终端是否支持颜色"""
        # 如果已经设置了 NO_COLOR 环境变量，遵循这个标准
        if 'NO_COLOR' in os.environ:
            return False

        # Windows 特殊处理
        if sys.platform == 'win32':
            # Windows 10 默认支持 ANSI 颜色
            return True

        # 检查是否是 TTY 终端
        return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()

    def _terminal_segments(self, segments):
        parts = []
        for text, color in segments:
            prefix = self.ansi_colors.get(color, '') if color != 'reset' else ''
            parts.append(prefix + text + self.ansi_colors['reset'] if prefix else text)
        return ''.join(parts)

    def colorize_terminal(self, text):
        """Terminal and Qt use the same classification; only rendering differs."""
        return ''.join(self._terminal_segments(self.analyze_text(line))
                       for line in text.splitlines(keepends=True))

    def colorize_timestamp_log(self, text):
        return self._terminal_segments(self.analyze_timestamp_log(text))

    def analyze_text(self, text):
        """分析文本，返回需要着色的段落和颜色信息"""
        segments = []

        # 如果是空文本，直接返回
        if not text:
            return segments

        # 服务器状态消息
        if self.patterns['server_status'].search(text):
            if '[+]' in text:  # 正向消息
                segments.append((text, 'bright_green'))
            else:  # 负面消息或关闭消息
                segments.append((text, 'bright_cyan'))
            return segments

        # 服务器错误消息
        if self.patterns['server_error'].search(text):
            segments.append((text, 'bright_red'))
            return segments

        # 时间戳日志条目处理
        if self.patterns['timestamp_log'].search(text):
            return self.analyze_timestamp_log(text)

        if re.search(r'\b(?:Error|ERROR|Exception|Traceback)\b', text):
            return [(text, 'bright_red')]
        if re.search(r'\b(?:Warn|WARNING|WARN)\b', text):
            return [(text, 'bright_yellow')]
        # 自定义日志标签
        if self.patterns['custom_log_tag'].search(text):
            segments.append((text, 'bright_magenta'))
            return segments

        # 加载消息
        if self.patterns['load_message'].search(text):
            segments.append((text, 'bright_blue'))
            return segments

        # 成功消息
        if self.patterns['success_message'].search(text):
            segments.append((text, 'bright_green'))
            return segments

        # 客户端事件
        if self.patterns['client_event'].search(text):
            segments.append((text, 'bright_yellow'))
            return segments

        # 命令响应 (JSON格式)
        if self.patterns['command_response'].search(text):
            segments.append((text, 'bright_cyan'))
            return segments

        # 默认不添加颜色
        segments.append((text, 'reset'))
        return segments

    def analyze_timestamp_log(self, text):
        """分析带有时间戳的日志条目，返回需要着色的段落列表"""
        segments = []

        # 提取时间戳部分
        timestamp_match = self.patterns['timestamp_log'].search(text)
        timestamp_part = text[:timestamp_match.end()]
        rest_of_text = text[timestamp_match.end():]

        # 添加时间戳部分
        segments.append((timestamp_part, 'bright_black'))

        # 处理日志级别前缀
        # 查找所有前缀 [XXX]
        prefixes = self.patterns['log_prefix'].findall(rest_of_text)
        if prefixes:
            current_pos = 0
            for prefix in prefixes:
                # 找到前缀在文本中的位置
                prefix_pos = rest_of_text.find(prefix, current_pos)
                if prefix_pos == -1:
                    continue

                # 添加前缀前的文本
                if prefix_pos > current_pos:
                    segments.append((rest_of_text[current_pos:prefix_pos], 'reset'))

                # 根据前缀类型确定颜色
                if '[ERROR]' in prefix:
                    segments.append((prefix, 'bright_red'))
                elif '[WARNING]' in prefix or '[WARN]' in prefix:
                    segments.append((prefix, 'bright_yellow'))
                elif '[SUCCESS]' in prefix:
                    segments.append((prefix, 'bright_green'))
                elif '[DEBUG]' in prefix:
                    segments.append((prefix, 'bright_black'))
                elif '[Developer]' in prefix:
                    segments.append((prefix, 'bright_magenta'))
                elif '[Engine]' in prefix:
                    segments.append((prefix, 'bright_blue'))
                elif '[INFO]' in prefix:
                    segments.append((prefix, 'bright_white'))
                else:
                    segments.append((prefix, 'bright_cyan'))

                # 更新当前位置
                current_pos = prefix_pos + len(prefix)

            # 添加剩余的文本
            if current_pos < len(rest_of_text):
                segments.append((rest_of_text[current_pos:], 'reset'))
        else:
            segments.append((rest_of_text, 'reset'))

        return segments

    def colorize(self, text):
        """根据日志内容添加适当的颜色（命令行模式）"""
        if not self.use_qt_colors:
            return self.colorize_terminal(text)
        else:
            # 在UI模式下仅返回分析结果供调用者处理
            return self.analyze_text(text)

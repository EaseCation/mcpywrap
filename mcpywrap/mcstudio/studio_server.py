#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import threading
import json
import time
import argparse
import sys
import re
import os

# 添加对 PyQt5 信号的支持
try:
    from PyQt5.QtCore import QObject, pyqtSignal, Qt
    from PyQt5.QtGui import QColor, QTextCharFormat
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False
    # 如果 PyQt5 不可用，创建一个虚拟的基类和信号类
    class QObject:
        pass
    
    class DummySignal:
        def __init__(self):
            pass
        
        def emit(self, *args, **kwargs):
            pass
        
        def connect(self, func):
            pass
    
    # 替代 pyqtSignal
    pyqtSignal = lambda *args, **kwargs: DummySignal()

# 日志彩色化工具类
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
    
    # Qt颜色映射（用于UI模式）
    QT_COLORS = {
        'reset': None,  # 使用默认颜色
        'black': QColor("#000000") if PYQT_AVAILABLE else None,
        'red': QColor("#CC0000") if PYQT_AVAILABLE else None,
        'green': QColor("#00CC00") if PYQT_AVAILABLE else None,
        'yellow': QColor("#CCCC00") if PYQT_AVAILABLE else None,
        'blue': QColor("#0000CC") if PYQT_AVAILABLE else None,
        'magenta': QColor("#CC00CC") if PYQT_AVAILABLE else None,
        'cyan': QColor("#00CCCC") if PYQT_AVAILABLE else None,
        'white': QColor("#CCCCCC") if PYQT_AVAILABLE else None,
        'bright_black': QColor("#666666") if PYQT_AVAILABLE else None,
        'bright_red': QColor("#FF0000") if PYQT_AVAILABLE else None,
        'bright_green': QColor("#00FF00") if PYQT_AVAILABLE else None,
        'bright_yellow': QColor("#FFFF00") if PYQT_AVAILABLE else None,
        'bright_blue': QColor("#0088FF") if PYQT_AVAILABLE else None,
        'bright_magenta': QColor("#FF00FF") if PYQT_AVAILABLE else None,
        'bright_cyan': QColor("#00FFFF") if PYQT_AVAILABLE else None,
        'bright_white': QColor("#FFFFFF") if PYQT_AVAILABLE else None
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
    
    def colorize_terminal(self, text):
        """为终端添加ANSI颜色代码"""
        # 如果是空文本，直接返回
        if not text:
            return text
            
        # 服务器状态消息
        if self.patterns['server_status'].search(text):
            if '[+]' in text:  # 正向消息
                return f"{self.ansi_colors['bright_green']}{text}{self.ansi_colors['reset']}"
            else:  # 负面消息或关闭消息
                return f"{self.ansi_colors['bright_cyan']}{text}{self.ansi_colors['reset']}"
        
        # 服务器错误消息
        if self.patterns['server_error'].search(text):
            return f"{self.ansi_colors['bright_red']}{text}{self.ansi_colors['reset']}"
            
        # 时间戳日志条目处理
        if self.patterns['timestamp_log'].search(text):
            return self.colorize_timestamp_log(text)
            
        # 自定义日志标签
        if self.patterns['custom_log_tag'].search(text):
            return f"{self.ansi_colors['bright_magenta']}{text}{self.ansi_colors['reset']}"
        
        # 加载消息
        if self.patterns['load_message'].search(text):
            return f"{self.ansi_colors['bright_blue']}{text}{self.ansi_colors['reset']}"
        
        # 成功消息
        if self.patterns['success_message'].search(text):
            return f"{self.ansi_colors['bright_green']}{text}{self.ansi_colors['reset']}"
        
        # 客户端事件
        if self.patterns['client_event'].search(text):
            return f"{self.ansi_colors['bright_yellow']}{text}{self.ansi_colors['reset']}"
        
        # 命令响应 (JSON格式)
        if self.patterns['command_response'].search(text):
            return f"{self.ansi_colors['bright_cyan']}{text}{self.ansi_colors['reset']}"
        
        # 默认不添加颜色
        return text
        
    def colorize_timestamp_log(self, text):
        """处理带有时间戳的日志条目"""
        # 提取时间戳部分
        timestamp_match = self.patterns['timestamp_log'].search(text)
        timestamp_part = text[:timestamp_match.end()]
        rest_of_text = text[timestamp_match.end():]
        
        colored_text = f"{self.ansi_colors['bright_black']}{timestamp_part}{self.ansi_colors['reset']}"
        
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
                    colored_text += rest_of_text[current_pos:prefix_pos]
                
                # 根据前缀类型添加不同颜色
                if '[ERROR]' in prefix:
                    colored_text += f"{self.ansi_colors['bright_red']}{prefix}{self.ansi_colors['reset']}"
                elif '[WARNING]' in prefix or '[WARN]' in prefix:
                    colored_text += f"{self.ansi_colors['bright_yellow']}{prefix}{self.ansi_colors['reset']}"
                elif '[DEBUG]' in prefix:
                    colored_text += f"{self.ansi_colors['bright_black']}{prefix}{self.ansi_colors['reset']}"
                elif '[Developer]' in prefix:
                    colored_text += f"{self.ansi_colors['bright_magenta']}{prefix}{self.ansi_colors['reset']}"
                elif '[Engine]' in prefix:
                    colored_text += f"{self.ansi_colors['bright_blue']}{prefix}{self.ansi_colors['reset']}"
                elif '[INFO]' in prefix:
                    colored_text += f"{self.ansi_colors['bright_white']}{prefix}{self.ansi_colors['reset']}"
                else:
                    colored_text += f"{self.ansi_colors['bright_cyan']}{prefix}{self.ansi_colors['reset']}"
                    
                # 更新当前位置
                current_pos = prefix_pos + len(prefix)
                
            # 添加剩余的文本
            if current_pos < len(rest_of_text):
                colored_text += rest_of_text[current_pos:]
        else:
            colored_text += rest_of_text
            
        return colored_text
    
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

class StudioLogServer(QObject if PYQT_AVAILABLE else object):
    # 定义信号 - 仅当 PyQt5 可用时才会是实际信号
    client_connected_signal = pyqtSignal()
    client_disconnected_signal = pyqtSignal()
    # 修改日志信号，发送文本和颜色分段信息
    log_received_signal = pyqtSignal(str, list)  # 参数: 原始日志文本, [(文本段, 颜色名称), ...]

    def __init__(self, host='0.0.0.0', port=8000):
        super().__init__()
        self.host = host
        self.port = port
        self.server_socket = None
        self.clients = []
        self.running = False
        # 命令历史记录
        self.command_history = []
        # 特殊命令处理
        self.special_commands = {
            'help': self.show_help,
            'list': self.list_clients,
            'exit': self.exit_server,
            'history': self.show_history
        }
        # 判断是否在UI中运行
        self.in_ui_mode = 'PyQt5' in sys.modules
        # 日志颜色器
        self.colorizer = LogColorizer(use_qt_colors=self.in_ui_mode)

    def start(self):
        """启动服务器"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.running = True
            print(f"[+] 服务器已启动，监听 {self.host}:{self.port}")
            
            # 如果不在UI模式下，启动命令输入线程
            if not self.in_ui_mode:
                cmd_thread = threading.Thread(target=self.command_input)
                cmd_thread.daemon = True
                cmd_thread.start()
                print("> ", end='', flush=True)
            
            # 接受客户端连接
            while self.running:
                try:
                    client_socket, client_address = self.server_socket.accept()
                    print(f"[+] 新客户端连接: {client_address[0]}:{client_address[1]}")
                    
                    client_info = {
                        'socket': client_socket,
                        'address': client_address,
                        'id': len(self.clients)
                    }
                    self.clients.append(client_info)
                    
                    # 发射客户端连接信号
                    self.client_connected_signal.emit()
                    
                    # 为每个客户端创建接收线程
                    client_thread = threading.Thread(
                        target=self.handle_client,
                        args=(client_info,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"[!] 接受连接时出错: {e}")
        
        except Exception as e:
            print(f"[!] 服务器启动失败: {e}")
        finally:
            self.shutdown()

    def handle_client(self, client_info):
        """处理客户端连接和数据"""
        client_socket = client_info['socket']
        client_id = client_info['id']
        
        try:
            while self.running:
                data = client_socket.recv(4096)
                if not data:
                    break
                
                # 检测命令消息格式 (chr(255) + json + chr(255))
                if data[0] == 255 and data[-1] == 255:
                    try:
                        json_data = data[1:-1].decode('utf-8')
                        cmd_data = json.loads(json_data)
                        
                        # 命令消息用特殊颜色标记
                        cmd_msg = f"[命令消息] 客户端 {client_id}:"
                        cmd_content = f"命令: {cmd_data.get('command')}"
                        msg_content = f"内容: {json.dumps(cmd_data.get('msg'), indent=2, ensure_ascii=False)}"
                        
                        # 命令行模式下打印彩色文本
                        if not self.in_ui_mode:
                            print(self.colorizer.colorize_terminal(cmd_msg))
                            print(self.colorizer.colorize_terminal(cmd_content))
                            print(self.colorizer.colorize_terminal(msg_content))
                        else:
                            # UI模式发送信号，包含颜色段信息
                            self.log_received_signal.emit(cmd_msg, [
                                (cmd_msg, 'bright_yellow')
                            ])
                            self.log_received_signal.emit(cmd_content, [
                                (cmd_content, 'bright_cyan')
                            ])
                            self.log_received_signal.emit(msg_content, [
                                (msg_content, 'bright_white')
                            ])
                            
                    except json.JSONDecodeError:
                        error_msg = f"[!] 无法解析JSON: {data[1:-1]}"
                        if not self.in_ui_mode:
                            print(self.colorizer.colorize_terminal(error_msg))
                        else:
                            self.log_received_signal.emit(error_msg, [
                                (error_msg, 'bright_red')
                            ])
                else:
                    # 普通日志消息，应用颜色处理
                    log_data = data.decode('utf-8', errors='replace')
                    
                    # 按行处理日志
                    lines = log_data.splitlines(True)  # 保留换行符
                    for line in lines:
                        if not self.in_ui_mode:
                            # 命令行模式，直接打印彩色文本
                            colored_line = self.colorizer.colorize_terminal(line)
                            print(colored_line, end='', flush=True)
                        else:
                            # UI模式，发送带颜色段信息的原始文本
                            color_segments = self.colorizer.analyze_text(line)
                            self.log_received_signal.emit(line, color_segments)
                
                # 只在非UI模式下显示命令提示符
                if not self.in_ui_mode:
                    print("\n> ", end='', flush=True)
                
        except ConnectionResetError:
            disconnect_msg = f"\n[!] 客户端 {client_id} 连接已重置"
            if not self.in_ui_mode:
                print(self.colorizer.colorize_terminal(disconnect_msg))
            else:
                self.log_received_signal.emit(disconnect_msg, [
                    (disconnect_msg, 'bright_red')
                ])
                
        except Exception as e:
            error_msg = f"\n[!] 处理客户端 {client_id} 时出错: {e}"
            if not self.in_ui_mode:
                print(self.colorizer.colorize_terminal(error_msg))
            else:
                self.log_received_signal.emit(error_msg, [
                    (error_msg, 'bright_red')
                ])
                
        finally:
            try:
                client_socket.close()
                self.clients.remove(client_info)
                disconnect_msg = f"\n[-] 客户端 {client_id} 已断开连接"
                
                if not self.in_ui_mode:
                    # 命令行模式下打印彩色文本
                    print(self.colorizer.colorize_terminal(disconnect_msg))
                else:
                    # UI模式发送信号
                    self.log_received_signal.emit(disconnect_msg, [
                        (disconnect_msg, 'bright_cyan')
                    ])
                
                # 发射客户端断开连接信号
                self.client_disconnected_signal.emit()
                
                if not self.in_ui_mode:
                    print("> ", end='', flush=True)
            except:
                pass

    def send_command(self, client_id, command, *args):
        """向特定客户端发送命令"""
        if client_id >= len(self.clients):
            print(f"[!] 客户端ID {client_id} 不存在")
            return False

        if command == "help":
            print(f"""
================
MC Studio 日志控制台 帮助：
reload_pack 重新加载脚本
reload_cache 重新加载位于缓存目录(packcache)的脚本
start_profile 启动客户端脚本性能分析(PC端)
stop_profile 停止客户端脚本性能分析(PC端)
start_mem_profile 停止客户端内存性能分析(PC端)
stop_mem_profile 停止客户端内存性能分析(PC端)
create_world 创建新世界
restart_local_game 重载存档
release_mouse 释放鼠标
begin_performance_profile 开始性能分析
end_performance_profile 停止性能分析
log_performance_profile_data 打印性能分析日志
================
""")
            return
        client = self.clients[client_id]
        command_str = f"{command} {' '.join(args)}"
        
        try:
            client['socket'].send(f"{command_str}\x00".encode('utf-8'))
            self.command_history.append(command_str)
            print(f"[+] 命令已发送到客户端 {client_id}: {command_str}")
            return True
        except Exception as e:
            print(f"[!] 发送命令失败: {e}")
            return False

    def broadcast_command(self, command, *args):
        """向所有客户端广播命令"""
        command_str = f"{command} {' '.join(args)}"
        success = False
        
        for idx, _ in enumerate(self.clients):
            if self.send_command(idx, command, *args):
                success = True
                
        if success:
            self.command_history.append(command_str)
        return success

    def command_input(self):
        """命令输入处理线程"""
        while self.running:
            try:
                cmd_input = input("\n> ")
                if not cmd_input.strip():
                    continue
                
                # 解析命令
                parts = cmd_input.split()
                if not parts:
                    continue
                
                # 处理特殊命令
                if parts[0] in self.special_commands:
                    self.special_commands[parts[0]](*parts[1:])
                    continue
                
                # 处理发送命令格式: [client_id] command args...
                client_id_match = re.match(r'^\[(\d+)\]\s+(.+)$', cmd_input)
                if client_id_match:
                    client_id = int(client_id_match.group(1))
                    rest_cmd = client_id_match.group(2).split()
                    if rest_cmd:
                        command, args = rest_cmd[0], rest_cmd[1:]
                        self.send_command(client_id, command, *args)
                    continue
                
                # 默认广播命令
                if parts:
                    command, args = parts[0], parts[1:]
                    self.broadcast_command(command, *args)
                    
            except KeyboardInterrupt:
                self.running = False
                break
            except Exception as e:
                print(f"[!] 命令处理出错: {e}")
                
            # 重新显示提示符
            if self.running and not self.in_ui_mode:
                print("> ", end='', flush=True)

    def show_help(self, *args):
        """显示帮助信息"""
        help_text = """
命令帮助:
  help              - 显示此帮助信息
  list              - 列出所有已连接的客户端
  exit              - 退出服务器
  history           - 显示命令历史
  
  [client_id] cmd   - 向特定客户端发送命令
  cmd args...       - 向所有客户端广播命令

示例Studio命令:
  restart_local_game         - 重启本地游戏
  release_mouse              - 释放鼠标捕获
  create_world path_to_config - 创建世界
  begin_performance_profile  - 开始性能分析
"""
        print(help_text)

    def list_clients(self, *args):
        """列出连接的客户端"""
        if not self.clients:
            print("[!] 没有客户端连接")
            return
            
        print("\n已连接的客户端:")
        for client in self.clients:
            print(f"  [{client['id']}] {client['address'][0]}:{client['address'][1]}")

    def show_history(self, *args):
        """显示命令历史"""
        if not self.command_history:
            print("[!] 没有命令历史")
            return
            
        print("\n命令历史:")
        for i, cmd in enumerate(self.command_history):
            print(f"  {i+1}. {cmd}")

    def exit_server(self, *args):
        """退出服务器"""
        print("[+] 正在关闭服务器...")
        self.running = False
        self.shutdown()
        sys.exit(0)

    def shutdown(self):
        """关闭服务器"""
        # 关闭所有客户端连接
        for client in self.clients:
            try:
                client['socket'].close()
            except:
                pass
        
        # 关闭服务器套接字
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
                
        print("[+] 服务器已关闭")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Minecraft Studio 调试日志服务器')
    parser.add_argument('-p', '--port', type=int, default=8000, 
                        help='服务器监听端口 (默认: 8000)')
    parser.add_argument('-a', '--address', default='0.0.0.0',
                        help='服务器监听地址 (默认: 0.0.0.0)')
    
    args = parser.parse_args()
    
    try:
        server = StudioLogServer(host=args.address, port=args.port)
        server.start()
    except KeyboardInterrupt:
        print("\n[+] 收到退出信号，正在关闭服务器...")
    except Exception as e:
        print(f"[!] 服务器运行出错: {e}")


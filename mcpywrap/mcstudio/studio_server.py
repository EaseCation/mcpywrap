#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import threading
import json
import time
import argparse
import sys
import re

class StudioLogServer:
    def __init__(self, host='0.0.0.0', port=8000):
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

    def start(self):
        """启动服务器"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.running = True
            print(f"[+] 服务器已启动，监听 {self.host}:{self.port}")
            
            # 启动命令输入线程
            cmd_thread = threading.Thread(target=self.command_input)
            cmd_thread.daemon = True
            cmd_thread.start()
            
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
                        print(f"\n[命令消息] 客户端 {client_id}:")
                        print(f"命令: {cmd_data.get('command')}")
                        print(f"内容: {json.dumps(cmd_data.get('msg'), indent=2, ensure_ascii=False)}")
                    except json.JSONDecodeError:
                        print(f"\n[!] 无法解析JSON: {data[1:-1]}")
                else:
                    # 普通日志消息
                    log_data = data.decode('utf-8', errors='replace')
                    print(f"\n[日志] 客户端 {client_id}: {log_data}", end='')
                
                # 让命令提示符重新出现
                print("\n> ", end='', flush=True)
                
        except ConnectionResetError:
            print(f"\n[!] 客户端 {client_id} 连接已重置")
        except Exception as e:
            print(f"\n[!] 处理客户端 {client_id} 时出错: {e}")
        finally:
            try:
                client_socket.close()
                self.clients.remove(client_info)
                print(f"\n[-] 客户端 {client_id} 已断开连接")
                print("> ", end='', flush=True)
            except:
                pass

    def send_command(self, client_id, command, *args):
        """向特定客户端发送命令"""
        if client_id >= len(self.clients):
            print(f"[!] 客户端ID {client_id} 不存在")
            return False
            
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
    parser = argparse.ArgumentParser(description='Minecraft Studio调试日志服务器')
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
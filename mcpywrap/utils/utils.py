# -*- coding: utf-8 -*-

"""
通用工具函数
"""
import subprocess
from pathlib import Path
import sys
import click

def validate_path(path_str):
    """验证路径是否有效"""
    path = Path(path_str).expanduser().resolve()
    return path.exists()

def ensure_dir(path_str):
    """确保目录存在，如果不存在则创建"""
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        path.mkdir(parents=True)
    return str(path)

def run_command(cmd, cwd=None, shell=False):
    """运行系统命令"""
    try:
        result = subprocess.run(
            cmd, 
            cwd=cwd, 
            shell=shell,
            check=True, 
            text=True, 
            capture_output=True
        )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr


class DynamicOutput:
    """动态输出类，用于覆盖终端中已经输出的内容"""
    
    def __init__(self, use_click=True, enabled=True):
        """
        初始化动态输出对象
        
        Args:
            use_click: 是否使用click库来输出（彩色支持）
            enabled: 是否启用动态输出，设为False则退化为普通输出
        """
        self.use_click = use_click
        self.enabled = enabled
        self.last_line_length = 0
        self.last_status = ""
        self.line_count = 0
        
    def update_status(self, message, color=None, bold=False):
        """
        更新当前行的状态信息
        
        Args:
            message: 要显示的消息
            color: 文字颜色
            bold: 是否加粗
        """
        if not self.enabled:
            self.print_msg(message, color, bold)
            return
            
        # 清除当前行
        sys.stdout.write('\r')
        sys.stdout.write(' ' * self.last_line_length)
        sys.stdout.write('\r')
        
        # 输出新内容
        if self.use_click and color:
            click.secho(message, fg=color, bold=bold, nl=False)
        else:
            sys.stdout.write(message)
            
        # 记录最新状态
        self.last_status = message
        self.last_line_length = len(message)
        sys.stdout.flush()
    
    def print_msg(self, message, color=None, bold=False):
        """
        打印一条新消息（不覆盖）
        
        Args:
            message: 要显示的消息
            color: 文字颜色
            bold: 是否加粗
        """
        # 如果有未完成的状态行，先换行
        if self.last_line_length > 0 and self.enabled:
            sys.stdout.write('\n')
            self.last_line_length = 0
        
        # 输出消息
        if self.use_click:
            click.secho(message, fg=color, bold=bold)
        else:
            print(message)
        
        self.line_count += 1
    
    def complete_status(self, success=True, end_message=None):
        """
        完成当前状态，将临时状态变为永久消息
        
        Args:
            success: 是否成功
            end_message: 结束消息，如果为None则使用最后的状态
        """
        message = end_message if end_message is not None else self.last_status
        color = "green" if success else "red"
        
        if not message:
            return
            
        if self.enabled and self.last_line_length > 0:
            # 覆盖最后一行
            self.print_msg(message, color)
        else:
            # 直接输出
            self.print_msg(message, color)
        
        # 重置状态
        self.last_line_length = 0
        self.last_status = ""
    
    def start_progress(self, message, color="cyan"):
        """
        开始一个进度显示
        
        Args:
            message: 进度消息前缀
            color: 文字颜色
        """
        self.update_status(f"{message}...", color)
        return self
    
    def progress_step(self, step_message, color="cyan"):
        """
        更新进度步骤
        
        Args:
            step_message: 步骤消息
            color: 文字颜色
        """
        self.update_status(f"{self.last_status[:-3]}: {step_message}...", color)
        return self
    
    def end_progress(self, success=True, message=None):
        """
        结束进度显示
        
        Args:
            success: 是否成功
            message: 完成消息，如果为None则使用默认消息
        """
        base_message = self.last_status[:-3] if self.last_status.endswith("...") else self.last_status
        
        if message is None:
            if success:
                message = f"{base_message}: ✓ 完成"
            else:
                message = f"{base_message}: ✗ 失败"
                
        self.complete_status(success, message)
        return self

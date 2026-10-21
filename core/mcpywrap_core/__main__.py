# -*- coding: utf-8 -*-
"""
mcpywrap 命令行工具的入口点
"""

from .cli import cli

def main():
    """主函数，作为 CLI 入口点"""
    import sys
    # Keep the caller's text encoding; unsupported symbols must not abort an operation.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='backslashreplace')
    cli()

if __name__ == "__main__":
    main()

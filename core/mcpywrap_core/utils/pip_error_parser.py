# -*- coding: utf-8 -*-

"""
pip安装错误解析工具 - 提供友好的中文错误信息
"""
import re
import click


def parse_pip_error(output):
    """解析pip错误输出，返回友好的中文错误信息
    
    Args:
        output: pip命令的标准错误输出或异常信息
        
    Returns:
        tuple: (是否为依赖错误, 友好的中文错误消息, 建议解决方案列表)
    """
    if not output:
        return False, "未知的安装错误", ["请检查项目配置文件是否正确"]
    
    output_str = str(output)
    
    # 解析缺少依赖的错误
    missing_dep_patterns = [
        r"ERROR: Could not find a version that satisfies the requirement (\S+)",
        r"ERROR: No matching distribution found for (\S+)"
    ]
    
    for pattern in missing_dep_patterns:
        match = re.search(pattern, output_str)
        if match:
            package_name = match.group(1)
            # 移除版本约束信息和来源信息，只保留包名
            package_name = re.sub(r'\s*\(.*?\)', '', package_name).strip()
            
            error_msg = f"❌ 缺少依赖包: {package_name}"
            suggestions = [
                f"检查依赖包名称 '{package_name}' 是否正确拼写",
                f"确认包 '{package_name}' 在PyPI上可用",
                f"检查项目的 pyproject.toml 配置中是否有拼写错误",
                f"手动安装依赖: pip install {package_name}",
                f"或使用 mcpy add {package_name} 命令添加依赖"
            ]
            return True, error_msg, suggestions
    
    # 解析版本冲突错误
    version_conflict_pattern = r"ERROR: .*has conflicting dependencies"
    if re.search(version_conflict_pattern, output_str):
        error_msg = "❌ 依赖版本冲突"
        suggestions = [
            "检查项目依赖的版本约束",
            "尝试更新依赖版本",
            "清理虚拟环境后重新安装"
        ]
        return True, error_msg, suggestions
    
    # 解析网络连接错误
    network_error_patterns = [
        r"ERROR: Could not install packages due to an OSError",
        r"ConnectTimeout",
        r"ConnectionError",
        r"URLError"
    ]
    
    for pattern in network_error_patterns:
        if re.search(pattern, output_str, re.IGNORECASE):
            error_msg = "❌ 网络连接错误"
            suggestions = [
                "检查网络连接是否正常",
                "尝试使用国内PyPI镜像源",
                "配置代理或VPN后重试"
            ]
            return True, error_msg, suggestions
    
    # 解析权限错误
    permission_patterns = [
        r"ERROR: .*Permission denied",
        r"PermissionError",
        r"Access is denied"
    ]
    
    for pattern in permission_patterns:
        if re.search(pattern, output_str, re.IGNORECASE):
            error_msg = "❌ 权限不足"
            suggestions = [
                "使用管理员权限运行命令",
                "检查文件系统权限设置",
                "尝试在虚拟环境中安装"
            ]
            return True, error_msg, suggestions
    
    # 解析构建错误
    build_error_patterns = [
        r"ERROR: Failed building wheel",
        r"error: Microsoft Visual C\+\+ \d+\.\d+ is required",
        r"Building wheel .* failed"
    ]
    
    for pattern in build_error_patterns:
        if re.search(pattern, output_str, re.IGNORECASE):
            error_msg = "❌ 包构建失败"
            suggestions = [
                "安装Microsoft Visual C++ Build Tools",
                "尝试安装预编译的wheel包",
                "检查Python开发环境配置"
            ]
            return True, error_msg, suggestions
    
    # 解析pyproject.toml配置错误
    config_error_patterns = [
        r"ERROR: .*pyproject.toml",
        r"Invalid configuration",
        r"ConfigError"
    ]
    
    for pattern in config_error_patterns:
        if re.search(pattern, output_str, re.IGNORECASE):
            error_msg = "❌ 项目配置文件错误"
            suggestions = [
                "检查pyproject.toml语法是否正确",
                "验证项目配置格式",
                "参考mcpywrap项目配置模板"
            ]
            return True, error_msg, suggestions
    
    # 默认通用错误处理
    return True, "❌ 安装过程中发生错误", ["请检查详细错误信息并手动解决"]


def display_pip_error(output, show_raw_output=False):
    """显示友好的pip错误信息
    
    Args:
        output: pip命令的错误输出
        show_raw_output: 是否显示原始错误输出
    """
    is_dependency_error, error_msg, suggestions = parse_pip_error(output)
    
    # 显示主要错误信息
    click.echo()
    click.echo(click.style("═" * 50, fg='red'))
    click.echo(click.style("🚫 依赖安装失败", fg='red', bold=True))
    click.echo(click.style("═" * 50, fg='red'))
    click.echo()
    click.echo(click.style(error_msg, fg='red', bold=True))
    
    # 显示建议解决方案
    if suggestions:
        click.echo()
        click.echo(click.style("💡 建议解决方案:", fg='yellow', bold=True))
        for i, suggestion in enumerate(suggestions, 1):
            click.echo(click.style(f"  {i}. {suggestion}", fg='yellow'))
    
    # 显示原始错误输出（可选）
    if show_raw_output and output:
        click.echo()
        click.echo(click.style("📋 详细错误信息:", fg='cyan', bold=True))
        click.echo(click.style("-" * 30, fg='cyan'))
        # 限制输出长度，避免过长的错误信息
        output_str = str(output)
        if len(output_str) > 1000:
            output_str = output_str[:1000] + "\n... (输出已截断)"
        click.echo(output_str)
    
    click.echo()
    click.echo(click.style("═" * 50, fg='red'))
    click.echo()


def suggest_common_fixes():
    """显示常见问题的通用解决建议"""
    click.echo(click.style("🔧 常见问题排查:", fg='magenta', bold=True))
    suggestions = [
        "确认所有依赖包名称拼写正确",
        "检查项目的pyproject.toml配置文件",
        "尝试在干净的虚拟环境中安装",
        "更新pip到最新版本: python -m pip install --upgrade pip",
        "清理pip缓存: python -m pip cache purge"
    ]
    
    for i, suggestion in enumerate(suggestions, 1):
        click.echo(click.style(f"  {i}. {suggestion}", fg='magenta'))
    click.echo()
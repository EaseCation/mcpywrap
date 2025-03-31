# -*- coding: utf-8 -*-

"""
安装网易ModSDK命令模块
"""
import click
from ..minecraft.netease_modsdk import get_available_versions, download_and_install_package

@click.command()
@click.option('--list', is_flag=True, help='列出所有可用版本')
@click.option('--version', type=str, help='指定要安装的版本')
def modsdk_cmd(list, version):
    """管理网易我的世界ModSDK"""
    
    if list:
        # 获取版本列表
        versions = get_available_versions()
        if not versions:
            click.echo(click.style('❌ 无法获取版本信息或没有可用版本', fg='red', bold=True))
            return
        
        click.echo(click.style('\n📋 mc-netease-sdk 可用版本:', fg='bright_green', bold=True))
        click.echo(click.style('='*40, fg='blue'))
        for i, ver in enumerate(versions):
            click.echo(click.style(f"{i+1:3}. {ver}", fg='cyan'))
            
        click.echo(click.style(f"\n🆕 最新版本: {versions[-1] if versions else '未知'}", fg='yellow', bold=True))
        click.echo(click.style('='*40, fg='blue'))
        return
    
    # 如果没有指定--list选项，则进入安装流程
    click.echo(click.style('🔍 正在准备安装网易ModSDK...', fg='bright_blue', bold=True))
    
    # 如果未指定版本，提示用户选择版本或使用最新版
    if not version:
        versions = get_available_versions()
        if not versions:
            click.echo(click.style('❌ 无法获取版本信息，安装失败', fg='red', bold=True))
            return
            
        click.echo(click.style('\n📋 可用版本:', fg='green'))
        for i, ver in enumerate(versions):
            click.echo(click.style(f"{i+1:3}. {ver}", fg='cyan'))
        
        if click.confirm(click.style('❓ 是否安装最新版本？', fg='yellow'), default=True):
            version = versions[-1]
        else:
            version_index = click.prompt(
                click.style('🔢 请输入版本序号', fg='yellow'),
                type=click.IntRange(1, len(versions)),
                default=len(versions)
            )
            version = versions[version_index - 1]
    
    # 显示安装信息
    click.echo(click.style(f'📦 正在安装 网易ModSDK {version}...', fg='bright_blue'))
    click.echo(click.style('⚙️ 将忽略Python版本兼容性进行强制安装', fg='yellow'))
    
    # 调用安装函数（始终强制安装）
    success = download_and_install_package(version, force=True)
    
    if success:
        click.echo(click.style('✅ 网易ModSDK安装成功！', fg='green', bold=True))
    else:
        click.echo(click.style('❌ 网易ModSDK安装失败，请检查网络连接或尝试其他版本', fg='red', bold=True))

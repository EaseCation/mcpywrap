# -*- coding: utf-8 -*-

import click
import os
from ..config import update_config, config_exists, read_config, get_project_type
from .init_cmd import init as init_project
from ..minecraft.netease_modsdk import check_installed_modsdk, get_available_versions, download_and_install_package
from ..utils.project_setup import find_and_configure_behavior_pack, install_project_dev_mode
from ..utils.print_guide import print_guide

base_dir = os.getcwd()


@click.command()
def default_cmd():
    # 判断当前是否已安装modsdk
    installed_modsdk = check_installed_modsdk()
    if not installed_modsdk:
        # 自动安装
        try_install_modsdk()

    # 判断当前目录是否存在配置文件
    if not config_exists():
        # 执行init指令
        init_project()
    else:
        click.echo(click.style('🔄 正在刷新项目...', fg='blue'))

        # 加载现有配置
        config = read_config()
        project_type = get_project_type()

        if project_type == 'addon':
            # 查找行为包并更新配置
            behavior_pack_dir, _ = find_and_configure_behavior_pack(base_dir, config)
            
            if not behavior_pack_dir:
                click.echo(click.style('❌ 未找到行为包目录，请手动配置', fg='red'))
                return
        
        # 更新配置文件
        update_config(config)
        click.echo(click.style('✅ 配置文件已更新', fg='green'))
        
        click.echo(click.style('🔄 正在安装到包管理...', fg='blue'))
        # 执行pip安装
        if install_project_dev_mode():
            click.echo(click.style('🚀 项目检查和安装完成！', fg='bright_green', bold=True))
        else:
            click.echo(click.style('❌ 安装失败，请检查包管理器配置', fg='red', bold=True))
        
        print_guide()

def try_install_modsdk():
    # 如果未指定版本，提示用户选择版本或使用最新版
    versions = get_available_versions()
    if not versions:
        click.echo(click.style('❌ 无法获取版本信息，跳过安装modsdk补全库', fg='red', bold=True))
        return
    
    version = versions[-1]
    
    # 显示安装信息
    click.echo(click.style(f'📦 正在安装 网易ModSDK {version}...', fg='bright_blue'))
    click.echo(click.style('⚙️ 将忽略Python版本兼容性进行强制安装', fg='yellow'))
    
    # 调用安装函数（始终强制安装）
    success = download_and_install_package(version, force=True)
    
    if success:
        click.echo(click.style('✅ 网易ModSDK安装成功！', fg='green', bold=True))
    else:
        click.echo(click.style('❌ 网易ModSDK安装失败，请检查网络连接或尝试其他版本', fg='red', bold=True))
# -*- coding: utf-8 -*-

import os
import sys
import json
import shutil
import tempfile
import subprocess
import urllib.request
from typing import List, Optional, Dict, Any, Tuple
import zipfile
import tarfile
import logging
import click

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 包名称常量
PACKAGE_NAME = "mc-netease-sdk"
PYPI_BASE_URL = "https://pypi.org/pypi"

def check_installed_modsdk():
    """
    检查是否已经安装了 modsdk 包。
    如果安装了，则返回已安装的版本号；否则返回 False。
    """
    try:
        # 优先使用 Python 3.8 及以上版本的 importlib.metadata
        from importlib.metadata import version, PackageNotFoundError
        return version(PACKAGE_NAME)
    except ImportError:
        # 如果无法使用 importlib.metadata，则使用 pkg_resources
        try:
            import pkg_resources
            return pkg_resources.get_distribution(PACKAGE_NAME).version
        except pkg_resources.DistributionNotFound:
            return False
    except PackageNotFoundError:
        return False

def get_available_versions() -> List[str]:
    """
    从PyPI API获取mc-netease-sdk所有可用版本
    
    Returns:
        List[str]: 可用版本列表（按版本号排序）
    """
    try:
        url = f"{PYPI_BASE_URL}/{PACKAGE_NAME}/json"
        logger.info(f"正在从 {url} 获取包信息...")
        
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.status != 200:
                logger.error(f"API请求失败: HTTP {response.status}")
                return []
            
            data = json.loads(response.read().decode())
            versions = list(data.get("releases", {}).keys())
            # 按版本号排序（使用PyPI返回的排序规则）
            versions.sort(key=lambda v: data["releases"][v][0]["upload_time_iso_8601"] if data["releases"][v] else "")
            
            logger.info(f"找到 {len(versions)} 个可用版本")
            return versions
    
    except urllib.error.URLError as e:
        logger.error(f"网络错误: {e}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"JSON解析错误: {e}")
        return []
    except Exception as e:
        logger.error(f"获取版本信息时发生错误: {e}")
        return []

def print_versions():
    """打印所有可用版本（使用click格式化输出）"""
    versions = get_available_versions()
    if not versions:
        click.echo(click.style('❌ 无法获取版本信息或没有可用版本', fg='red', bold=True))
        return
    
    click.echo(click.style(f'\n📋 {PACKAGE_NAME} 可用版本:', fg='bright_green', bold=True))
    click.echo(click.style('='*40, fg='blue'))
    for i, version in enumerate(versions):
        click.echo(click.style(f"{i+1:3}. {version}", fg='cyan'))
    click.echo(click.style(f"\n🆕 最新版本: {versions[-1] if versions else '未知'}", fg='yellow', bold=True))
    click.echo(click.style('='*40, fg='blue'))

def download_and_install_package(version: Optional[str] = None, force: bool = True) -> bool:
    """
    下载并安装指定版本的mc-netease-sdk包（不指定则安装最新版）
    
    Args:
        version (Optional[str]): 要安装的版本，如不指定则选择最新版本
        force (bool): 是否强制安装，忽略Python版本不兼容警告，默认为True
        
    Returns:
        bool: 安装成功返回True，否则返回False
    """
    try:
        versions = get_available_versions()
        if not versions:
            click.echo(click.style('❌ 没有可用版本，无法安装', fg='red', bold=True))
            return False
        
        # 如果未指定版本，使用最新版本
        if version is None:
            version = versions[-1]
            click.echo(click.style(f'ℹ️ 未指定版本，将安装最新版本: {version}', fg='blue'))
        elif version not in versions:
            click.echo(click.style(f'❌ 版本 {version} 不存在。', fg='red'))
            click.echo(click.style('可用版本:', fg='yellow'))
            for i, ver in enumerate(versions[-5:]):  # 只显示最新的5个版本
                click.echo(click.style(f" - {ver}", fg='cyan'))
            return False
        
        # 获取该版本的详细信息
        url = f"{PYPI_BASE_URL}/{PACKAGE_NAME}/{version}/json"
        click.echo(click.style(f'🔍 获取版本 {version} 的下载信息...', fg='bright_blue'))
        
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.status != 200:
                click.echo(click.style(f'❌ API请求失败: HTTP {response.status}', fg='red'))
                return False
            
            data = json.loads(response.read().decode())
            
            # 查找适合安装的包（优先使用wheel，其次是sdist）
            urls = data.get("urls", [])
            wheel_url = next((item["url"] for item in urls if item["packagetype"] == "bdist_wheel"), None)
            sdist_url = next((item["url"] for item in urls if item["packagetype"] == "sdist"), None)
            
            download_url = wheel_url or sdist_url
            if not download_url:
                click.echo(click.style(f'❌ 版本 {version} 没有可用的下载链接', fg='red'))
                return False
            
            click.echo(click.style(f'✅ 找到下载链接', fg='green'))
            
            # 创建临时目录
            with tempfile.TemporaryDirectory() as temp_dir:
                # 下载包
                package_path = os.path.join(temp_dir, os.path.basename(download_url))
                click.echo(click.style('📥 下载中...', fg='bright_blue'))
                
                with urllib.request.urlopen(download_url, timeout=60) as response, open(package_path, 'wb') as out_file:
                    shutil.copyfileobj(response, out_file)
                
                click.echo(click.style('✅ 下载完成', fg='green'))
                
                # 安装包
                click.echo(click.style(f'🔧 正在安装 {PACKAGE_NAME} {version}...', fg='bright_blue'))
                
                # 添加强制安装选项
                cmd = [sys.executable, "-m", "pip", "install", "--no-input", "--force-reinstall", "--no-deps"]
                
                # 强制忽略Python版本兼容性检查
                cmd.append("--ignore-requires-python")
                
                cmd.append(package_path)
                logger.debug(f"执行命令: {' '.join(cmd)}")
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode == 0:
                    click.echo(click.style(f'🎉 {PACKAGE_NAME} {version} 安装成功!', fg='green', bold=True))
                    return True
                else:
                    click.echo(click.style(f'⚠️ 安装失败: {result.stderr}', fg='yellow'))
                    # 如果还是失败，尝试解包wheel文件并手动安装
                    if package_path.endswith('.whl') and os.path.exists(package_path):
                        click.echo(click.style('🔄 尝试手动解包wheel文件进行安装...', fg='yellow'))
                        try:
                            return _manually_install_wheel(package_path, temp_dir)
                        except Exception as e:
                            click.echo(click.style(f'❌ 手动安装失败: {str(e)}', fg='red'))
                    return False
    
    except Exception as e:
        click.echo(click.style(f'❌ 下载安装过程中发生错误: {e}', fg='red'))
        return False

def _manually_install_wheel(wheel_path: str, extract_dir: str) -> bool:
    """
    手动解包并安装wheel文件（用于pip无法直接安装的情况）
    
    Args:
        wheel_path: wheel文件路径
        extract_dir: 解压目录
        
    Returns:
        bool: 安装成功返回True，否则返回False
    """
    try:
        # 解压wheel文件（本质上是zip文件）
        with zipfile.ZipFile(wheel_path, 'r') as zip_ref:
            wheel_extract_dir = os.path.join(extract_dir, "wheel_extract")
            os.makedirs(wheel_extract_dir, exist_ok=True)
            zip_ref.extractall(wheel_extract_dir)
        
        click.echo(click.style(f'📂 已解压wheel文件', fg='blue'))
        
        # 查找并复制包目录到site-packages
        import site
        site_packages = site.getsitepackages()[0]
        
        # 寻找包主目录
        package_dirs = [d for d in os.listdir(wheel_extract_dir) 
                      if os.path.isdir(os.path.join(wheel_extract_dir, d)) and 
                         d.endswith(".dist-info") == False]
        
        if not package_dirs:
            click.echo(click.style('❌ 无法在wheel文件中找到包目录', fg='red'))
            return False
        
        # 复制所有非dist-info目录到site-packages
        for dir_name in package_dirs:
            src_dir = os.path.join(wheel_extract_dir, dir_name)
            dst_dir = os.path.join(site_packages, dir_name)
            
            if os.path.exists(dst_dir):
                click.echo(click.style(f'🔄 删除已存在的包目录', fg='yellow'))
                shutil.rmtree(dst_dir)
                
            click.echo(click.style(f'📋 复制包文件到Python环境', fg='blue'))
            shutil.copytree(src_dir, dst_dir)
        
        # 也复制.dist-info目录以保持pip记录完整
        dist_info_dirs = [d for d in os.listdir(wheel_extract_dir) if d.endswith(".dist-info")]
        for dir_name in dist_info_dirs:
            src_dir = os.path.join(wheel_extract_dir, dir_name)
            dst_dir = os.path.join(site_packages, dir_name)
            
            if os.path.exists(dst_dir):
                shutil.rmtree(dst_dir)
                
            shutil.copytree(src_dir, dst_dir)
        
        click.echo(click.style('✅ 手动安装完成', fg='green', bold=True))
        return True
        
    except Exception as e:
        click.echo(click.style(f'❌ 手动安装过程中发生错误: {str(e)}', fg='red'))
        return False

def main():
    """主函数，用于命令行调用"""
    import argparse
    
    parser = argparse.ArgumentParser(description=f'管理 {PACKAGE_NAME} 包')
    parser.add_argument('--list', action='store_true', help='列出所有可用版本')
    parser.add_argument('--install', action='store_true', help='安装包')
    parser.add_argument('--version', type=str, help='指定要安装的版本')
    
    args = parser.parse_args()
    
    if args.list or (not args.list and not args.install):
        print_versions()
    
    if args.install:
        # 始终强制安装
        success = download_and_install_package(args.version, force=True)
        if not success:
            sys.exit(1)

if __name__ == "__main__":
    main()

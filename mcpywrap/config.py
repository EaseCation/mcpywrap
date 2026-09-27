# -*- coding: utf-8 -*-

"""
处理 mcpywrap 配置文件的模块
"""
import os
import tomli
import tomli_w
import click
from .command_context import project_dir

CONFIG_FILE = 'pyproject.toml'


def get_config_path() -> str:
    """获取配置文件路径"""
    return os.path.join(str(project_dir()), CONFIG_FILE)

def config_exists() -> bool:
    """检查配置文件是否存在"""
    return os.path.exists(get_config_path())

def read_config(config_path=None) -> dict:
    """读取配置文件"""
    if config_path is None:
        config_path = get_config_path()
        
    if not os.path.exists(config_path):
        return {}
    
    with open(config_path, 'rb') as f:
        try:
            config = tomli.load(f)
            # 确保mcpywrap工具配置部分存在
            if 'tool' not in config:
                config['tool'] = {}
            if 'mcpywrap' not in config['tool']:
                config['tool']['mcpywrap'] = {}
            
            # 确保project部分存在
            if 'project' not in config:
                config['project'] = {}
            
            return config
        except tomli.TOMLDecodeError:
            click.echo(click.style(f"❌ {config_path} 格式错误", fg='red', bold=True))
            return {}
        
def check_has_mcpywrap_config(config_path=None) -> bool:
    """检查配置文件是否包含mcpywrap配置"""
    if config_path is None:
        config_path = get_config_path()
        
    if not os.path.exists(config_path):
        return False
    
    with open(config_path, 'rb') as f:
        try:
            config = tomli.load(f)
            return 'tool' in config and 'mcpywrap' in config['tool']
        except tomli.TOMLDecodeError:
            click.echo(click.style(f"❌ {config_path} 格式错误", fg='red', bold=True))
            return False

def write_config(config_data):
    """写入配置文件"""
    with open(get_config_path(), 'wb') as f:
        tomli_w.dump(config_data, f)

def update_config(update_dict):
    """更新配置文件"""
    config = read_config()
    # 递归更新字典
    _deep_update(config, update_dict)
    write_config(config)
    return config

def _deep_update(original, update):
    """递归更新字典"""
    for key, value in update.items():
        if isinstance(value, dict) and key in original and isinstance(original[key], dict):
            _deep_update(original[key], value)
        else:
            original[key] = value

def get_project_name() -> str:
    """获取项目名称"""
    config = read_config()
    return config.get('project', {}).get('name', 'project')

def get_project_version() -> str:
    """获取项目版本"""
    config = read_config()
    return config.get('project', {}).get('version', '0.1.0')

def get_mcpywrap_config():
    """获取mcpywrap特定的配置"""
    config = read_config()
    return config.get('tool', {}).get('mcpywrap', {})


def get_project_type():
    """获取项目类型，可能为：addon, map, apollo"""
    mcpywrap_config = get_mcpywrap_config()
    return mcpywrap_config.get('project_type', 'addon')

def get_project_dependencies() -> list[str]:
    """获取项目依赖列表"""
    config = read_config()
    return config.get('project', {}).get('dependencies', [])

def add_dependency(package):
    """添加依赖到配置"""
    config = read_config()
    if 'dependencies' not in config.get('project', {}):
        if 'project' not in config:
            config['project'] = {}
        config['project']['dependencies'] = []
    
    if package not in config['project']['dependencies']:
        config['project']['dependencies'].append(package)
        write_config(config)
        return True
    return False

def remove_dependency(package_name):
    """从项目配置中删除依赖
    
    Args:
        package_name: 要删除的依赖名称
        
    Returns:
        bool: 删除是否成功
    """
    try:
        config = read_config()
        if 'project' in config and 'dependencies' in config['project'] and package_name in config['project']['dependencies']:
            config['project']['dependencies'].remove(package_name)
            write_config(config)
            return True
        return False
    except Exception as e:
        click.echo(f"❌ 删除依赖失败: {e}", err=True)
        return False

def scan_behavior_packs(base_dir=None):
    """扫描 behavior_packs 目录，返回所有行为包目录列表
    
    Args:
        base_dir: 项目根目录，默认为当前目录
        
    Returns:
        list: 行为包目录名称列表
    """
    if base_dir is None:
        base_dir = str(project_dir())
    
    behavior_packs_dir = os.path.join(base_dir, "behavior_packs")
    
    if not os.path.exists(behavior_packs_dir):
        return []
    
    packs = []
    for item in os.listdir(behavior_packs_dir):
        pack_path = os.path.join(behavior_packs_dir, item)
        if os.path.isdir(pack_path):
            packs.append(item)
    
    return sorted(packs)

def update_map_setuptools_config(interactive=False):
    """只同步自动生成的 behavior_packs 项，保留用户其他包声明。"""
    if get_project_type() != 'map':
        return False
    config = read_config()
    settings = config.setdefault('tool', {}).setdefault('setuptools', {})
    existing = settings.get('packages', [])
    # 用户显式使用 find 配置时，由 setuptools 自行发现，不替换其规则。
    if isinstance(existing, dict):
        return True
    names = ['behavior_packs.' + name for name in scan_behavior_packs()]
    settings['packages'] = [name for name in existing if not name.startswith('behavior_packs.')] + names
    directories = settings.setdefault('package-dir', {})
    for name in list(directories):
        if name.startswith('behavior_packs.'):
            del directories[name]
    directories.update({name: name.replace('.', '/') for name in names})
    write_config(config)
    return True


def check_map_setuptools_sync():
    """检查 map 项目的 setuptools 配置是否与实际的 behavior_packs 同步
    
    Returns:
        tuple: (是否同步, 当前包列表, 配置中的包列表)
    """
    project_type = get_project_type()
    if project_type != "map":
        return True, [], []
    
    # 获取实际的包列表
    actual_packs = scan_behavior_packs()
    
    # 获取配置中的包列表
    config = read_config()
    setuptools_config = config.get('tool', {}).get('setuptools', {})
    configured_packages = setuptools_config.get('packages', [])
    
    # 从配置包名中提取行为包名
    configured_packs = []
    for pkg in configured_packages:
        if pkg.startswith('behavior_packs.'):
            pack_name = pkg[len('behavior_packs.'):]
            configured_packs.append(pack_name)
    
    configured_packs.sort()
    
    # 比较是否同步
    is_sync = actual_packs == configured_packs
    
    return is_sync, actual_packs, configured_packs

def ensure_map_setuptools_sync(interactive=True):
    """确保 map 项目的 setuptools 配置与实际情况同步
    
    Args:
        interactive: 是否在不同步时询问用户确认
        
    Returns:
        bool: 是否成功同步或用户取消操作
    """
    is_sync, actual_packs, configured_packs = check_map_setuptools_sync()
    
    if is_sync:
        return True
    
    if not interactive:
        # 非交互模式直接更新
        return update_map_setuptools_config(interactive=False)
    
    # 显示差异信息
    click.echo(click.style("🔍 检测到 behavior_packs 配置不同步:", fg="yellow", bold=True))
    click.echo(f"  实际行为包: {actual_packs}")
    click.echo(f"  配置中的包: {configured_packs}")
    
    if click.confirm(
        click.style("❓ 是否自动更新 setuptools 配置以同步 behavior_packs？", fg="magenta"),
        default=True
    ):
        return update_map_setuptools_config(interactive=True)
    else:
        click.echo(click.style("⚠️  配置未更新，IDE 代码提示可能不准确", fg="yellow"))
        return False

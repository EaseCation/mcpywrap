# -*- coding: utf-8 -*-

"""
处理 mcpywrap 配置文件的模块
"""
import os
import tomli
import tomli_w
import click

CONFIG_FILE = 'pyproject.toml'

def get_config_path() -> str:
    """获取配置文件路径"""
    return os.path.join(os.getcwd(), CONFIG_FILE)

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

def get_mcpywrap_config():
    """获取mcpywrap特定的配置"""
    config = read_config()
    return config.get('tool', {}).get('mcpywrap', {})

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
        if 'dependencies' in config and package_name in config['dependencies']:
            config['dependencies'].remove(package_name)
            write_config(config)
            return True
        return False
    except Exception:
        return False

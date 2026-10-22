"""向导与脚本共用的初始化服务；不安装依赖，不打开窗口。"""
import re
from pathlib import Path

from packaging.version import Version

from .command_context import project_scope
from .dependencies import write_project, addon_directories, DependencyError
from .minecraft.addons import setup_minecraft_addon, is_minecraft_addon_project, find_behavior_pack_dir
from .minecraft.map import setup_minecraft_map, is_minecraft_map_project


def detect_project(directory):
    if is_minecraft_map_project(str(directory)):
        return 'map'
    try:
        addon_directories(directory)
        return 'addon'
    except DependencyError:
        return None


def initialize_project(directory, name=None, project_type=None, version='0.1.0', target_dir='./build',
                       description='', author=''):
    root = Path(directory).resolve()
    if (root / 'pyproject.toml').exists():
        raise ValueError('pyproject.toml 已存在；初始化不会覆盖配置')
    name = name or re.sub(r'[^A-Za-z0-9_.-]', '-', root.name).strip('-')
    if not name or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
        raise ValueError('请通过 --name 指定有效的 Python 项目名称')
    parsed = Version(version)
    detected = detect_project(root)
    if detected and project_type and project_type != detected:
        raise ValueError(f'检测到 {detected} 项目，与 --type 不一致')
    project_type = project_type or detected
    if project_type not in ('addon', 'map'):
        raise ValueError('无法识别项目类型，请指定 --type addon 或 --type map')
    if not detected:
        # 不向未知现有目录写入模板，防止覆盖用户资源。
        occupied = [p.name for p in root.iterdir() if p.name not in ('.git', 'README.md', '.gitignore')]
        if occupied:
            raise ValueError('无法识别非空目录结构；请整理为 Addon/Map，或在空目录初始化')
        if project_type == 'addon':
            numbers = list(parsed.release[:3])
            numbers += [0] * (3 - len(numbers))
            setup_minecraft_addon(str(root), name, description, '.'.join(map(str, numbers)))
        else:
            setup_minecraft_map(str(root), name, description)
    elif project_type == 'addon':
        addon_directories(root)
    config = {
        'build-system': {'requires': ['setuptools>=77', 'wheel'], 'build-backend': 'setuptools.build_meta'},
        'project': {'name': name, 'version': version, 'description': description,
                    'requires-python': '>=3.9', 'dependencies': [], 'readme': 'README.md'},
        'tool': {'mcpywrap': {'project_type': project_type, 'target_dir': target_dir,
                             'local_dependencies': []}},
    }
    if author:
        config['project']['authors'] = [{'name': author}]
    behavior = find_behavior_pack_dir(str(root)) if project_type == 'addon' else None
    if behavior:
        from .utils.project_setup import update_behavior_pack_config
        update_behavior_pack_config(config, str(root), behavior, target_dir)
    elif project_type == 'addon':
        config['tool']['setuptools'] = {'packages': []}
    if not (root / 'README.md').exists():
        (root / 'README.md').write_text(f'# {name}\n', encoding='utf-8')
    write_project(root, config)
    if project_type == 'map':
        from .config import update_map_setuptools_config
        with project_scope(root):
            update_map_setuptools_config(interactive=False)
    return {'project': str(root), 'name': name, 'type': project_type, 'version': version}

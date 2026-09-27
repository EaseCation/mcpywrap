"""薄预设适配器：数据转标准Git声明，安装由通用项目依赖服务完成。"""
import keyword
from pathlib import Path
from .dependencies import DependencyError, addon_directories
from .git_projects import declarations
from .framework_presets import FRAMEWORK_PRESETS
from .project_dependencies import GitDependencyService


def script_directories(root):
    behavior = addon_directories(root).get('behavior')
    if not behavior:
        raise DependencyError('框架需要包含 manifest 的行为包')
    return sorted(p.name for p in Path(behavior).iterdir() if p.is_dir() and (p / 'modMain.py').is_file())


def framework_preview(root, preset_name, script_dir=None, source=None):
    if preset_name not in FRAMEWORK_PRESETS:
        raise DependencyError('未知框架预设: ' + preset_name)
    preset = FRAMEWORK_PRESETS[preset_name]
    entries = declarations(root)
    from .code_libraries import declarations as legacy_declarations
    legacy = legacy_declarations(root)
    if not script_dir:
        candidates = script_directories(root)
        if len(candidates) > 1:
            raise DependencyError('存在多个 Mod，请用 --script-dir 选择: ' + ', '.join(candidates))
        script_dir = candidates[0] if candidates else 'MyScript'
    if not script_dir.isascii() or not script_dir.isidentifier() or keyword.iskeyword(script_dir):
        raise DependencyError('脚本目录必须是有效 ASCII Python 标识符')
    if source is not None and source not in preset['sources']:
        raise DependencyError('未知来源: ' + source)
    behavior = addon_directories(root).get('behavior')
    if not behavior:
        raise DependencyError('框架入口需要包含manifest的行为包')
    target = Path(behavior) / script_dir
    if target.is_symlink() or (hasattr(target, 'is_junction') and target.is_junction()) or (target.exists() and not target.is_dir()):
        raise DependencyError('脚本目录必须为普通目录')
    mount = script_dir + '/' + preset['folder']
    previous = next((e for e in entries + legacy if e.get('target', '').lower() == mount.lower()), None)
    if previous and (previous['git'] not in preset['sources'].values() or previous.get('subdir', '.') != preset['subdir']):
        raise DependencyError('安装位置已声明其他项目')
    return {'preset': preset_name, 'title': preset['title'], 'script_dir': script_dir, 'script_path': str(target),
            'legacy': previous in legacy if previous else False,
            'original_source': previous['git'] if previous else None,
            'new_script': not target.exists(), 'target': mount,
            'dependency': previous['name'] if previous else preset_name + '-' + script_dir.lower(),
            'source': preset['sources'][source] if source else previous['git'] if previous else preset['sources'][preset['default_source']],
            'rev': previous['rev'] if previous else preset['rev'],
            'version': preset['version'] if not previous or previous['rev'] == preset['rev'] else '自定义固定提交'}


def add_framework(root, preset_name, script_dir=None, source=None, require_new=False):
    preview = framework_preview(root, preset_name, script_dir, source)
    if require_new and not preview['new_script']:
        raise DependencyError('脚本目录已存在，不覆盖: ' + preview['script_path'])
    preset = FRAMEWORK_PRESETS[preset_name]
    if preview['legacy']:
        # 兼容叶子库声明：恢复而不隐式迁移格式或制造同目标的重复Git节点。
        from .code_libraries import sync_libraries
        if preview['new_script'] or preview['source'] != preview['original_source']:
            raise DependencyError('此目标使用既有code_libraries声明；请用mcpy sync恢复，格式迁移请显式修改声明并保留业务入口')
        sync_libraries(root)
        return {**{key: preview[key] for key in ('preset', 'title', 'script_dir', 'script_path', 'version', 'dependency', 'source', 'rev', 'target')},
                'classification': 'code_library', 'synced': True, 'changed': False, 'new_script': False,
                'warnings': ['已恢复兼容代码库声明；已有入口与配置格式保持不变。']}
    scaffold = None
    if preview['new_script']:
        scaffold = {'directory': preview['script_dir'], 'files': {
            name: text.replace('{script_dir}', preview['script_dir']) for name, text in preset['files'].items()}}
    result = GitDependencyService(root).add(preview['source'], preview['rev'], preview['dependency'],
        preset['subdir'], preset['kind'], preview['target'], scaffold)
    result.update({key: preview[key] for key in ('preset', 'title', 'script_dir', 'script_path', 'version')})
    if not preview['new_script']:
        result['warnings'].append('已有脚本保留；请按所选框架接入入口，向导不会改写业务代码。')
    return result

"""完整构建和增量更新共用相同的文件合并规则。"""
import os
import shutil
from pathlib import Path

from ..dependencies import DependencyError, canonical_path
from .AddonsPack import MANIFEST_FILES
from .file_merge import try_merge_file
from ..code_libraries import library_source

MERGED_JSON = {'blocks.json', 'terrain_texture.json', 'item_texture.json', 'sounds.json',
               'sound_definitions.json', 'animations.json', 'animation_controllers.json',
               'entity_models.json', 'render_controllers.json', 'materials.json',
               'attachables.json', 'particle_effects.json', '_ui_defs.json'}


def is_within(path, parent):
    try:
        return os.path.commonpath([canonical_path(path), canonical_path(parent)]) == canonical_path(parent)
    except ValueError:
        return False


def validate_target(target, root, packs):
    if not target:
        raise DependencyError('未指定构建输出目录')
    # 根目录下的独立 build 允许存在，但不能覆盖任意源包或依赖项目。
    if is_within(root, target):
        raise DependencyError(f'构建输出会覆盖主项目: {target}')
    for pack in packs:
        protected = [pack.path] if not pack.is_origin else [pack.behavior_pack_dir, pack.resource_pack_dir]
        for source in filter(None, protected):
            if is_within(source, target) or is_within(target, source):
                raise DependencyError(f'构建输出与源目录重叠: {target} <-> {source}')


def pack_files(pack, kind):
    if kind == 'behavior':
        for library in getattr(pack, 'code_libraries', []):
            for file in sorted(library['source'].rglob('*')):
                if file.is_file():
                    yield library['target'] + '/' + file.relative_to(library['source']).as_posix()
    folder = getattr(pack, kind + '_pack_dir')
    if not folder or not os.path.isdir(folder):
        return
    for current, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not pack.should_exclude(os.path.join(current, d)))
        for name in sorted(files):
            source = Path(current) / name
            if name in MANIFEST_FILES or not pack.should_exclude(str(source)):
                yield source.relative_to(folder).as_posix()


def rebuild_file(packs, kind, relative, destination):
    """按依赖优先序重建单个产物；所有来源删除后同步删除产物。"""
    destination = Path(destination)
    if destination.is_file() or destination.is_symlink():
        destination.unlink()
    sources = []
    for pack in packs:
        folder = getattr(pack, kind + '_pack_dir')
        if not folder:
            continue
        mounted = library_source(pack, kind, relative)
        source = mounted or Path(folder) / relative
        if source.is_file() and (mounted or source.name in MANIFEST_FILES or not pack.should_exclude(str(source))):
            sources.append((pack, source))
    if relative in MANIFEST_FILES:
        # 优先保留主包 manifest；主包缺少该包类型时使用最后一个依赖的 manifest。
        manifest_owner = next((pack for pack in reversed(packs)
                               if getattr(pack, kind + '_pack_dir') and any(
                                   (Path(getattr(pack, kind + '_pack_dir')) / name).is_file()
                                   for name in MANIFEST_FILES)), None)
        sources = [(pack, source) for pack, source in sources if pack is manifest_owner]
    for pack, source in sources:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and (source.name in MERGED_JSON or source.suffix == '.lang'):
            success, error = try_merge_file(str(source), str(destination))
            if not success:
                raise DependencyError(error)
        elif source.suffix == '.py':
            pack._copy_with_encoding_check(str(source), str(destination))
        else:
            shutil.copy2(source, destination)


def assemble_addon(packs, target_pack):
    for kind in ('behavior', 'resource'):
        target = getattr(target_pack, kind + '_pack_dir')
        paths = {relative for pack in packs for relative in pack_files(pack, kind)}
        for relative in sorted(paths):
            rebuild_file(packs, kind, relative, Path(target) / relative)

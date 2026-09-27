"""先校验依赖与输出位置，再组装项目。"""
import os
import shutil
import tempfile
from pathlib import Path
from ..command_context import report_dependency_warnings
from ..dependencies import DependencyError, DependencyService, addon_directories, read_project
from .AddonsPack import AddonsPack
from .MapPack import MapPack
from .assembly import assemble_addon, validate_target, is_within, pack_files, rebuild_file
from ..code_libraries import prepare_libraries


def _clear_directory(directory):
    for item in Path(directory).iterdir():
        if item.is_symlink():
            item.unlink()
        elif hasattr(item, 'is_junction') and item.is_junction():
            os.rmdir(item)
        elif item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


class AddonProjectBuilder:
    def __init__(self, source_dir, target_dir, include_dependencies=True):
        self.source_dir = str(Path(source_dir).resolve())
        self.target_dir = str(Path(target_dir).resolve()) if target_dir else None
        self.config = read_project(self.source_dir)
        self.project_name = self.config.get('project', {}).get('name', 'current_project')
        self.include_dependencies = include_dependencies

    def initialize(self):
        addon_directories(self.source_dir)
        config = None
        if not self.include_dependencies:
            import copy
            config = copy.deepcopy(self.config)
            config.setdefault('project', {})['dependencies'] = []
            config.setdefault('tool', {}).setdefault('mcpywrap', {})['local_dependencies'] = []
            config['tool']['mcpywrap']['git_dependencies'] = []
        self.dependency_manager = DependencyService(self.source_dir).resolve(config)
        report_dependency_warnings(self.dependency_manager)
        self.dependency_tree = self.dependency_manager.root_node
        self.origin_addon = self.dependency_tree.addon_pack
        self.packs = list(self.dependency_manager.get_all_dependencies().values()) + [self.origin_addon]
        prepare_libraries(self.packs)
        validate_target(self.target_dir, self.source_dir, self.packs)
        if Path(self.target_dir).is_symlink() or (hasattr(Path(self.target_dir), 'is_junction') and Path(self.target_dir).is_junction()):
            raise DependencyError('构建目标不能是目录链接')
        self.target_addon = AddonsPack(self.project_name, self.source_dir)
        self.target_addon.path = self.target_dir
        for kind in ('behavior', 'resource'):
            source = getattr(self.origin_addon, kind + '_pack_dir')
            setattr(self.target_addon, kind + '_pack_dir', str(Path(self.target_dir) / Path(source).name))
        return True

    def build(self):
        try:
            self.initialize()
            target = Path(self.target_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.mcpy-build-', dir=target.parent) as temporary:
                stage = Path(temporary) / 'output'
                stage.mkdir()
                staged_addon = AddonsPack(self.project_name, stage)
                for kind in ('behavior', 'resource'):
                    setattr(staged_addon, kind + '_pack_dir', str(stage / Path(getattr(self.target_addon, kind + '_pack_dir')).name))
                assemble_addon(self.packs, staged_addon)
                backup = Path(temporary) / 'previous'
                if target.exists():
                    os.replace(target, backup)
                try:
                    os.replace(stage, target)
                except OSError:
                    if backup.exists():
                        os.replace(backup, target)
                    raise
            return True, None
        except (DependencyError, OSError, ValueError) as exc:
            return False, str(exc)


class MapProjectBuilder:
    def __init__(self, source_dir, target_dir, merge=False):
        self.source_dir = str(Path(source_dir).resolve())
        self.target_dir = str(Path(target_dir).resolve()) if target_dir else None
        self.merge = merge

    def build(self):
        try:
            manager = DependencyService(self.source_dir).resolve()
            report_dependency_warnings(manager)
            packs = list(manager.get_all_dependencies().values())
            root = manager.root_node.addon_pack
            if self.merge:
                prepare_libraries(packs + [root])
            else:
                for pack in packs + [root]:
                    prepare_libraries([pack])
            validate_target(self.target_dir, self.source_dir, packs + [root])
            for name in ('behavior_packs', 'resource_packs', 'db'):
                if is_within(self.target_dir, Path(self.source_dir) / name):
                    raise DependencyError('构建输出不能位于地图数据目录内')
            Path(self.target_dir).mkdir(parents=True, exist_ok=True)
            _clear_directory(self.target_dir)
            source = MapPack(manager.root_node.name, self.source_dir)
            target = MapPack(manager.root_node.name, self.target_dir)
            source.copy_level_data_to(self.target_dir)
            if not self.merge:
                for pack in packs:
                    pack.is_origin = True
                    if pack.behavior_pack_dir:
                        pack.copy_behavior_to(target.behavior_packs_dir, rename=Path(pack.behavior_pack_dir).name + '_' + pack.pkg_name)
                    if pack.resource_pack_dir:
                        pack.copy_resource_to(target.resource_packs_dir, rename=Path(pack.resource_pack_dir).name + '_' + pack.pkg_name)
                    for lib in getattr(pack, 'code_libraries', []):
                        destination = Path(target.behavior_packs_dir) / (Path(pack.behavior_pack_dir).name + '_' + pack.pkg_name) / lib['target']
                        shutil.copytree(lib['source'], destination)
                source.copy_behavior_packs_to(self.target_dir)
                source.copy_resource_packs_to(self.target_dir)
            else:
                for kind in ('behavior', 'resource'):
                    own = getattr(source, kind + '_packs')
                    main = AddonsPack(manager.root_node.name, self.source_dir, is_origin=True)
                    setattr(main, kind + '_pack_dir', own[0] if own else None)
                    folder = Path(getattr(target, kind + '_packs_dir')) / (Path(own[0]).name if own else kind + '_pack')
                    ordered = packs + [main]
                    for relative in sorted({f for p in ordered for f in pack_files(p, kind)}):
                        rebuild_file(ordered, kind, relative, folder / relative)
                    for extra in own[1:]:
                        shutil.copytree(extra, Path(getattr(target, kind + '_packs_dir')) / Path(extra).name)
            target.setup_world_packs_config()
            return True, None
        except (DependencyError, OSError, ValueError) as exc:
            return False, str(exc)

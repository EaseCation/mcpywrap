"""Non-game consumers resolve inputs without changing an active deployment."""
from pathlib import Path
import copy

from . import occupancy
from ..dependencies import DependencyService, read_project
from ..builders.AddonsPack import AddonsPack
from ..builders.MapPack import MapPack
from ..builders.project_builder import AddonProjectBuilder
from ..builders.assembly import assemble_addon
from ..code_libraries import prepare_libraries
from ..engines.host import EngineError


def resolve_packs(project, report=None):
    manager = DependencyService(project).resolve()
    if report:
        for warning in manager.warnings:
            report(warning)
    packs = list(manager.get_all_dependencies().values())
    if read_project(project).get('tool', {}).get('mcpywrap', {}).get('project_type', 'addon') == 'addon':
        packs.append(manager.root_node.addon_pack)
    return packs


def prepare_editor(project):
    if read_project(project).get('tool', {}).get('mcpywrap', {}).get('project_type', 'addon') == 'map':
        return resolve_packs(project)
    target = Path(project)/'.mcpy/editor/assembled'
    builder = AddonProjectBuilder(project, target)
    ok, error = builder.build()
    if not ok:
        raise EngineError(error, 'build_failed')
    return [builder.target_addon]


class MapRuntimeBuilder:
    """Assemble a map's separate packs without copying its world database."""
    def __init__(self, project, target, resolved=None):
        self.source_dir = str(Path(project).resolve())
        self.target_dir = str(Path(target).resolve())
        self.resolved = resolved

    def initialize(self):
        self.manager = self.resolved or DependencyService(self.source_dir).resolve()
        self.packs = [copy.copy(pack) for pack in self.manager.get_all_dependencies().values()]
        world = MapPack('map', self.source_dir)
        for kind in ('behavior', 'resource'):
            for folder in getattr(world, kind + '_packs'):
                pack = AddonsPack(Path(folder).name, self.source_dir, is_origin=True)
                pack.behavior_pack_dir = folder if kind == 'behavior' else None
                pack.resource_pack_dir = folder if kind == 'resource' else None
                self.packs.append(pack)
        from ..builders.assembly import validate_target
        from ..mcstudio.deployment_links import pack_uuid
        self.target_addon = []
        self.entries = []
        seen = {}
        for pack in self.packs:
            pack.is_origin = True
            prepare_libraries([pack])
            target = AddonsPack(pack.pkg_name, self.source_dir, is_origin=True)
            target.path = self.target_dir
            target.origin_path = pack.path
            target.behavior_pack_dir = None
            target.resource_pack_dir = None
            for kind in ('behavior', 'resource'):
                folder = getattr(pack, kind + '_pack_dir')
                if not folder or not Path(folder).is_dir(): continue
                identity = pack_uuid(folder)
                if not identity: continue
                key = (kind, identity)
                if key in seen:
                    if occupancy.path_key(seen[key]) != occupancy.path_key(folder):
                        raise EngineError('地图中存在不同来源的相同包 UUID。', 'pack_conflict')
                    continue
                seen[key] = folder
                setattr(target, kind + '_pack_dir', str(Path(self.target_dir)/(kind + '_packs')/identity))
                self.entries.append((pack, kind, target))
            if target.behavior_pack_dir or target.resource_pack_dir:
                self.target_addon.append(target)
        validate_target(self.target_dir, self.source_dir, self.packs)
        return True

    def build(self):
        try:
            self.initialize()
            Path(self.target_dir).mkdir(parents=True)
            for pack, kind, target in self.entries:
                source = copy.copy(pack)
                setattr(source, ('resource' if kind == 'behavior' else 'behavior') + '_pack_dir', None)
                if kind == 'resource':
                    source.code_libraries = []
                assemble_addon([source], target)
            return True, None
        except (OSError, ValueError) as error:
            return False, str(error)

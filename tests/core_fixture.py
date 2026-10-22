"""Small real project fixture, independent of desktop GUI/test dependencies."""
import json
from pathlib import Path
import uuid


def projects(root):
    from mcpywrap_core.dependencies import write_project
    root = Path(root)
    for name in ('main', 'dependency'):
        project = root/name
        project.mkdir(parents=True)
        write_project(project, {'project': {'name': name, 'version': '1.0.0'}, 'tool': {'mcpywrap': {
            'target_dir': './build', 'local_dependencies': ['../dependency'] if name == 'main' else []}}})
        for directory, kind in (('behavior_pack', 'data'), ('resource_pack', 'resources')):
            pack = project/directory
            pack.mkdir()
            (pack/'manifest.json').write_text(json.dumps({'format_version': 1, 'header': {
                'name': name, 'description': 'shared core fixture', 'version': [1, 0, 0],
                'uuid': str(uuid.uuid5(uuid.NAMESPACE_URL, name+directory))}, 'modules': [{
                    'type': kind, 'version': [1, 0, 0], 'uuid': str(uuid.uuid5(uuid.NAMESPACE_URL, name+directory+'module'))}]}))
        (project/'behavior_pack'/f'{name}.py').write_text(f'VALUE = {name!r}\n')
        (project/'behavior_pack/shared.py').write_text(f'OWNER = {name!r}\n')
        textures = project/'resource_pack/textures'
        textures.mkdir()
        (textures/'terrain_texture.json').write_text(json.dumps({'texture_data': {name: {'textures': name}}}))
    return root/'main'

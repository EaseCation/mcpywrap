"""Map changed source files to explicit reload operations for CLI and UI."""
import os


def changed_reload_targets(target_dir, changed_paths):
    from ..mcstudio.hot_reload import target_from_file
    from ..command_context import report_warning
    targets = {}
    for path in changed_paths:
        path = os.fspath(path)
        parts = [part.lower() for part in os.path.normpath(path).split(os.sep)]
        kind = ('python' if path.lower().endswith('.py') else
                'ui' if 'ui' in parts and path.lower().endswith('.json') else
                'shader' if 'shaders' in parts else
                'material' if 'materials' in parts else
                'particle' if 'particles' in parts and path.lower().endswith('.json') else None)
        if not kind:
            continue
        try:
            target = target_from_file(target_dir, kind, path)
            targets[(kind, None if kind == 'ui' else target)] = path
        except ValueError as error:
            report_warning('跳过热更: ' + str(error))
    return targets

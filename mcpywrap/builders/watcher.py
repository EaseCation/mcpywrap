"""监控主项目与全部依赖，使用与完整构建一致的合并顺序。"""
import os
import threading
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from ..dependencies import DependencyService
from .AddonsPack import AddonsPack
from .assembly import is_within, pack_files, rebuild_file, validate_target


class FileChangeHandler(FileSystemEventHandler):
    def __init__(self, source_dir, target_dir, callback=None, is_dependency=False,
                 dependency_name=None, project_watcher=None, addon_pack=None):
        self.source_dir, self.target_dir = source_dir, target_dir
        self.callback, self.project_watcher, self.addon_pack = callback, project_watcher, addon_pack
        self.is_dependency, self.dependency_name = is_dependency, dependency_name

    def _should_ignore_path(self, path):
        return is_within(path, self.target_dir) or self.addon_pack.should_exclude(path) and Path(path).name not in ('manifest.json', 'pack_manifest.json')

    def _process_event(self, event, event_type):
        if self._should_ignore_path(event.src_path):
            return
        inside, kind, relative = self.addon_pack.get_relative_path_in_pack(event.src_path)
        if not inside:
            return
        success, output = True, '文件已重新组装'
        destination = None
        try:
            if event.is_directory:
                self.project_watcher.rebuild_all()
            else:
                destination = self.project_watcher.rebuild(kind, relative)
        except (OSError, ValueError) as exc:
            success, output = False, str(exc)
        if self.callback:
            self.callback(event.src_path, destination, success, output,
                          event.src_path.endswith('.py'), self.is_dependency, self.dependency_name, event_type)

    def on_created(self, event):
        self._process_event(event, 'created')

    def on_deleted(self, event):
        self._process_event(event, 'deleted')

    def on_modified(self, event):
        self._process_event(event, 'modified')

    def on_moved(self, event):
        self._process_event(event, 'deleted')
        from watchdog.events import FileCreatedEvent, DirCreatedEvent
        self._process_event((DirCreatedEvent if event.is_directory else FileCreatedEvent)(event.dest_path), 'created')


class FileWatcher:
    def __init__(self, source_dir, target_dir, callback=None, **kwargs):
        self.source_dir = source_dir
        self.handler = FileChangeHandler(source_dir, target_dir, callback, **kwargs)
        self.observer = None

    def start(self):
        self.observer = Observer()
        self.observer.schedule(self.handler, self.source_dir, recursive=True)
        self.observer.start()

    def stop(self):
        if self.observer:
            self.observer.stop()
            if self.observer.is_alive():
                self.observer.join()


class MultiWatcher:
    def __init__(self):
        self.watchers = []

    def add_watcher(self, watcher):
        self.watchers.append(watcher)

    def start_all(self):
        try:
            for watcher in self.watchers:
                watcher.start()
        except Exception:
            self.stop_all()
            raise

    def stop_all(self):
        for watcher in self.watchers:
            watcher.stop()


class ProjectWatcher:
    def __init__(self, source_dir, target_dir, callback=None):
        self.source_dir, self.target_dir = os.path.abspath(source_dir), os.path.abspath(target_dir)
        self.callback = callback
        self.multi_watcher = MultiWatcher()
        self.lock = threading.RLock()
        self.known_files = set()

    def setup_from_config(self, project_name, dependencies=None):
        self.dependency_manager = DependencyService(self.source_dir).resolve()
        self.main_addon_pack = self.dependency_manager.root_node.addon_pack
        self.packs = list(self.dependency_manager.get_all_dependencies().values()) + [self.main_addon_pack]
        validate_target(self.target_dir, self.source_dir, self.packs)
        self.target_addon_pack = AddonsPack(project_name, self.target_dir)
        for kind in ('behavior', 'resource'):
            folder = getattr(self.main_addon_pack, kind + '_pack_dir')
            setattr(self.target_addon_pack, kind + '_pack_dir', str(Path(self.target_dir) / Path(folder).name))
        for pack in self.packs:
            self.known_files.update((kind, rel) for kind in ('behavior', 'resource') for rel in pack_files(pack, kind))
            self.multi_watcher.add_watcher(FileWatcher(
                pack.path, self.target_dir, self.callback, project_watcher=self,
                addon_pack=pack, is_dependency=not pack.is_origin, dependency_name=pack.pkg_name))
        return len(self.packs) - 1

    def rebuild(self, kind, relative):
        with self.lock:
            destination = Path(getattr(self.target_addon_pack, kind + '_pack_dir')) / relative
            rebuild_file(self.packs, kind, relative, destination)
            self.known_files.add((kind, relative))
            return str(destination)

    def rebuild_all(self):
        with self.lock:
            current = {(kind, rel) for p in self.packs for kind in ('behavior', 'resource') for rel in pack_files(p, kind)}
            for kind, relative in sorted(self.known_files | current):
                self.rebuild(kind, relative)
            self.known_files = current

    def start(self):
        self.multi_watcher.start_all()

    def stop(self):
        self.multi_watcher.stop_all()

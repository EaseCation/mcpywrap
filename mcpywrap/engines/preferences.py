"""User preferences mirrored to native files; worlds and identities stay isolated.

Only changed keys are exported, so an older running instance cannot overwrite
preferences changed by another instance merely by saving its stale options file.
"""
from contextlib import contextmanager, ExitStack
from pathlib import Path
import time
import uuid


GAME_PREFIXES = ('gfx_', 'audio_', 'ctrl_', 'keyboard_', 'feedback_', 'chat_', 'touch_',
                 'graphics_', 'glint_', 'bloom_', 'point_light_', 'upscaling_')
GAME_KEYS = {'game_language', 'game_thirdperson', 'game_tips_enabled', 'game_tips_animation_enabled',
             'screen_animations', 'ui_text_to_speech', 'text_to_speech_discovered',
             'monitor_platform_text_to_speech', 'camera_shake', 'hide_endflash',
             'gamma_calibration', 'darkness_effect_modifier', 'raytracing_viewdistance',
             'deferred_viewdistance', 'target_resolution', 'shadow_quality', 'cloud_quality',
             'volumetric_fog_quality', 'reflections_quality', 'frame_pacing_enabled',
             'ecomode_toggle', 'enable_dithering_blocks', 'enable_dithering_mobs',
             'show_advanced_video_settings'}


def game_preference(key):
    return key.startswith(GAME_PREFIXES) or key in GAME_KEYS


def read_properties(path, separator):
    try:
        before = path.stat()
        text = path.read_text(encoding='utf-8')
        after = path.stat()
    except FileNotFoundError:
        return {}
    if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
        return None  # The game is writing; try again on the next poll.
    # A final partial line may be an in-progress native write.
    lines = text.splitlines() if text.endswith('\n') else text.splitlines()[:-1]
    return dict(line.split(separator, 1) for line in lines if separator in line and not line.startswith(('#', ';')))


def write_properties(path, values, separator):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    try:
        temporary.write_text(''.join(key + separator + value + '\n' for key, value in sorted(values.items())), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def preference_lock(root):
    from ..remote.service import directory_lock, RemoteError
    with ExitStack() as stack:
        for attempt in range(100):
            try:
                stack.enter_context(directory_lock(root/'lock'))
                break
            except RemoteError as error:
                if error.code != 'busy' or attempt == 99:
                    raise
                time.sleep(.02)
        yield


class PreferenceFile:
    def __init__(self, local, shared, separator, accepts):
        self.local, self.shared = local, shared
        self.separator, self.accepts = separator, accepts
        self.observed = {}

    def filtered(self, data):
        return {key: value for key, value in data.items() if self.accepts(key)}

    def prepare(self, candidates):
        local = read_properties(self.local, self.separator)
        if local is None:
            raise ValueError('偏好文件正在写入，请稍后重试：' + str(self.local))
        shared = read_properties(self.shared, self.separator)
        if shared is None:
            raise ValueError('共享偏好文件正在写入：' + str(self.shared))
        if not self.shared.exists():
            # On adoption, prefer this existing instance, then the most recently
            # saved native preferences in this project. Never scan other projects.
            seed = self.filtered(local)
            if not seed:
                for candidate in candidates:
                    data = read_properties(candidate, self.separator)
                    if data:
                        seed = self.filtered(data)
                        if seed: break
            if seed:
                write_properties(self.shared, seed, self.separator)
                shared = seed
        merged = dict(local, **self.filtered(shared))
        if merged != local:
            write_properties(self.local, merged, self.separator)
        self.observed = self.filtered(merged)

    def sync(self):
        data = read_properties(self.local, self.separator)
        if data is None:
            return
        current = self.filtered(data)
        changed = {key: value for key, value in current.items() if self.observed.get(key) != value}
        if changed:
            shared = read_properties(self.shared, self.separator)
            if shared is None:
                return
            shared = self.filtered(shared)
            shared.update(changed)
            write_properties(self.shared, shared, self.separator)
        # Missing keys during a native truncate/rewrite are not deletions.
        self.observed.update(current)


class NativePreferences:
    def __init__(self, project, data, root):
        self.root = Path(root)
        data = Path(data)
        self.data = data
        game_path = Path('games/com.netease/minecraftpe/options.txt')
        launcher_path = Path('mcpelauncher-client-settings.txt')
        self.files = [PreferenceFile(data/game_path, self.root/'options.txt', ':', game_preference),
                      PreferenceFile(data/launcher_path, self.root/launcher_path, '=', lambda key: True)]
        self.project = Path(project)
        self.next_sync = 0

    def prepare(self):
        with preference_lock(self.root):
            for file in self.files:
                relative = file.local.relative_to(self.data)
                candidates = sorted((self.project/'.runtime/macos/instances').glob('*/data/' + relative.as_posix()),
                                    key=lambda p: p.stat().st_mtime_ns, reverse=True)
                file.prepare(candidates)
        return self

    def sync(self, force=False):
        now = time.monotonic()
        if not force and now < self.next_sync:
            return
        self.next_sync = now + 1
        with preference_lock(self.root):
            for file in self.files:
                file.sync()

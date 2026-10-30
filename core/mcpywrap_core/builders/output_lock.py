"""A dev watcher owns its output until stopped; builds cannot overwrite it."""
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import hashlib
import tempfile

from ..dependencies import canonical_path, DependencyError
from ..utils.locks import directory_lock


class OutputLease:
    def __init__(self, target):
        self.target = canonical_path(target)
        self.active = True

    @contextmanager
    def use(self, target):
        if not self.active or canonical_path(target) != self.target:
            raise DependencyError('构建输出占用凭据无效，请重启 dev')
        yield self


@contextmanager
def output_lease(target):
    key = hashlib.sha256(canonical_path(target).encode('utf-8')).hexdigest()
    with directory_lock(Path(tempfile.gettempdir())/'mcpy-output-locks'/key, reentrant=True):
        lease = OutputLease(target)
        try:
            yield lease
        finally:
            lease.active = False


def locked_output(method):
    @wraps(method)
    def wrapped(self):
        try:
            if self.target_dir is None:
                return method(self)
            lease = getattr(self, 'output_lease', None)
            with lease.use(self.target_dir) if lease else output_lease(self.target_dir):
                return method(self)
        except (ValueError, OSError) as exc:
            return False, str(exc)
    return wrapped

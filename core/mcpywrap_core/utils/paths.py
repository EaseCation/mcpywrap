"""Filesystem link checks shared by builders and runtime ownership guards."""
from pathlib import Path
import os
import stat


def is_link(path):
    """Recognize symlinks and Windows junctions on every supported Python.

    Path.is_junction only exists since 3.12; st_reparse_tag exists since 3.8.
    Other reparse tags (for example cloud placeholders) are not directory links.
    """
    try:
        info = Path(path).lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or (
        os.name == 'nt' and getattr(info, 'st_reparse_tag', None) == stat.IO_REPARSE_TAG_MOUNT_POINT)

"""Process identity without requiring system-wide boot statistics on restricted Linux."""
import os
import sys
from pathlib import Path
import psutil


def proc_stat(pid):
    # comm may contain spaces and parentheses; numeric fields start after its final ')'.
    raw = Path('/proc/%d/stat' % pid).read_text().rsplit(')', 1)[1].split()
    return {'pid': pid, 'state': raw[0], 'parent': int(raw[1]), 'group': int(raw[2]), 'start_ticks': int(raw[19])}


def identity(pid):
    process = psutil.Process(pid)
    try:
        created = process.create_time()
    except psutil.AccessDenied:
        if not sys.platform.startswith('linux'):
            raise
        # Android and other restricted procfs mounts expose our per-process stat,
        # but not /proc/stat (which psutil needs to convert ticks to wall-clock time).
        stat = proc_stat(pid)
        return {'pid': pid, 'start_ticks': stat['start_ticks'], 'executable': process.exe()}
    return {'pid': pid, 'created_at': created, 'executable': process.exe()}


def alive(record):
    try:
        if 'start_ticks' in record:
            stat = proc_stat(record['pid'])
            return stat['start_ticks'] == record['start_ticks'] and stat['state'] != 'Z'
        process = psutil.Process(record['pid'])
        return abs(process.create_time()-record['created_at']) < .01 and process.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, FileNotFoundError, ProcessLookupError):
        return False


def proc_members(group, known):
    """Inspect readable per-process records, never require visibility of other UIDs."""
    rows = {}
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit(): continue
        try: rows[int(directory.name)] = proc_stat(int(directory.name))
        except (OSError, ValueError, IndexError): continue
    owned = {record['pid'] for record in known.values() if alive(record)}
    found = {pid for pid, row in rows.items() if row['group'] == group and row['state'] != 'Z'}
    while True:
        descendants = {pid for pid, row in rows.items() if row['parent'] in owned | found and row['state'] != 'Z'}
        if descendants <= found: break
        found |= descendants
    for pid in found:
        try: known[pid] = identity(pid)
        except (psutil.NoSuchProcess, OSError): pass
    return [record for record in known.values() if alive(record)]

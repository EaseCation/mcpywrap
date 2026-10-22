"""Apply background-window and safe-stop patches to an initialized runtime source tree."""
import argparse
from pathlib import Path
import subprocess


def apply(manifest):
    root = Path(manifest).resolve(strict=True)
    patches = Path(__file__).resolve().parent
    targets = [(root/'game-window', patches/'game-window-background.patch'),
               (root/'mcpelauncher-client', patches/'client-background.patch'),
               (root/'libc-shim', patches/'libc-shim-background.patch'),
               (root, patches/'manifest-background.patch')]
    pending = []
    for repo, patch in targets:
        if not (repo/'.git').exists():
            raise RuntimeError('Initialize the Git checkout/submodule first: ' + str(repo))
        command = ['git', '-C', str(repo), 'apply']
        if subprocess.run(command + ['--reverse', '--check', str(patch)], capture_output=True).returncode == 0:
            continue
        result = subprocess.run(command + ['--check', str(patch)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('Patch preflight failed: ' + str(patch) + '\n' + result.stderr)
        pending.append((command, patch))
    applied = []
    try:
        for command, patch in pending:
            subprocess.run(command + [str(patch)], check=True)
            applied.append((command, patch))
    except BaseException:
        for command, patch in reversed(applied):
            subprocess.run(command + ['--reverse', str(patch)], check=True)
        raise
    return len(applied)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    args = parser.parse_args()
    print('Applied', apply(args.manifest), 'patches; build a new runtime before testing.')

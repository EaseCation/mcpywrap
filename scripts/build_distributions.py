"""Build both wheels from their sdists, avoiding stale build/lib ownership."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--outdir', default=str(ROOT/'dist'))
    parser.add_argument('--no-isolation', action='store_true')
    args = parser.parse_args()
    for name, source in (('core', ROOT/'core'), ('desktop', ROOT)):
        command = [sys.executable, '-m', 'build', str(source), '--outdir', str(Path(args.outdir).resolve()/name)]
        if args.no_isolation:
            command.append('--no-isolation')
        subprocess.run(command, check=True)

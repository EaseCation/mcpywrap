"""One release version for both distributions, without importing runtime code."""
import argparse
import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT/'core/mcpywrap_core/_version.py'


def release_version():
    return ast.literal_eval(ast.parse(VERSION_FILE.read_text()).body[0].value)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--set')
    parser.add_argument('--check-tag')
    args = parser.parse_args()
    if args.set:
        if not re.fullmatch(r'\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?', args.set):
            parser.error('Use X.Y.Z or X.Y.ZrcN/aN/bN')
        VERSION_FILE.write_text('__version__ = ' + repr(args.set) + '\n')
    version = release_version()
    if args.check_tag and args.check_tag != 'v'+version:
        parser.error('Tag does not match the shared release version')
    print(version)

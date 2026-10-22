"""Prepare idempotent uploads and confirm core visibility before desktop publish.

This script never uploads. Trusted Publishing remains in the release workflow.
An already published filename is skipped only when its SHA-256 matches exactly.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from urllib.error import HTTPError
from urllib.request import urlopen

if __package__:
    from .version import release_version
else:
    from version import release_version


def release_files(directory, project, version):
    name = project.replace('-', '_')+'-'+version
    files = [Path(directory)/(name+suffix) for suffix in ('-py3-none-any.whl', '.tar.gz')]
    if not all(path.is_file() for path in files):
        raise ValueError('Both wheel and sdist must exist before publishing')
    return files


def fetch(project, version):
    try:
        with urlopen('https://pypi.org/pypi/'+project+'/'+version+'/json', timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return {'urls': []}
        raise


def missing(files, remote):
    published = {entry['filename']: entry['digests']['sha256'] for entry in remote['urls']}
    result = []
    for file in files:
        if file.name not in published:
            result.append(file)
        elif published[file.name] != hashlib.sha256(file.read_bytes()).hexdigest():
            raise ValueError('Published bytes differ for '+file.name+'; use a new version, never overwrite or skip blindly')
    return result


def downloadable(files, remote):
    published = {entry['filename']: entry for entry in remote['urls']}
    for file in files:
        digest = hashlib.sha256()
        try:
            with urlopen(published[file.name]['url'], timeout=30) as response:
                for block in iter(lambda: response.read(1024 * 1024), b''):
                    digest.update(block)
        except OSError:
            return False
        if digest.hexdigest() != hashlib.sha256(file.read_bytes()).hexdigest():
            raise ValueError('Downloaded release bytes differ: '+file.name)
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('prepare', 'wait'))
    parser.add_argument('--project', required=True, choices=('mcpywrap', 'mcpywrap-core'))
    parser.add_argument('--directory', required=True)
    parser.add_argument('--outdir')
    args = parser.parse_args()
    version = release_version()
    files = release_files(args.directory, args.project, version)
    if args.mode == 'wait':
        for attempt in range(18):
            remote = fetch(args.project, version)
            if not missing(files, remote) and downloadable(files, remote):
                print(args.project+' '+version+' wheel and sdist are downloadable and match'); break
            time.sleep(10)
        else:
            raise SystemExit('Core artifacts are not yet visible; desktop publish has not started')
    else:
        if not args.outdir:
            parser.error('--outdir is required for prepare')
        pending = missing(files, fetch(args.project, version))
        output = Path(args.outdir)
        output.mkdir(parents=True, exist_ok=True)
        if any(output.iterdir()):
            raise ValueError('Upload staging directory must be empty')
        for file in pending:
            shutil.copy2(file, output/file.name)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
                stream.write('count='+str(len(pending))+'\n')
        print(json.dumps({'project': args.project, 'version': version, 'pending': [p.name for p in pending]}))

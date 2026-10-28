#!/usr/bin/env python3
"""Fetch exact compatible wheels; reuse verified public artifacts across builds."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import urllib.request

from download_asset import download
from pip._vendor.packaging.tags import sys_tags
from pip._vendor.packaging.utils import canonicalize_name, parse_wheel_filename
from pip._vendor.packaging.specifiers import SpecifierSet


def locked(path, result=None, visiting=None):
    result = {} if result is None else result
    visiting = set() if visiting is None else visiting
    path = Path(path).resolve()
    if path in visiting:
        raise ValueError('Cyclic lock file include')
    visiting.add(path)
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('-r '):
                locked(path.parent / line[3:].strip(), result, visiting)
                continue
            match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)', line)
            if not match:
                raise ValueError('Use a complete lock file with exact versions')
            name, version = match.groups()
            for existing, pinned in result.items():
                if canonicalize_name(existing) == canonicalize_name(name):
                    if pinned != version:
                        raise ValueError('Conflicting locked versions')
                    break
            else:
                result[name] = version
    finally:
        visiting.remove(path)
    return result


def install(path, cache_dir=None):
    versions = locked(path)
    tags = {tag: index for index, tag in enumerate(sys_tags())}
    python = '.'.join(map(str, sys.version_info[:3]))
    with TemporaryDirectory(prefix='plusfolio-wheels-') as directory:
        root = Path(directory)
        cache = Path(cache_dir) if cache_dir else None

        def wheel(item):
            name, version = item
            with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json', timeout=30) as response:
                metadata = json.load(response)
            choices = []
            for row in metadata['urls']:
                if row['packagetype'] != 'bdist_wheel' or row.get('yanked'):
                    continue
                if row.get('requires_python') and python not in SpecifierSet(row['requires_python']):
                    continue
                _, _, _, wheel_tags = parse_wheel_filename(row['filename'])
                ranks = [tags[tag] for tag in wheel_tags if tag in tags]
                if ranks:
                    choices.append((min(ranks), row['filename'], row))
            if not choices:
                raise ValueError('No compatible locked wheel: ' + name + '==' + version)
            row = min(choices, key=lambda value: (value[0], value[1]))[2]
            digest = row['digests']['sha256']
            target = cache / digest / row['filename'] if cache else root / row['filename']
            download(row['url'], target, digest, row['size'], workers=4)
            if cache:
                # Pip sees only this lock's chosen wheels, never unrelated cached versions.
                shutil.copyfile(target, root / row['filename'])
            print('Verified wheel: ' + name + '==' + version, flush=True)
            return name + '==' + version + ' --hash=sha256:' + digest

        with ThreadPoolExecutor(max_workers=6) as pool:
            requirements = list(pool.map(wheel, versions.items()))
        hashed = root / 'verified.txt'
        hashed.write_text('\n'.join(requirements) + '\n')
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--no-cache-dir',
                        '--find-links', str(root), '--require-hashes', '-r', str(hashed)], check=True)
        subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('lock', type=Path)
    parser.add_argument('--cache-dir', type=Path, help='Build-only cache; wheel hashes are always verified')
    args = parser.parse_args()
    install(args.lock, args.cache_dir)

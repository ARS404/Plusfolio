#!/usr/bin/env python3
"""Read/check product identity, or synchronize a new version before committing it."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from core.release import build_metadata, read_release, validate_release


def check(root=ROOT, tag=None):
    root = Path(root)
    release = read_release(root)
    package = json.loads((root/'frontend/package.json').read_text())
    lock = json.loads((root/'frontend/package-lock.json').read_text())
    if any(value != release['version'] for value in [package['version'], lock['version'], lock['packages']['']['version']]):
        raise ValueError('Frontend versions differ from release.json; use --set to synchronize them')
    if tag is not None and (release['status'] != 'released' or tag != 'v' + release['version']):
        raise ValueError('Release tag requires status=released and must match v<version>')
    return release


def set_release(version, status='development', root=ROOT):
    root = Path(root)
    release = validate_release({'version': version, 'status': status})
    package_path = root/'frontend/package.json'
    lock_path = root/'frontend/package-lock.json'
    package = json.loads(package_path.read_text())
    lock = json.loads(lock_path.read_text())
    package['version'] = lock['version'] = lock['packages']['']['version'] = version
    (root/'release.json').write_text(json.dumps(release, indent=2) + '\n')
    package_path.write_text(json.dumps(package, separators=(',', ':')) + '\n')
    lock_path.write_text(json.dumps(lock, indent=2) + '\n')
    check(root)
    return release


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--check', action='store_true')
    actions.add_argument('--set', dest='version')
    actions.add_argument('--check-tag')
    parser.add_argument('--status', choices=['development', 'released'])
    args = parser.parse_args()
    try:
        if args.status and not args.version:
            parser.error('--status requires --set')
        if args.version:
            set_release(args.version, args.status or 'development')
        check(tag=args.check_tag)
        print(json.dumps(build_metadata(), ensure_ascii=False))
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, str(error) + '\n')

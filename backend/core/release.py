"""Public product/build identity, independent from API and database versions."""
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SEMVER = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?')


def validate_release(data):
    if not isinstance(data, dict) or set(data) != {'version', 'status'}:
        raise ValueError('release.json requires version and status')
    version = data['version']
    match = SEMVER.fullmatch(version) if isinstance(version, str) else None
    if not match or (match[4] and any(part.isdigit() and len(part) > 1 and part.startswith('0') for part in match[4].split('.'))):
        raise ValueError('Use a valid SemVer version')
    if not isinstance(data['status'], str) or data['status'] not in {'development', 'released'}:
        raise ValueError('Release status must be development or released')
    if data['status'] == 'released' and match[4]:
        raise ValueError('A stable release cannot contain a prerelease identifier')
    return dict(data)


def read_release(root=ROOT):
    return validate_release(json.loads((Path(root)/'release.json').read_text()))


def source_revision(root=ROOT):
    # Git is optional in source archives and deliberately absent from runtime images.
    root = Path(root)
    if not (root/'.git').exists():
        return 'unknown'
    try:
        result = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                                capture_output=True, text=True, timeout=3)
        revision = result.stdout.strip()
        if result.returncode or not re.fullmatch(r'[0-9a-f]{40,64}', revision):
            return 'unknown'
        state = subprocess.run(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=normal'],
                               capture_output=True, text=True, timeout=3)
        return revision + ('-dirty' if state.returncode or state.stdout else '')
    except (OSError, subprocess.TimeoutExpired):
        return 'unknown'


def build_metadata(root=ROOT):
    revision = os.environ.get('PLUSFOLIO_REVISION') or source_revision(root)
    if not re.fullmatch(r'(?:[0-9a-f]{40,64}(?:-dirty)?|unknown)', revision):
        revision = 'unknown'
    return {**read_release(root), 'revision': revision}


@lru_cache(maxsize=1)
def release_info():
    return build_metadata()

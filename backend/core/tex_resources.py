"""Receipt for trusted, successfully compiled offline resources; no app settings."""
import hashlib
import json
import os
import stat
from pathlib import Path
from uuid import uuid4

PREPARATION_FILE = 'plusfolio-prepared.json'
CACHE_PREFIX = '.local/tectonic-cache/'
MAX_RESOURCE_ENTRIES = 4096
MAX_RESOURCE_BYTES = 256*1024*1024
MAX_RECEIPT_BYTES = 2*1024*1024
PREPARATION_SOURCES = (
    'scripts/setup_tex.py', 'backend/core/tex_resources.py',
    'backend/core/tex_templates/math-a4-v1.tex',
    'backend/core/tex_templates/math-a4-v2.tex',
)


def resource_files(cache):
    """Bound metadata, traversal and input bytes before hashing or archiving."""
    cache = Path(cache); pending = [cache]; result = {}; count = 0; total = 0
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                count += 1
                if count > MAX_RESOURCE_ENTRIES:
                    raise ValueError('TeX resources exceed the 4096-entry limit; rebuild the trusted cache.')
                if stat.S_ISDIR(info.st_mode):
                    pending.append(Path(entry.path))
                elif stat.S_ISREG(info.st_mode):
                    total += info.st_size
                    if total > MAX_RESOURCE_BYTES:
                        raise ValueError('TeX resources exceed the 256 MiB limit; rebuild the trusted cache.')
                    path = Path(entry.path); result[str(path.relative_to(cache))] = path
    return result


def read_preparation(path):
    with path.open('rb') as source:
        data = source.read(MAX_RECEIPT_BYTES+1)
    if len(data) > MAX_RECEIPT_BYTES:
        raise ValueError('TeX preparation receipt exceeds 2 MiB.')
    return json.loads(data)


def trusted_paths(root, values=None):
    """Image-owned resources stay outside the persistent application volume."""
    values = os.environ if values is None else values
    local = Path(root)/'.local'
    cache = Path(values.get('PLUSFOLIO_TEX_RESOURCE_DIR') or local/'tectonic-cache')
    compiler = Path(values.get('PLUSFOLIO_TEX_COMPILER') or local/'tools/tectonic')
    return {'tools': compiler.parent, 'tectonic-cache': cache,
            'tectonic-config': cache.parent/'tectonic-config'}


def file_hash(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def record_preparation(root, cache):
    """Call only after every trusted template passed offline compilation."""
    root = Path(root); cache = Path(cache)
    receipt = {
        'version': 1,
        'sources': {name: file_hash(root/name) for name in PREPARATION_SOURCES},
        'resources': {name: file_hash(path) for name, path in resource_files(cache).items()
                      if name != PREPARATION_FILE},
    }
    temporary = cache/('.prepared-'+uuid4().hex+'.tmp')
    try:
        data = json.dumps(receipt, sort_keys=True).encode()
        if len(data) > MAX_RECEIPT_BYTES:
            raise ValueError('TeX preparation receipt exceeds 2 MiB.')
        temporary.write_bytes(data)
        temporary.chmod(0o600)
        os.replace(temporary, cache/PREPARATION_FILE)
    finally:
        temporary.unlink(missing_ok=True)


def validate_preparation(hashes, receipt):
    sources = {name: hashes[name] for name in PREPARATION_SOURCES}
    resources = {name.removeprefix(CACHE_PREFIX): digest for name, digest in hashes.items()
                 if name.startswith(CACHE_PREFIX) and name != CACHE_PREFIX+PREPARATION_FILE}
    if receipt != {'version': 1, 'sources': sources, 'resources': resources}:
        raise ValueError('Offline TeX resources are incomplete or stale; the administrator must run scripts/setup_tex.py and rebuild the toolchain archive.')

"""Distribute the exact, non-secret renderer and its prepared offline resources."""
import ast
import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
import zipfile
from django.conf import settings
from .documents import TEMPLATE, CompilerUnavailable

SOURCE_FILES = [
    'backend/core/__init__.py', 'backend/core/documents.py', 'backend/core/tex_worker.py',
    'backend/core/tex_templates/math-a4-v1.tex', 'backend/core/tex_templates/math-a4-v2.tex',
    'backend/core/document_content.py', 'backend/core/content.py', 'backend/core/tex_project.py', 'backend/core/tex_cache.py', 'backend/core/tex_runtime.py', 'backend/core/tex_toolchain.py', 'backend/core/tex_remote.py', 'scripts/tex_service.py',
    'scripts/setup_tex.py', 'scripts/download_asset.py', 'scripts/preview_tex.py', 'requirements-tex.lock',
    'docs/tex-preflight.md', 'docs/worksheet-builder.md',
]


def toolchain_files(root=None, cache_root=None):
    root=Path(root or settings.BASE_DIR)
    cache=Path(cache_root or settings.LOCAL_DIR/'tectonic-cache')
    sources={name:root/name for name in SOURCE_FILES}
    resources={'.local/tectonic-cache/'+str(path.relative_to(cache)):path
               for path in cache.rglob('*') if path.is_file() and not path.is_symlink()}
    if not resources or any(not path.is_file() or path.is_symlink() for path in sources.values()):
        raise CompilerUnavailable('Пакет TeX не подготовлен. Администратору: выполните scripts/setup_tex.py.')
    return {**sources,**resources}


@lru_cache(maxsize=4096)
def _file_digest(path, signature):
    # The signature includes ctime/inode, so same-size edits and atomic replacements
    # invalidate a cached digest even if a tool restores the old mtime.
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def _contract(files):
    hashes={};total_bytes=0
    for name,path in sorted(files.items()):
        info=path.stat();total_bytes+=info.st_size
        signature=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
        hashes[name]=_file_digest(path.absolute(),signature)
    # Read the pinned version from the same installer used by the service.
    tree=ast.parse(files['scripts/setup_tex.py'].read_text())
    version=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign)
                 and any(isinstance(target,ast.Name) and target.id=='VERSION' for target in node.targets))
    compiler={'name':'Tectonic','version':version,'provider':'XeTeX',
              'arguments':['-X','compile','--untrusted','--only-cached','--keep-logs','main.tex']}
    identity={'compiler':compiler,'template_version':TEMPLATE,'files':hashes}
    digest=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    return {**identity,'contract_id':digest,'archive_url':'/api/v1/tex/toolchain/archive',
            'archive_bytes_uncompressed':total_bytes,
            'prepare_command':'python scripts/preview_tex.py --prepare --expected-contract <CONTRACT_ID>',
            'preview_command':'python scripts/preview_tex.py --input draft.json --output review-v1 --expected-contract <CONTRACT_ID>',
            'requirements':['Python 3.12+','macOS arm64: sandbox-exec; Linux x86_64/aarch64: bubblewrap',
                            'Exact Tectonic version; complete bundled offline cache; no network for user TeX'],
            'limits':{'wall_seconds':20,'cpu_seconds':12,'max_pdf_bytes':16777216,
                      'max_blocks':300,'max_image_bytes':4194304,'max_workspace_bytes':67108864,'max_workspace_entries':2048,'max_open_files':256,'linux_address_space_bytes':1073741824,'max_problems':300}}


def build_contract(root=None, cache_root=None):
    return _contract(toolchain_files(root,cache_root))


def toolchain_archive(*,open_file=False):
    from .tex_cache import toolchain_cache
    from uuid import uuid4
    cache=toolchain_cache()
    if not cache.max_entries or not cache.max_age or not cache.max_bytes:
        raise CompilerUnavailable('Архив TeX недоступен: хранение пакета отключено настройками кэша.')
    files=toolchain_files();contract=_contract(files)
    with cache.locked():
        cache._prune()
        target=cache.directory/(contract['contract_id']+'.zip')
        if target.is_symlink():raise CompilerUnavailable('Некорректный файл кэша TeX.')
        if not target.exists():
            temporary=cache.directory/(contract['contract_id']+'.'+uuid4().hex+'.tmp')
            try:
                with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
                    for relative,path in files.items():archive.write(path,relative)
                    archive.writestr('toolchain-manifest.json',json.dumps(contract,ensure_ascii=False,indent=2))
                if temporary.stat().st_size>cache.max_bytes:raise CompilerUnavailable('Архив TeX превышает настроенный лимит кэша.')
                temporary.chmod(0o600);os.replace(temporary,target)
            finally:temporary.unlink(missing_ok=True)
        os.utime(target,None);cache._prune()
        # Open while still locked: a newer contract can evict this path immediately afterwards.
        return target.open('rb') if open_file else target

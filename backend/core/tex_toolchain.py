"""Distribute the exact, non-secret renderer and its prepared offline resources."""
import ast
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import zipfile
from django.conf import settings
from .documents import TEMPLATE, CompilerUnavailable

SOURCE_FILES = [
    'backend/core/__init__.py', 'backend/core/documents.py', 'backend/core/tex_worker.py',
    'backend/core/tex_templates/math-a4-v1.tex', 'backend/core/tex_toolchain.py', 'backend/core/tex_remote.py', 'scripts/tex_service.py',
    'scripts/setup_tex.py', 'scripts/download_asset.py', 'scripts/preview_tex.py', 'requirements-tex.lock',
    'docs/tex-preflight.md',
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


def build_contract(root=None, cache_root=None):
    files=toolchain_files(root,cache_root)
    hashes={}
    for name,path in sorted(files.items()):
        with path.open('rb') as source:hashes[name]=hashlib.file_digest(source,'sha256').hexdigest()
    # Read the pinned version from the same installer used by the service.
    tree=ast.parse(files['scripts/setup_tex.py'].read_text())
    version=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign)
                 and any(isinstance(target,ast.Name) and target.id=='VERSION' for target in node.targets))
    compiler={'name':'Tectonic','version':version,'provider':'XeTeX',
              'arguments':['-X','compile','--untrusted','--only-cached','--keep-logs','main.tex']}
    identity={'compiler':compiler,'template_version':TEMPLATE,'files':hashes}
    digest=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    return {**identity,'contract_id':digest,'archive_url':'/api/v1/tex/toolchain/archive',
            'archive_bytes_uncompressed':sum(path.stat().st_size for path in files.values()),
            'prepare_command':'python scripts/preview_tex.py --prepare --expected-contract <CONTRACT_ID>',
            'preview_command':'python scripts/preview_tex.py --input draft.json --output review-v1 --expected-contract <CONTRACT_ID>',
            'requirements':['Python 3.12+','macOS arm64: sandbox-exec; Linux x86_64/aarch64: bubblewrap',
                            'Exact Tectonic version; complete bundled offline cache; no network for user TeX'],
            'limits':{'wall_seconds':20,'cpu_seconds':12,'max_pdf_bytes':16777216,
                      'max_open_files':256,'linux_address_space_bytes':1073741824,'max_problems':300}}


def toolchain_archive():
    contract=build_contract()
    directory=settings.LOCAL_DIR/'tex-toolchains';directory.mkdir(mode=0o700,exist_ok=True)
    target=directory/(contract['contract_id']+'.zip')
    if not target.exists():
        with NamedTemporaryFile(dir=directory,suffix='.zip',delete=False) as temp:name=temp.name
        try:
            with zipfile.ZipFile(name,'w',zipfile.ZIP_DEFLATED) as archive:
                for relative,path in toolchain_files().items():archive.write(path,relative)
                archive.writestr('toolchain-manifest.json',json.dumps(contract,ensure_ascii=False,indent=2))
            os.chmod(name,0o600);os.replace(name,target)
        finally:Path(name).unlink(missing_ok=True)
    return target

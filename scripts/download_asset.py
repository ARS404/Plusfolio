"""Bounded parallel download of immutable public assets, with verified final hashes."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib,math,re,shutil,time,urllib.request


def download(url,target,digest=None,size=None,workers=8,max_bytes=512*1024*1024):
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists() and digest:
        with target.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()==digest:return
    workers=max(1,min(int(workers),16))
    with TemporaryDirectory(prefix='asset-',dir=target.parent) as temporary:
        temporary=Path(temporary);output=temporary/'asset'
        parallel=False
        if workers>1 and (size is None or size>=2*1024*1024):
            try:
                req=urllib.request.Request(url,headers={'Range':'bytes=0-0'})
                with urllib.request.urlopen(req,timeout=30) as response:
                    match=re.fullmatch(r'bytes 0-0/(\d+)',response.headers.get('Content-Range',''))
                    if response.status==206 and match:
                        actual=int(match[1])
                        if size is not None and actual!=size:raise ValueError('Asset size mismatch')
                        size=actual;parallel=2*1024*1024<=size<=max_bytes
            except (OSError,TimeoutError):parallel=False
        if size is not None and size>max_bytes:raise ValueError('Asset too large')
        if parallel:
            chunk=max(1024*1024,math.ceil(size/workers))
            ranges=[(start,min(size-1,start+chunk-1)) for start in range(0,size,chunk)]
            def part(pair):
                start,end=pair;path=temporary/str(start)
                for attempt in range(3):
                    try:
                        req=urllib.request.Request(url,headers={'Range':f'bytes={start}-{end}'})
                        with urllib.request.urlopen(req,timeout=90) as response:
                            if response.status!=206 or response.headers.get('Content-Range')!=f'bytes {start}-{end}/{size}':raise ValueError('Invalid asset range')
                            with path.open('wb') as target:shutil.copyfileobj(response,target,1024*1024)
                        if path.stat().st_size!=end-start+1:raise ValueError('Truncated asset range')
                        return path
                    except OSError:
                        if attempt==2:raise
                        time.sleep(2**attempt)
            with ThreadPoolExecutor(max_workers=workers) as pool:paths=list(pool.map(part,ranges))
            with output.open('wb') as sink:
                for path in paths:
                    with path.open('rb') as source:shutil.copyfileobj(source,sink,1024*1024)
        else:
            with urllib.request.urlopen(url,timeout=120) as source,output.open('wb') as sink:
                total=0
                while data:=source.read(1024*1024):
                    total+=len(data)
                    if total>max_bytes:raise ValueError('Asset too large')
                    sink.write(data)
        if size is not None and output.stat().st_size!=size:raise ValueError('Asset size mismatch')
        if digest:
            with output.open('rb') as source:
                if hashlib.file_digest(source,'sha256').hexdigest()!=digest:raise ValueError('Asset checksum mismatch')
        output.replace(target)

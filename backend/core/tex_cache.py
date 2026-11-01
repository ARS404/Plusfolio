"""Bounded disposable artifacts. Never traverses TeX resources or user attachments."""
from contextlib import contextmanager
import fcntl,json,os,re,time
from pathlib import Path
from uuid import uuid4


class ArtifactCache:
    def __init__(self,directory,suffix,max_bytes,max_entries,max_age):
        self.directory=Path(directory);self.suffix=suffix
        self.max_bytes=max(0,int(max_bytes));self.max_entries=max(0,int(max_entries));self.max_age=max(0,int(max_age))
        self.pattern=re.compile(r'[0-9a-f]{64}\.'+re.escape(suffix))

    @contextmanager
    def locked(self):
        self.directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        if self.directory.is_symlink():raise OSError('Artifact cache cannot be a symlink')
        descriptor=os.open(self.directory/'.lock',os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            fcntl.flock(descriptor,fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor,fcntl.LOCK_UN);os.close(descriptor)

    def _remove(self,path):
        path.unlink(missing_ok=True);path.with_suffix('.json').unlink(missing_ok=True)

    def _prune(self):
        now=time.time();entries=[];removed=0
        for path in self.directory.iterdir():
            if path.is_symlink() or not path.is_file():continue
            info=path.stat()
            if self.pattern.fullmatch(path.name):
                side=path.with_suffix('.json')
                size=info.st_size+(side.stat().st_size if side.is_file() and not side.is_symlink() else 0)
                if now-info.st_mtime>self.max_age or not self.max_entries or size>self.max_bytes:
                    self._remove(path);removed+=1
                else:entries.append((info.st_mtime,path,size))
            elif now-info.st_mtime>3600 and (re.fullmatch(r'[0-9a-f]{64}\.[0-9a-f]+\.tmp',path.name) or
                    re.fullmatch(r'[0-9a-f]{64}\.json',path.name) and not path.with_suffix('.'+self.suffix).exists()):
                path.unlink(missing_ok=True);removed+=1
        entries.sort();size=sum(entry[2] for entry in entries);evicted=0
        while evicted<len(entries) and (size>self.max_bytes or len(entries)-evicted>self.max_entries):
            _,path,amount=entries[evicted];self._remove(path);size-=amount;removed+=1;evicted+=1
        return {'files':len(entries)-evicted,'bytes':size,'removed':removed,'max_bytes':self.max_bytes,'max_files':self.max_entries,'max_age_seconds':self.max_age}

    def prune(self):
        with self.locked():return self._prune()

    def get(self,digest):
        if not re.fullmatch(r'[0-9a-f]{64}',digest):raise ValueError('Invalid artifact digest')
        with self.locked():
            self._prune();path=self.directory/(digest+'.'+self.suffix)
            if not path.is_file() or path.is_symlink():return None
            payload=path.read_bytes();metadata={}
            side=path.with_suffix('.json')
            if side.is_file() and not side.is_symlink() and side.stat().st_size<=100000:
                try:
                    loaded=json.loads(side.read_text())
                    if isinstance(loaded,dict):metadata=loaded
                except (OSError,ValueError):pass
            if self.suffix=='pdf' and not payload.startswith(b'%PDF-'):
                self._remove(path);return None
            os.utime(path,None)
            return payload,metadata

    def put(self,digest,payload,metadata=None):
        if not re.fullmatch(r'[0-9a-f]{64}',digest):raise ValueError('Invalid artifact digest')
        if not self.max_entries or not self.max_age or len(payload)>self.max_bytes:return False
        with self.locked():
            path=self.directory/(digest+'.'+self.suffix)
            temporary=self.directory/(digest+'.'+uuid4().hex+'.tmp')
            try:
                temporary.write_bytes(payload);temporary.chmod(0o600);os.replace(temporary,path)
                if metadata is not None:
                    temporary.write_text(json.dumps(metadata,ensure_ascii=False));temporary.chmod(0o600)
                    os.replace(temporary,path.with_suffix('.json'))
                self._prune()
            finally:temporary.unlink(missing_ok=True)
            return path.exists()


def pdf_cache():
    from django.conf import settings
    return ArtifactCache(settings.LOCAL_DIR/'pdf-cache','pdf',getattr(settings,'PDF_CACHE_MAX_BYTES',128*1024*1024),
                         getattr(settings,'PDF_CACHE_MAX_FILES',256),getattr(settings,'PDF_CACHE_MAX_AGE',7*86400))


def toolchain_cache():
    from django.conf import settings
    return ArtifactCache(settings.LOCAL_DIR/'tex-toolchains','zip',getattr(settings,'TEX_ARCHIVE_CACHE_MAX_BYTES',128*1024*1024),
                         getattr(settings,'TEX_ARCHIVE_CACHE_MAX_FILES',2),getattr(settings,'TEX_ARCHIVE_CACHE_MAX_AGE',14*86400))

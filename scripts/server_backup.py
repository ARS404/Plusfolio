#!/usr/bin/env python3
"""Streaming authenticated age backups: database, source, runtime, model and configuration."""
import argparse,fcntl,hashlib,io,json,os,re,stat,subprocess,tarfile,time
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
ROOT=Path(__file__).resolve().parents[1]


class HashedReader:
    def __init__(self,path):self.source=path.open('rb');self.digest=hashlib.sha256()
    def read(self,size=-1):
        value=self.source.read(size);self.digest.update(value);return value



def retention_policy(values=None):
    values=os.environ if values is None else values
    policy={key:int(values.get(name,default)) for key,name,default in [
        ('days','BACKUP_RETENTION_DAYS','14'),('count','BACKUP_MAX_COUNT','14'),
        ('bytes','BACKUP_MAX_BYTES','2147483648'),('keep','BACKUP_KEEP_MIN','2')]}
    if policy['days']<1 or policy['keep']<2 or policy['count']<policy['keep'] or policy['bytes']<1:
        raise ValueError('Срок хранения должен быть положительным; сохраняется минимум две копии, MAX_COUNT >= KEEP_MIN')
    return policy


def prune_backups(directory,policy=None,now=None):
    policy=policy or retention_policy();now=time.time() if now is None else now
    files=[]
    for path in Path(directory).iterdir():
        if not re.fullmatch(r'plusfolio-\d{8}T\d{12}Z\.tar\.gz\.age',path.name):continue
        info=path.lstat()
        if stat.S_ISREG(info.st_mode):files.append((path,info))
    files.sort(key=lambda row:row[0].name,reverse=True)
    keep=files[:policy['keep']];used=sum(info.st_size for _,info in keep);removed=0
    for path,info in files[policy['keep']:]:
        if info.st_mtime<now-policy['days']*86400 or len(keep)>=policy['count'] or used+info.st_size>policy['bytes']:
            path.unlink();removed+=1
        else:keep.append((path,info));used+=info.st_size
    for path in Path(directory).iterdir():
        if re.fullmatch(r'plusfolio-\d{8}T\d{12}Z\.tar\.gz\.partial',path.name):
            info=path.lstat()
            if stat.S_ISREG(info.st_mode) and info.st_mtime<now-86400:path.unlink()
    return {'removed':removed,'kept':len(keep),'bytes':used}


def backup():
    directory=Path('/backups');directory.mkdir(exist_ok=True)
    policy=retention_policy()
    with (directory/'.backup.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('Backup already running; nothing changed.',flush=True);return None
        try:os.nice(10)
        except OSError:pass
        result=_backup()
        report=prune_backups(directory,policy)
        (directory/'last-success').write_text(str(time.time()))
        print('Backup retention: '+json.dumps(report),flush=True)
        return result


def _backup():
    recipient=os.environ.get('BACKUP_RECIPIENT','')
    if not recipient.startswith('age1'):raise RuntimeError('BACKUP_RECIPIENT is required')
    directory=Path('/backups');directory.mkdir(exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target=directory/f'plusfolio-{stamp}.tar.gz.age';temporary=target.with_suffix('.partial')
    from release import build_metadata
    manifest={'release':build_metadata(ROOT),'format':'plusfolio-server-v1','created_at':datetime.now(timezone.utc).isoformat(),'files':{},'image':os.environ.get('RELEASE_ID','local-build')}
    with TemporaryDirectory(prefix='plusfolio-backup-') as scratch:
        dump=Path(scratch)/'database.dump'
        env=os.environ.copy();env['PGPASSWORD']=Path(env['POSTGRES_PASSWORD_FILE']).read_text().strip()
        with dump.open('wb') as stream:
            subprocess.run(['pg_dump','--host',env['POSTGRES_HOST'],'--username',env['POSTGRES_USER'],'--dbname',env['POSTGRES_DB'],'--format=custom','--no-owner'],env=env,stdout=stream,stderr=subprocess.PIPE,check=True)
        paths={'database.dump':dump}
        for name in ['backend','scripts','deploy','data','docs','frontend','embeddings','.github']:
            for path in (ROOT/name).rglob('*'):
                if path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts and path.suffix!='.pyc':paths['source/'+str(path.relative_to(ROOT))]=path
        for name in ['README.md','CHANGELOG.md','release.json','compose.yml','.dockerignore','.gitignore','requirements.lock','requirements-server.lock','requirements-tex.lock','requirements.txt']:
            paths['source/'+name]=ROOT/name
        for name in ['tools','tectonic-cache','tectonic-config']:
            for path in (ROOT/'.local'/name).rglob('*'):
                if path.is_file() and not path.is_symlink():paths['source/.local/'+str(path.relative_to(ROOT/'.local'))]=path
        for path in Path('/model').rglob('*'):
            if path.is_file() and not path.is_symlink():paths['model/'+str(path.relative_to('/model'))]=path
        # The decrypting key is deliberately excluded. Keep it outside the server too.
        config=Path('/deployment/env')
        if config.is_file() and not config.is_symlink():
            paths['source/.deploy/env']=config
        for path in Path('/run/secrets').glob('*'):
            if path.is_file() and path.name in {'app_key','postgres_password','db_password','smtp_password','admin_password'}:
                paths['source/.deploy/secrets/'+path.name]=path
        try:
            with temporary.open('wb') as output:
                process=subprocess.Popen(['age','--recipient',recipient],stdin=subprocess.PIPE,stdout=output,stderr=subprocess.PIPE)
                try:
                    with tarfile.open(fileobj=process.stdin,mode='w|gz',compresslevel=1) as archive:
                        for name,path in sorted(paths.items()):
                            reader=HashedReader(path)
                            try:
                                info=tarfile.TarInfo(name);info.size=path.stat().st_size;info.mode=0o600;archive.addfile(info,reader)
                                manifest['files'][name]=reader.digest.hexdigest()
                            finally:reader.source.close()
                        payload=json.dumps(manifest,sort_keys=True).encode();info=tarfile.TarInfo('manifest.json');info.size=len(payload);archive.addfile(info,io.BytesIO(payload))
                    process.stdin.close()
                    if process.wait(timeout=60):raise RuntimeError('Backup encryption failed')
                finally:
                    if process.poll() is None:process.kill();process.wait()
            temporary.chmod(0o600);temporary.replace(target)
            print('Encrypted backup ready: '+target.name,flush=True)
            return target
        except Exception:
            temporary.unlink(missing_ok=True);raise


def verify(path,key,into=None,empty_output=False):
    with TemporaryDirectory(prefix='plusfolio-verify-') as scratch:
        tar=Path(scratch)/'decrypted.tar.gz'
        with tar.open('wb') as stream:
            subprocess.run(['age','--decrypt','--identity',str(key),str(path)],stdout=stream,stderr=subprocess.PIPE,check=True)
        with tarfile.open(tar,'r:gz') as archive:
            manifest=json.load(archive.extractfile('manifest.json'))
            if manifest.get('format')!='plusfolio-server-v1':raise ValueError('Unknown backup format')
            names=archive.getnames()
            if len(names)!=len(set(names)) or set(names)!=set(manifest['files'])|{'manifest.json'}:raise ValueError('Invalid manifest')
            for member in archive.getmembers():
                if not member.isfile() or Path(member.name).is_absolute() or '..' in Path(member.name).parts:raise ValueError('Invalid backup member')
                with archive.extractfile(member) as stream:
                    checksum=hashlib.file_digest(stream,'sha256').hexdigest()
                if member.name!='manifest.json' and checksum!=manifest['files'][member.name]:raise ValueError('Checksum mismatch')
            if into:
                into=Path(into)
                if into.exists() and (not empty_output or any(into.iterdir())):raise ValueError('Restore destination must not exist or must be an explicitly allowed empty mount')
                into.mkdir(mode=0o700,parents=True,exist_ok=empty_output)
                for member in archive.getmembers():
                    target=into/member.name;target.parent.mkdir(parents=True,exist_ok=True,mode=0o755)
                    with archive.extractfile(member) as source,target.open('wb') as destination:
                        import shutil;shutil.copyfileobj(source,destination,1024*1024)
                    target.chmod(0o600 if member.name=='database.dump' or member.name.startswith('source/.deploy/') else 0o644)
                for name in ['source/.deploy','source/.deploy/secrets']:
                    directory=into/name
                    if directory.exists():directory.chmod(0o700)
                for name in ['source/.local/tools/tectonic','source/deploy/postgres-init.sh','source/scripts/install_server.sh','source/scripts/run_demo.sh','source/scripts/run_search.sh']:
                    path=into/name
                    if path.exists():path.chmod(0o755)
            print(json.dumps({'verified':True,'files':len(manifest['files']),'created_at':manifest['created_at']}))
            return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--watch',action='store_true');parser.add_argument('--verify',type=Path);parser.add_argument('--key',type=Path);parser.add_argument('--into',type=Path);parser.add_argument('--empty-output',action='store_true');parser.add_argument('--prune-only',action='store_true')
    args=parser.parse_args()
    if args.prune_only:
        with Path('/backups/.backup.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            print(json.dumps(prune_backups(Path('/backups'))))
    elif args.verify:
        if not args.key:parser.error('--key required')
        verify(args.verify,args.key,args.into,args.empty_output)
    else:
        while True:
            try:backup()
            except Exception as exc:
                # Do not leak pg_dump connection settings or SMTP/deployment configuration.
                print('Backup failed: '+type(exc).__name__,flush=True)
                if not args.watch:raise SystemExit(1)
                time.sleep(60);continue
            if not args.watch:break
            time.sleep(int(os.environ.get('BACKUP_INTERVAL','86400')))

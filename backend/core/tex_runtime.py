"""Bound each compiler job's time, logs and aggregate temporary disk use."""
import fcntl,os,re,shutil,signal,stat,subprocess,tempfile,time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


def prune_jobs(directory):
    directory=Path(directory);removed=0
    if not directory.exists() or directory.is_symlink():return {'removed':0}
    for path in directory.iterdir():
        descriptor=None
        try:
            if path.is_symlink() or not path.is_dir() or not re.fullmatch(r'job-[0-9a-f]{32}',path.name):continue
            # The grace period covers the tiny gap between mkdir and acquiring the lease.
            if time.time()-path.stat().st_mtime<60:continue
            descriptor=os.open(path/'.lease',os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
            fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
            shutil.rmtree(path);removed+=1
        except (OSError,BlockingIOError):pass
        finally:
            if descriptor is not None:os.close(descriptor)
    return {'removed':removed}


@contextmanager
def job_directory(directory=None):
    directory=Path(directory or Path(tempfile.gettempdir())/'plusfolio-tex-jobs')
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    if directory.is_symlink():raise ValueError('Некорректный каталог временных сборок.')
    prune_jobs(directory);work=directory/('job-'+uuid4().hex);work.mkdir(mode=0o700)
    descriptor=os.open(work/'.lease',os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        fcntl.flock(descriptor,fcntl.LOCK_EX)
        yield work
    finally:
        try:shutil.rmtree(work)
        finally:os.close(descriptor)


def check_workspace(work,max_bytes=64*1024*1024,max_entries=2048):
    """Stream files with one stat per entry and at most one open directory iterator."""
    total=0;count=0;pending=[os.fspath(work)]
    while pending:
        try:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    try:info=entry.stat(follow_symlinks=False)
                    except FileNotFoundError:continue  # Intermediates can disappear during a scan.
                    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):continue
                    count+=1;total+=info.st_size if stat.S_ISREG(info.st_mode) else 0
                    if count>max_entries or total>max_bytes:
                        raise ValueError('Временные файлы TeX превысили лимит 64 МиБ или 2048 файлов/каталогов. Упростите исходник.')
                    if stat.S_ISDIR(info.st_mode):pending.append(entry.path)
        except FileNotFoundError:continue
    return {'bytes':total,'entries':count}


def run_compiler(command,work,env,seconds=20,max_bytes=64*1024*1024):
    work=Path(work);output=work/'compiler-output.log';started=time.monotonic()
    with output.open('wb') as log:
        process=subprocess.Popen(command,cwd=work,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            while True:
                try:process.wait(timeout=.2);break
                except subprocess.TimeoutExpired:pass
                check_workspace(work,max_bytes)
                if time.monotonic()-started>seconds:raise ValueError('Сборка TeX превысила 20 секунд. Упростите рисунок или исходник.')
            check_workspace(work,max_bytes)
        except BaseException:
            try:
                if process.poll() is None:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait();raise
    with output.open('rb') as stream:payload=stream.read(2*1024*1024)
    return process.returncode,payload

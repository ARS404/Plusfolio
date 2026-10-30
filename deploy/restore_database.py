"""Restore a verified pg_dump into an empty, explicitly selected fresh database only."""
import os,re,subprocess,sys
from pathlib import Path
from tempfile import TemporaryDirectory
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from django.conf import settings
from django.db import connection,transaction
from django.utils import timezone

if settings.DEMO:raise RuntimeError('This restore command is only for the server PostgreSQL database')
with connection.cursor() as cursor:
    cursor.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='core_user')")
    if cursor.fetchone()[0]:raise RuntimeError('Refusing to overwrite an initialized database; use a fresh deployment')
with TemporaryDirectory(prefix='plusfolio-restore-',dir=settings.LOCAL_DIR) as temporary:
    dump=Path(temporary)/'database.dump'
    with dump.open('wb') as target:
        import shutil;shutil.copyfileobj(sys.stdin.buffer,target,1024*1024)
    env=os.environ.copy();env['PGPASSWORD']=settings.DATABASES['default']['PASSWORD']
    listing=subprocess.check_output(['pg_restore','--list',str(dump)],env=env,text=True)
    # Extensions and the public schema are initialized by the database administrator.
    # Application restore must neither drop them nor change their ownership/comments.
    keep=Path(temporary)/'restore.list'
    keep.write_text('\n'.join(line for line in listing.splitlines() if not re.search(r'\b(?:EXTENSION|SCHEMA)\b',line)))
    result=subprocess.run(['pg_restore','--host',env['POSTGRES_HOST'],'--username',env['POSTGRES_USER'],
        '--dbname',env['POSTGRES_DB'],'--no-owner','--no-privileges','--exit-on-error','--use-list',str(keep),str(dump)],
        env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    if result.returncode:raise RuntimeError('Database restore failed; discard this fresh instance and retry from verified backup')
connection.close()
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('DELETE FROM django_session')
        cursor.execute('UPDATE core_apitoken SET revoked_at=%s WHERE revoked_at IS NULL',[timezone.now()])
        cursor.execute("UPDATE core_invitation SET state='revoked' WHERE state='pending'")
        cursor.execute("UPDATE core_emailoutbox SET state='cancelled',locked_until=NULL WHERE state IN ('queued','retry')")
print('Database restored; previous sessions, API tokens and pending invitations were revoked.')

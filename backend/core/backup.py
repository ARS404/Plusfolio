"""Encrypted local-demo recovery bundles. Production PostgreSQL uses the documented PITR plan."""
import hashlib,io,json,os,shutil,sqlite3,zipfile
from pathlib import Path
from datetime import datetime,timezone
from tempfile import TemporaryDirectory
from cryptography.fernet import Fernet
from django.conf import settings
from django.db import connection
from .release import release_info

EXCLUDE={'.git','.deploy','.local','node_modules','__pycache__','.venv'}
CHUNK_SIZE=1024*1024

def source_files():
    # Prune ignored trees before traversal, rather than visiting every dependency file.
    for directory,children,names in os.walk(settings.BASE_DIR):
        children[:]=[name for name in children if name not in EXCLUDE]
        for name in names:
            path=Path(directory)/name
            if name not in EXCLUDE and path.is_file() and path.suffix not in {'.pyc','.pfb'}:
                yield str(path.relative_to(settings.BASE_DIR)),path
    for name in ['tools','tectonic-cache','tectonic-config','embedding-model']:
        for path in (settings.LOCAL_DIR/name).rglob('*'):
            if path.is_file() and not path.is_symlink():yield '.local/'+str(path.relative_to(settings.LOCAL_DIR)),path

def write_file(archive,name,path):
    checksum=hashlib.sha256()
    with path.open('rb') as source,archive.open(name,'w',force_zip64=True) as target:
        for chunk in iter(lambda:source.read(CHUNK_SIZE),b''):
            target.write(chunk);checksum.update(chunk)
    return checksum.hexdigest()

def backup_cipher():
    path=settings.LOCAL_DIR/'backup.key'
    if not path.exists():path.write_bytes(Fernet.generate_key());path.chmod(0o600)
    return Fernet(path.read_bytes().strip())
def create_bundle(destination):
    if not settings.DEMO or connection.vendor!='sqlite':raise ValueError('Команда предназначена только для локальной SQLite-демки.')
    connection.ensure_connection()
    with TemporaryDirectory() as directory:
        snapshot=Path(directory)/'snapshot.sqlite3'
        target=sqlite3.connect(snapshot)
        connection.connection.backup(target);target.close()
        manifest={'release':release_info(),'format':'plusfolio-demo-v1','created_at':datetime.now(timezone.utc).isoformat(),'files':{},'database':'sqlite','mail_policy':'disabled_after_restore'}
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
            manifest['files']['.local/demo.sqlite3']=write_file(archive,'.local/demo.sqlite3',snapshot)
            key=settings.SECRET_KEY.encode();archive.writestr('.local/app.key',key)
            manifest['files']['.local/app.key']=hashlib.sha256(key).hexdigest()
            for name,path in source_files():manifest['files'][name]=write_file(archive,name,path)
            archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
        destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(backup_cipher().encrypt(buffer.getvalue()));destination.chmod(0o600)
    return manifest
def verify_bundle(path,key_path):
    payload=Fernet(Path(key_path).read_bytes().strip()).decrypt(Path(path).read_bytes())
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        if manifest.get('format')!='plusfolio-demo-v1':raise ValueError('Неизвестный формат.')
        if set(archive.namelist())!=set(manifest['files'])|{'manifest.json'}:raise ValueError('Манифест не соответствует файлам.')
        for name,checksum in manifest['files'].items():
            if Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('Недопустимый путь в архиве.')
            with archive.open(name) as source:
                if hashlib.file_digest(source,'sha256').hexdigest()!=checksum:raise ValueError('Контрольная сумма не совпала.')
        with TemporaryDirectory() as directory:
            database=Path(directory)/'verify.sqlite3';database.write_bytes(archive.read('.local/demo.sqlite3'))
            db=sqlite3.connect(database)
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Нарушена целостность БД.')
            manifest['users']=db.execute('SELECT count(*) FROM core_user').fetchone()[0]
            manifest['topics']=db.execute('SELECT count(*) FROM core_topic').fetchone()[0]
            db.close()
    return manifest,payload
def restore_bundle(path,key_path,destination):
    manifest,payload=verify_bundle(path,key_path)
    destination=Path(destination)
    if destination.exists():raise ValueError('Для восстановления нужна новая пустая папка.')
    destination.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for name in manifest['files']:
            file=destination/name;file.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(name) as source,file.open('wb') as target:shutil.copyfileobj(source,target,CHUNK_SIZE)
    (destination/'.local/app.key').chmod(0o600)
    compiler=destination/'.local/tools/tectonic'
    if compiler.exists():compiler.chmod(0o755)
    db=sqlite3.connect(destination/'.local/demo.sqlite3')
    db.execute('DELETE FROM django_session')
    revoke_restored_api_tokens(db)
    db.execute("UPDATE core_invitation SET state='revoked' WHERE state='pending'")
    db.execute("UPDATE core_emailoutbox SET state='cancelled'")
    db.commit();db.close()
    return manifest


def revoke_restored_api_tokens(db):
    # Older backups do not contain this table. Restored credentials must never revive.
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='core_apitoken'").fetchone():
        db.execute('UPDATE core_apitoken SET revoked_at=? WHERE revoked_at IS NULL', (datetime.now(timezone.utc).isoformat(),))

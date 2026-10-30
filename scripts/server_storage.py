"""Independent storage locations; never create a missing mount or move existing data."""
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

PATHS = [('DB_DATA_DIR', 'DB_MOUNTPOINT', 'database'), ('BACKUP_DIR', 'BACKUP_MOUNTPOINT', 'backups')]


def validate(values):
    if values.get('BUILD_CACHE_REGISTRY') and not re.fullmatch(r'[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+',values['BUILD_CACHE_REGISTRY']):
        raise ValueError('Некорректный BUILD_CACHE_REGISTRY')
    for directory, mount, _ in PATHS:
        for key in [directory, mount]:
            if values.get(key) and (not Path(values[key]).is_absolute() or any(c in str(values[key]) for c in '\n\r,:')):
                raise ValueError(key + ': укажите абсолютный путь без перевода строки, запятых и двоеточий')
        if values.get(mount) and not values.get(directory):
            raise ValueError(mount + ' требует ' + directory)
    if values.get('POSTGRES_HOST', 'db') != 'db':
        if values.get('DB_DATA_DIR'):
            raise ValueError('Для внешней БД DB_DATA_DIR не используется')
        if values.get('PGSSLMODE') != 'verify-full':
            raise ValueError('Для внешней БД требуется PGSSLMODE=verify-full и доверенный CA')
        if not str(values.get('POSTGRES_PORT', '5432')).isdigit() or not 1 <= int(values.get('POSTGRES_PORT', '5432')) <= 65535:
            raise ValueError('Некорректный порт PostgreSQL')
    if values.get('BACKUP_S3_BUCKET'):
        address = urlsplit(values.get('BACKUP_S3_ENDPOINT', 'https://storage.yandexcloud.net'))
        if address.scheme != 'https' or not address.hostname or address.username or address.password or address.query or address.fragment or address.path not in {'', '/'}:
            raise ValueError('BACKUP_S3_ENDPOINT: нужен HTTPS-адрес S3 без пути и учётных данных')
        prefix = values.get('BACKUP_S3_PREFIX', '')
        if not prefix or prefix.startswith('/') or '..' in prefix.split('/'):
            raise ValueError('Задайте отдельный непустой BACKUP_S3_PREFIX для этого экземпляра')
        if values.get('BACKUP_S3_STORAGE_CLASS', 'STANDARD') not in {'STANDARD', 'COLD', 'STANDARD_IA'}:
            raise ValueError('Класс бэкапов: STANDARD, COLD или STANDARD_IA')


def compose_files(values, root):
    files = [Path(root) / 'compose.yml']
    for key, name in [('DB_DATA_DIR', 'database-disk'), ('BACKUP_DIR', 'backup-disk'), ('BACKUP_S3_BUCKET', 's3')]:
        if values.get(key):files.append(Path(root) / 'deploy' / ('compose.' + name + '.yml'))
    if values.get('POSTGRES_HOST', 'db') != 'db':files.append(Path(root) / 'deploy/compose.external-db.yml')
    return files


def check_paths(values, docker, config):
    for directory, mount, volume in PATHS:
        path = values.get(directory)
        if path:
            target = Path(path)
            if not target.is_dir() or target.is_symlink():
                raise RuntimeError(directory + ': каталог должен уже существовать и не быть симлинком')
            if values.get(mount):
                point = Path(values[mount])
                if not os.path.ismount(point) or not target.resolve().is_relative_to(point.resolve()):
                    raise RuntimeError(mount + ': диск не смонтирован либо каталог расположен вне него; запуск отменён')
        # A named volume's driver options cannot be changed in place. Refuse to
        # accidentally keep using an old disk when configuration points elsewhere.
        spec = config.get('volumes', {}).get(volume)
        if not spec:continue
        import subprocess, json
        try:result = docker('volume', 'inspect', spec['name'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:continue  # first deployment, no volume yet
        actual = (json.loads(result.stdout)[0].get('Options') or {}).get('device', '')
        if actual != (path or ''):
            raise RuntimeError('Размещение volume ' + volume + ' изменилось. Перенесите данные отдельно; существующий volume не изменён')


def configuration(data):
    """Public settings plus source files to copy into the private secret directory."""
    values = {};files = {}
    for key in [item for directory, mount, _ in PATHS for item in [directory, mount]] + ['BUILD_CACHE_REGISTRY']:
        if key.lower() in data:values[key] = str(data[key.lower()])
    database = data.get('database')
    if database:
        cursors=database.get('disable_server_side_cursors',str(database.get('port',5432))=='6432')
        if type(cursors) is not bool:raise ValueError('disable_server_side_cursors должен быть true или false')
        values.update(POSTGRES_HOST=database['host'], POSTGRES_PORT=str(database.get('port',5432)),
            POSTGRES_DB=database['name'], POSTGRES_USER=database['user'], PGSSLMODE='verify-full',
            PGSSLROOTCERT='/run/secrets/db_ca', POSTGRES_DISABLE_SERVER_SIDE_CURSORS='1' if cursors else '0')
        files.update(db_password=Path(database['password_file']), db_ca=Path(database['ca_file']))
    storage = data.get('backup_s3')
    if storage:
        values.update(BACKUP_S3_BUCKET=storage['bucket'], BACKUP_S3_PREFIX=storage['prefix'],
            BACKUP_S3_ENDPOINT=storage.get('endpoint','https://storage.yandexcloud.net'),
            BACKUP_S3_REGION=storage.get('region','ru-central1'), BACKUP_S3_STORAGE_CLASS=storage.get('storage_class','STANDARD'))
        files['backup_s3_credentials'] = Path(storage['credentials_file'])
    validate(values)
    for name, path in files.items():
        if not path.is_file() or path.is_symlink():raise ValueError('Нет обычного файла для ' + name)
    if 'backup_s3_credentials' in files:
        import json
        credentials=json.loads(files['backup_s3_credentials'].read_text())
        if not all(isinstance(credentials.get(key),str) and credentials[key] for key in ['access_key_id','secret_access_key']):
            raise ValueError('S3 credentials: укажите access_key_id и secret_access_key')
    return values,files


def for_restore(values):
    # A recovered checkout must never reconnect to the old live database, disks,
    # or backup prefix. The operator explicitly attaches new locations afterwards.
    return {key:value for key,value in values.items() if key not in
            {item for directory,mount,_ in PATHS for item in [directory,mount]} and
            not key.startswith(('POSTGRES_','PGSSL','PGTARGET','BACKUP_S3_'))}

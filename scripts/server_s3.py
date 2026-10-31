"""Encrypted backup transport. Bucket policy owns remote retention; no delete permission needed."""
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def stored_checksum(response):
    # Object metadata names are HTTP headers. Yandex returns `Sha256`, while
    # other S3 implementations commonly return `sha256`.
    return {key.lower():value for key,value in response.get('Metadata',{}).items()}.get('sha256')


def client(values=None):
    import boto3
    from botocore.config import Config
    values = os.environ if values is None else values
    credentials = json.loads(Path(values['BACKUP_S3_CREDENTIALS_FILE']).read_text())
    return boto3.client('s3', endpoint_url=values.get('BACKUP_S3_ENDPOINT', 'https://storage.yandexcloud.net'),
        region_name=values.get('BACKUP_S3_REGION', 'ru-central1'),
        aws_access_key_id=credentials['access_key_id'], aws_secret_access_key=credentials['secret_access_key'],
        config=Config(signature_version='s3v4', connect_timeout=10, read_timeout=60,
                      retries={'max_attempts':3,'mode':'standard'}, request_checksum_calculation='when_required',
                      response_checksum_validation='when_required'))


def upload(path, values=None):
    from boto3.s3.transfer import TransferConfig
    from botocore.exceptions import ClientError
    values = os.environ if values is None else values
    if not values.get('BACKUP_S3_BUCKET'):return None
    path = Path(path)
    with path.open('rb') as stream:checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    bucket = values['BACKUP_S3_BUCKET'];key = values['BACKUP_S3_PREFIX'].rstrip('/') + '/' + path.name
    s3 = client(values)
    # A previous PUT may have completed before its response was lost. Reuse the
    # immutable object instead of creating another full version on every retry.
    try:existing=s3.head_object(Bucket=bucket,Key=key)
    except ClientError as error:
        if error.response.get('ResponseMetadata',{}).get('HTTPStatusCode')!=404:raise
    else:
        if existing['ContentLength']!=path.stat().st_size or stored_checksum(existing)!=checksum:
            raise RuntimeError('S3 backup name already exists with different content')
        return 's3://' + bucket + '/' + key
    # One transfer thread and bounded parts fit the existing backup memory limit.
    s3.upload_file(str(path), bucket, key,
        ExtraArgs={'StorageClass':values.get('BACKUP_S3_STORAGE_CLASS','STANDARD'),'Metadata':{'sha256':checksum}},
        Config=TransferConfig(use_threads=False, multipart_chunksize=8*1024*1024))
    head = s3.head_object(Bucket=bucket, Key=key)
    if head['ContentLength'] != path.stat().st_size or stored_checksum(head) != checksum:
        raise RuntimeError('Проверка загруженного S3-бэкапа не прошла')
    return 's3://' + bucket + '/' + key


def download(uri, destination, values):
    address = urlsplit(uri)
    prefix = values.get('BACKUP_S3_PREFIX', '').rstrip('/') + '/'
    key = address.path.lstrip('/')
    if address.scheme != 's3' or address.netloc != values.get('BACKUP_S3_BUCKET') or not key.startswith(prefix) or not key.endswith('.tar.gz.age') or '..' in key.split('/'):
        raise ValueError('Укажите s3:// URI бэкапа из настроенного бакета и префикса этого экземпляра')
    destination = Path(destination)
    # Exclusive creation prevents overwriting an existing recovery archive.
    with destination.open('xb') as target:
        try:
            response = client(values).get_object(Bucket=address.netloc, Key=key)
            digest = hashlib.sha256();size = 0
            with response['Body'] as source:
                for chunk in iter(lambda:source.read(1024*1024), b''):
                    target.write(chunk);digest.update(chunk);size += len(chunk)
            if size != response['ContentLength'] or digest.hexdigest() != stored_checksum(response):
                raise RuntimeError('Контрольная сумма S3-бэкапа не совпала')
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    destination.chmod(0o600)
    return destination

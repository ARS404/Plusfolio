"""Publish and consume immutable OCI releases independently of the runtime server."""
import hashlib
import json
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

IMAGES = {'app':'PLUSFOLIO_APP_IMAGE', 'tex':'PLUSFOLIO_TEX_IMAGE', 'embeddings':'PLUSFOLIO_EMBEDDINGS_IMAGE'}
TARGETS = {'app':'web', 'tex':'tex', 'embeddings':'embeddings'}


def manifest(path, root):
    from release import build_metadata
    data=json.loads(Path(path).read_text())
    if data.get('format')!='plusfolio-images-v1' or data.get('release')!=build_metadata(root):
        raise ValueError('Манифест образов должен соответствовать версии и чистому commit текущего checkout')
    if data.get('platform') not in {'linux/amd64','linux/arm64'} or set(data.get('images',{}))!=set(IMAGES):
        raise ValueError('Некорректная платформа или набор образов')
    if any(not isinstance(image,str) or not re.fullmatch(r'[a-zA-Z0-9._:/-]+@sha256:[0-9a-f]{64}',image) for image in data['images'].values()):
        raise ValueError('Образы должны быть закреплены полными sha256 digest')
    return data


def pull(docker, root, path):
    data=manifest(path,root)
    for image in data['images'].values():
        docker('pull',image)
        info=json.loads(docker('image','inspect',image,stdout=subprocess.PIPE).stdout)[0]
        labels=info.get('Config',{}).get('Labels') or {}
        expected=data['release']
        if (labels.get('org.opencontainers.image.version')!=expected['version'] or
                labels.get('org.opencontainers.image.revision')!=expected['revision'] or
                labels.get('io.plusfolio.release-status')!=expected['status'] or
                info.get('Os')+'/'+info.get('Architecture')!=data['platform']):
            raise ValueError('Метки или платформа загруженного образа не соответствуют манифесту')
    return {key:data['images'][kind] for kind,key in IMAGES.items()}


def publish(docker, root, registry, output, platform='linux/amd64', cache_registry=None):
    import server_host
    from release import check,build_metadata
    check(root);release=build_metadata(root)
    if not re.fullmatch(r'[0-9a-f]{40,64}',release['revision']):
        raise ValueError('Публикуйте образы из чистого Git checkout с известным commit')
    if not re.fullmatch(r'[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+',registry) or platform not in {'linux/amd64','linux/arm64'}:
        raise ValueError('Укажите OCI registry/repository и linux/amd64 либо linux/arm64')
    server_host.tools_ready(True)
    registry=registry.rstrip('/')
    values=server_host.shared_values({'COMPOSE_PROJECT_NAME':'plusfolio-publish-'+hashlib.sha256(str(root).encode()).hexdigest()[:8],
        'INSTANCE_ID':'publish-'+hashlib.sha256(registry.encode()).hexdigest(),'PUBLIC_URL':'https://localhost','PUBLIC_HOST':'localhost',
        'ADMIN_EMAIL':'build@example.test','SMTP_HOST':'unused','SMTP_FROM':'build@example.test',
        **{key:registry+'/'+kind+':'+release['revision'] for kind,key in IMAGES.items()},
        **({'BUILD_CACHE_REGISTRY':cache_registry} if cache_registry else {})})
    with TemporaryDirectory(prefix='plusfolio-image-metadata-') as directory:
        metadata=Path(directory)/'images.json'
        server_host.build_images(docker,values,root,push=True,metadata=metadata,platform=platform)
        built=json.loads(metadata.read_text())
        images={kind:registry+'/'+kind+'@'+built[target]['containerimage.digest'] for kind,target in TARGETS.items()}
    data={'format':'plusfolio-images-v1','release':release,'platform':platform,'images':images}
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(data,indent=2)+'\n')
    manifest(output,root)
    print('Published immutable image manifest: '+str(output))
    return data


def export_archive(docker, images, output):
    # Docker save drops RepoDigests. Recovery tags preserve offline usability on
    # a fresh engine, where the original registry may be unavailable.
    output=Path(output);index=output.with_suffix(output.suffix+'.json')
    if output.exists() or index.exists():raise ValueError('Архив образов или его манифест уже существует')
    entries={}
    for image in sorted(set(images)):
        info=json.loads(docker('image','inspect',image,stdout=subprocess.PIPE).stdout)[0]
        tag='plusfolio-recovery/image:'+hashlib.sha256(image.encode()).hexdigest()
        docker('image','tag',image,tag)
        entries[image]={'tag':tag,'id':info['Id']}
    docker('image','save','--output',str(output),*(item['tag'] for item in entries.values()))
    output.chmod(0o600)
    with output.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
    index.write_text(json.dumps({'format':'plusfolio-image-archive-v1','sha256':checksum,'images':entries},indent=2)+'\n')
    index.chmod(0o600)
    print('Keep image archive and '+index.name+' together.')


def import_archive(docker, archive):
    archive=Path(archive);data=json.loads(archive.with_suffix(archive.suffix+'.json').read_text())
    if data.get('format')!='plusfolio-image-archive-v1' or not isinstance(data.get('images'),dict) or not data['images']:
        raise ValueError('Неизвестный манифест архива образов')
    for item in data['images'].values():
        if not re.fullmatch(r'plusfolio-recovery/image:[0-9a-f]{64}',item['tag']) or not re.fullmatch(r'sha256:[0-9a-f]{64}',item['id']):
            raise ValueError('Некорректный образ восстановления')
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=data.get('sha256'):raise ValueError('Контрольная сумма архива образов не совпала')
    def present(item):
        try:info=json.loads(docker('image','inspect',item['tag'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL).stdout)[0]
        except subprocess.CalledProcessError:return False
        return info['Id']==item['id']
    if not all(present(item) for item in data['images'].values()):docker('image','load','--input',str(archive))
    if not all(present(item) for item in data['images'].values()):raise ValueError('Загруженные образы не соответствуют архиву')
    return {image:item['tag'] for image,item in data['images'].items()}

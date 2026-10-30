#!/usr/bin/env python3
"""One-command server setup. Secrets are read from prompts/files, never CLI arguments."""
import argparse,getpass,hashlib,json,os,re,secrets,subprocess,sys,time,urllib.parse,urllib.request,ssl
import server_host,server_storage
from email.utils import parseaddr
from pathlib import Path
from collections.abc import Mapping
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'.deploy'

INSTALLED_VERSION_CODE = """import json,sys
from pathlib import Path
if Path('backend/core/release.py').is_file():
    sys.path.insert(0,'backend')
    from core.release import release_info
    print(json.dumps(release_info()))
else:
    print(json.dumps({'version':None,'status':'unversioned','revision':'unknown'}))
"""


BACKUP_BEFORE_UPDATE_CODE = """import sys,time
sys.path.insert(0,'scripts')
from server_backup import backup
until=time.monotonic()+900
while backup() is None:
    if time.monotonic()>until:raise RuntimeError('Backup stayed busy; update cancelled')
    time.sleep(2)
"""


def docker(*args,**kwargs):return subprocess.run(['docker',*args],cwd=ROOT,check=True,**kwargs)

def compose(*args,**kwargs):
    values=read_env()
    kwargs.setdefault('env',{**os.environ,**{key:str(value) for key,value in values.items()}})
    files=[argument for path in server_storage.compose_files(values,ROOT) for argument in ['-f',str(path)]]
    return subprocess.run(['docker','compose','--project-name',values['COMPOSE_PROJECT_NAME'],'--env-file',str(STATE/'env'),*files,*args],cwd=ROOT,check=True,**kwargs)

def write_env(values: Mapping[str, object], path: Path | None = None) -> None:
    target = STATE/'env' if path is None else path
    if target.exists():target.chmod(0o600)
    target.write_text(''.join(key+'='+json.dumps(str(value),ensure_ascii=False)+'\n' for key,value in sorted(values.items())))
    target.chmod(0o444)

def read_env(path: Path | None = None) -> dict[str, object]:
    target = STATE/'env' if path is None else path
    values: dict[str, object] = {}
    for line in target.read_text().splitlines():
        if line and not line.startswith('#'):
            key,value=line.split('=',1);values[key]=json.loads(value)
    return values

def configure(config=None):
    STATE.mkdir(mode=0o700,exist_ok=True);STATE.chmod(0o700)
    if (STATE/'env').exists():
        previous=read_env()
        return server_host.shared_values(previous,legacy=previous.get('DEPLOYMENT_MODE')!='shared')
    data=json.loads(Path(config).read_text()) if config else {}
    def ask(key,prompt,default=''):
        if key in data:return str(data[key])
        return input(prompt+(f' [{default}]' if default else '')+': ').strip() or default
    url=ask('public_url','Адрес сайта с https://').rstrip('/')
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('Нужен HTTPS-адрес без пути, например https://plusfolio.example.ru')
    ascii_host=parsed.hostname.encode('idna').decode()
    url=urllib.parse.urlunsplit(('https',ascii_host+(':'+str(parsed.port) if parsed.port else ''),'','',''))
    parsed=urllib.parse.urlsplit(url)
    admin=ask('admin_email','Email первого администратора')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',admin):raise ValueError('Некорректный email администратора')
    admin_name=ask('admin_name','Имя администратора','Администратор')
    password=data.get('admin_password') or getpass.getpass('Пароль администратора (минимум 12 символов): ')
    if len(password)<12:raise ValueError('Пароль администратора — минимум 12 символов')
    host=ask('smtp_host','SMTP-хост')
    port=ask('smtp_port','SMTP-порт','587')
    if not host or not port.isdigit() or not 1<=int(port)<=65535:raise ValueError('Проверьте SMTP-хост/порт')
    user=ask('smtp_user','SMTP-логин (пусто, если авторизация не нужна)')
    sender=ask('smtp_from','Адрес отправителя',admin)
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',parseaddr(sender)[1]) or any(character in sender for character in '\r\n'):
        raise ValueError('Некорректный адрес отправителя')
    smtp_password=data.get('smtp_password') if 'smtp_password' in data else getpass.getpass('SMTP-пароль (ввод скрыт): ')
    ssl_mode=str(data.get('smtp_ssl','1' if port=='465' else '0'))
    tls=str(data.get('smtp_tls','0' if ssl_mode=='1' else '1'))
    if tls=='1' and ssl_mode=='1':raise ValueError('Выберите STARTTLS или SSL, не оба')
    local_port=ask('local_port','Локальный порт Plusfolio (только 127.0.0.1)','18080')
    project=data.get('project','plusfolio-'+hashlib.sha256(str(ROOT).encode()).hexdigest()[:8])
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*',project):raise ValueError('Некорректное имя проекта')
    values={'INSTANCE_ID':secrets.token_hex(16),'COMPOSE_PROJECT_NAME':project,'PUBLIC_URL':url,'PUBLIC_HOST':parsed.hostname,'ADMIN_EMAIL':admin,'ADMIN_NAME':admin_name,
        'SMTP_HOST':host,'SMTP_PORT':port,'SMTP_USER':user,'SMTP_FROM':sender,'SMTP_TLS':tls,'SMTP_SSL':ssl_mode,
        'LOCAL_PORT':local_port}
    extra,files=server_storage.configuration(data)
    values=server_host.shared_values({**values,**extra})
    (STATE/'secrets').mkdir(mode=0o700,exist_ok=True)
    for name,value in {'app_key':secrets.token_urlsafe(64),'postgres_password':secrets.token_urlsafe(32),
        'db_password':secrets.token_urlsafe(32),'admin_password':password,'smtp_password':smtp_password or ''}.items():
        path=STATE/'secrets'/name
        path.write_text(value)
        # Host parent directories are 0700. Container-local Compose secrets are readable
        # by its unprivileged application UID, without exposing parent paths on host.
        path.chmod(0o444)
    for name,source in files.items():
        path=STATE/'secrets'/name
        if path.exists():path.chmod(0o600)
        path.write_bytes(source.read_bytes());path.chmod(0o444)
    write_env(values);return values


def backup_key(values):
    path=STATE/'backup.key'
    image=values.get('PLUSFOLIO_APP_IMAGE','plusfolio-app:local')
    if not path.exists():
        with path.open('wb') as stream:docker('run','--rm','--network','none','--cpus','0.25','--memory','256m','--memory-swap','256m','--pids-limit','64','--entrypoint','age-keygen',image,stdout=stream)
        path.chmod(0o600)
    with path.open('rb') as stream:
        result=docker('run','--rm','-i','--network','none','--cpus','0.25','--memory','256m','--memory-swap','256m','--pids-limit','64','--entrypoint','age-keygen',image,'-y',stdin=stream,stdout=subprocess.PIPE)
    values['BACKUP_RECIPIENT']=result.stdout.decode().strip();write_env(values)


def verify_external(values):
    context=None
    if values['PUBLIC_HOST']=='localhost':
        target=STATE/'local-ca.crt'
        target.unlink(missing_ok=True)
        for _ in range(30):
            try:compose('cp','proxy:/data/caddy/pki/authorities/local/root.crt',str(target),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            except subprocess.CalledProcessError:pass
            if target.exists():break
            time.sleep(1)
        context=ssl.create_default_context(cafile=str(target))
    for attempt in range(30):
        try:
            with urllib.request.urlopen(values['PUBLIC_URL']+'/healthz',context=context,timeout=10) as response:
                body=json.load(response)
                if response.status==200 and body['ok'] and body.get('instance')==values.get('INSTANCE_ID'):return
        except Exception:
            if attempt==29:raise RuntimeError('HTTPS readiness failed. Check domain DNS and ports 80/443, then run up again.')
            time.sleep(2)


def preflight(values,require_build=False):
    server_host.tools_ready(require_build)
    containers=server_host.project_containers(docker,values,ROOT)
    config=json.loads(compose('config','--format','json',stdout=subprocess.PIPE).stdout)
    server_storage.validate(values)
    server_storage.check_paths(values,docker,config)
    budget=server_host.check_limits(config)
    published=config['services']['web']['ports']
    if len(published)!=1 or str(published[0]['published'])!=str(values['LOCAL_PORT']):raise RuntimeError('Порт в Compose не совпадает с LOCAL_PORT')
    server_host.port_available(values['LOCAL_PORT'],containers)
    return containers,budget


def verify_local(values):
    url='http://127.0.0.1:'+str(values['LOCAL_PORT'])+'/healthz'
    for attempt in range(30):
        try:
            with urllib.request.urlopen(url,timeout=10) as response:
                body=json.load(response)
                if response.status==200 and body.get('ok') and body.get('instance')==values['INSTANCE_ID']:return url
        except Exception:pass
        if attempt==29:raise RuntimeError('Локальная проверка готовности не прошла. Проверьте logs и LOCAL_PORT.')
        time.sleep(2)


def run(args):
    release=getattr(args,'release',None)
    require_build=args.command in {'init','update'} and not getattr(args,'no_build',False) and not release
    if args.command=='publish-images':
        from server_images import publish
        publish(docker,ROOT,args.registry,args.output,args.platform,args.cache_registry);return
    if args.command=='fetch-backup':
        from server_s3 import download
        if args.config:
            values,files=server_storage.configuration(json.loads(Path(args.config).read_text()))
            values['BACKUP_S3_CREDENTIALS_FILE']=str(files['backup_s3_credentials'])
        else:
            values=read_env();values['BACKUP_S3_CREDENTIALS_FILE']=str(STATE/'secrets/backup_s3_credentials')
        try:download(args.uri,args.file,values)
        except (ValueError,FileExistsError):raise
        except Exception:raise RuntimeError('Не удалось скачать S3-бэкап. Проверьте доступ к бакету и настройки восстановления') from None
        print('Encrypted backup downloaded; verify it before restoring.');return
    if args.command=='init':
        server_host.tools_ready(require_build)
        values=configure(args.config)
    elif (STATE/'env').exists():values=read_env()
    elif args.command in {'verify-backup','restore-backup','import-images'}:values={}
    elif args.command=='doctor':
        server_host.tools_ready(True);server_host.port_available('18080',[])
        print('Docker/Compose/Buildx доступны; локальный порт 18080 свободен. Системные настройки не изменены.');return
    else:raise ValueError('Сначала выполните init: конфигурация сервера не найдена')
    if args.command in {'init','up','update','doctor'}:
        values=server_host.shared_values(values,legacy=values.get('DEPLOYMENT_MODE')!='shared')
        if release:
            from server_images import pull
            values.update(pull(docker,ROOT,release))
        containers,budget=preflight(values,require_build)
        print('Лимиты служб: '+str(budget['cpus'])+' CPU, '+str(budget['memory_mib'])+' МиБ памяти (сумма верхних границ).',flush=True)
        if args.command=='doctor':return
        if require_build:server_host.build_images(docker,values,ROOT)
        if args.command=='update' and any(item.get('State',{}).get('Running') and (item.get('Config',{}).get('Labels') or {}).get('com.docker.compose.service')=='web' for item in containers):
            compose('exec','-T','backup','python','-c',BACKUP_BEFORE_UPDATE_CODE)
        write_env(values)
        backup_key(values)
        # Migrate only this checkout's former edge; never touch another project's proxy.
        for item in containers:
            if (item.get('Config',{}).get('Labels') or {}).get('com.docker.compose.service')=='proxy':
                docker('stop',item['Id'],stdout=subprocess.DEVNULL)
        compose('up','--detach','--wait','--wait-timeout','600')
        compose('exec','-T','mail','python','backend/manage.py','check_smtp')
        verify_local(values)
        print('Plusfolio ready locally: http://127.0.0.1:'+values['LOCAL_PORT'])
        print('Connect the existing HTTPS proxy for '+values['PUBLIC_URL']+'; see proxy-config nginx|caddy|traefik, then check-public.')
        print('Save .deploy/backup.key separately; encrypted backups and retention are running.')
    elif args.command=='import-images':
        server_host.tools_ready();operate(args,values)
    elif args.command in {'status','logs','backup','prune-backups','download-backup','export-images','restore-database','stop','version'}:
        server_host.tools_ready()
        server_host.project_containers(docker,values,ROOT)
        operate(args,values)
    elif args.command=='check-public':verify_external(values);print('Public HTTPS verified: '+values['PUBLIC_URL'])
    elif args.command=='proxy-config':print(server_host.proxy_config(server_host.shared_values(values),args.kind))
    else:operate(args,values)


def operate(args,values):
    if args.command=='version':
        compose('exec','-T','web','python','-c',INSTALLED_VERSION_CODE)
    elif args.command=='status':compose('ps')
    elif args.command=='logs':compose('logs','--tail','80',*(args.services or []))
    elif args.command=='backup':compose('exec','-T','backup','python','scripts/server_backup.py')
    elif args.command=='prune-backups':compose('exec','-T','backup','python','scripts/server_backup.py','--prune-only')
    elif args.command=='verify-backup':
        path=Path(args.file).resolve();key=Path(args.key or STATE/'backup.key').resolve()
        docker('run','--rm','--network','none','--cpus','0.25','--memory','256m','--memory-swap','256m','--pids-limit','64','--cap-drop','ALL','--security-opt','no-new-privileges','--user',str(os.getuid())+':'+str(os.getgid()),'--mount',f'type=bind,src={path},dst=/backup.age,readonly',
            '--mount',f'type=bind,src={key},dst=/backup.key,readonly',getattr(args,'image',None) or values.get('PLUSFOLIO_APP_IMAGE','plusfolio-app:local'),
            'python','scripts/server_backup.py','--verify','/backup.age','--key','/backup.key')
    elif args.command=='download-backup':
        destination=Path(args.into).resolve();destination.mkdir(parents=True,exist_ok=True,mode=0o700)
        compose('cp','backup:/backups/.',str(destination))
    elif args.command=='export-images':
        output=Path(args.file).resolve()
        result=compose('config','--images',stdout=subprocess.PIPE)
        from server_images import export_archive
        export_archive(docker,result.stdout.decode().split(),output)
    elif args.command=='import-images':
        from server_images import import_archive,IMAGES,TARGETS
        aliases=import_archive(docker,args.file)
        if values:
            config=json.loads(compose('config','--format','json',stdout=subprocess.PIPE).stdout)
            services={TARGETS[kind]:key for kind,key in IMAGES.items()}
            services.update(db='PLUSFOLIO_DB_IMAGE',redis='PLUSFOLIO_REDIS_IMAGE')
            for name,key in services.items():
                image=config['services'].get(name,{}).get('image')
                if image in aliases:values[key]=aliases[image]
            write_env(values)
        print(json.dumps({'recovery_images':aliases}))
    elif args.command=='restore-backup':
        path=Path(args.file).resolve();key=Path(args.key or STATE/'backup.key').resolve();destination=Path(args.into).resolve()
        if destination.exists():raise ValueError('Restore destination must not exist')
        destination.mkdir(parents=True,mode=0o700)
        docker('run','--rm','--network','none','--cpus','0.25','--memory','256m','--memory-swap','256m','--pids-limit','64','--cap-drop','ALL','--security-opt','no-new-privileges','--user',str(os.getuid())+':'+str(os.getgid()),'--mount',f'type=bind,src={path},dst=/backup.age,readonly',
            '--mount',f'type=bind,src={key},dst=/backup.key,readonly','--mount',f'type=bind,src={destination},dst=/output',
            getattr(args,'image',None) or values.get('PLUSFOLIO_APP_IMAGE','plusfolio-app:local'),'python','scripts/server_backup.py','--verify','/backup.age','--key','/backup.key','--into','/output','--empty-output')
        import shutil
        config=destination/'source/.deploy/env'
        restored=server_storage.for_restore(read_env(config))
        restored['COMPOSE_PROJECT_NAME']='plusfolio-restored-'+str(time.time_ns())
        restored['INSTANCE_ID']=secrets.token_hex(16)
        restored=server_host.shared_values(restored,legacy=restored.get('DEPLOYMENT_MODE')!='shared')
        write_env(restored,config)
        for secret in (destination/'source/.deploy/secrets').iterdir():secret.chmod(0o444)
        shutil.copyfile(key,destination/'source/.deploy/backup.key');(destination/'source/.deploy/backup.key').chmod(0o600)
        print('Verified sources and database restored into '+str(destination))
        print('Run scripts/server.py restore-database '+str(destination/'database.dump')+' from '+str(destination/'source'))
    elif args.command=='restore-database':
        running=compose('ps','--status','running','--services',stdout=subprocess.PIPE).stdout.decode().split()
        if any(name not in {'db','redis'} for name in running):raise ValueError('Stop application workers before restoring; only a fresh database is allowed')
        services=['db','redis'] if values.get('POSTGRES_HOST','db')=='db' else ['redis']
        compose('up','--detach','--wait','--wait-timeout','120',*services)
        with Path(args.file).open('rb') as stream:
            compose('run','--rm','--no-deps','-T','web','python','deploy/restore_database.py',stdin=stream)
        print('Restore complete. Run up to start the recovered service.')
    elif args.command=='stop':compose('stop')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init');init.add_argument('--no-build',action='store_true');init.add_argument('--config',help='JSON file for unattended setup; secrets never go in CLI arguments')
    init.add_argument('--release',type=Path,help='Pull a verified digest-pinned images manifest; no server build')
    update=sub.add_parser('update');update.add_argument('--no-build',action='store_true');update.add_argument('--release',type=Path)
    publish=sub.add_parser('publish-images');publish.add_argument('--registry',required=True);publish.add_argument('--output',type=Path,required=True);publish.add_argument('--platform',default='linux/amd64');publish.add_argument('--cache-registry')
    fetch=sub.add_parser('fetch-backup');fetch.add_argument('uri');fetch.add_argument('file',type=Path);fetch.add_argument('--config',help='Private recovery JSON containing backup_s3 settings')
    for name in ['up','status','backup','prune-backups','stop','doctor','check-public','version']:sub.add_parser(name)
    proxy=sub.add_parser('proxy-config');proxy.add_argument('kind',choices=['nginx','caddy','traefik'])
    logs=sub.add_parser('logs');logs.add_argument('services',nargs='*')
    restore=sub.add_parser('restore-backup');restore.add_argument('file');restore.add_argument('--key');restore.add_argument('--into',required=True);restore.add_argument('--image',help='Loaded application image for recovery on a fresh host')
    database=sub.add_parser('restore-database');database.add_argument('file')
    check=sub.add_parser('verify-backup');check.add_argument('file');check.add_argument('--key');check.add_argument('--image')
    download=sub.add_parser('download-backup');download.add_argument('into')
    export=sub.add_parser('export-images');export.add_argument('file')
    load=sub.add_parser('import-images');load.add_argument('file',type=Path)
    args=parser.parse_args()
    try:run(args)
    except (ValueError,RuntimeError,subprocess.CalledProcessError,KeyError,OSError) as exc:
        print('Setup did not complete: '+(str(exc) if isinstance(exc,(ValueError,RuntimeError)) else 'a deployment command failed; inspect service logs.'),file=sys.stderr)
        raise SystemExit(1)

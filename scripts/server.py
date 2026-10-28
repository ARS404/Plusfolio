#!/usr/bin/env python3
"""One-command server setup. Secrets are read from prompts/files, never CLI arguments."""
import argparse,getpass,hashlib,json,os,re,secrets,subprocess,sys,time,urllib.parse,urllib.request,ssl
import server_host
from email.utils import parseaddr
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'.deploy'


def docker(*args,**kwargs):return subprocess.run(['docker',*args],cwd=ROOT,check=True,**kwargs)

def compose(*args,**kwargs):
    probe=subprocess.run(['docker','compose','version'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    prefix=['docker','compose'] if probe.returncode==0 else ['docker-compose']
    values=read_env()
    kwargs.setdefault('env',{**os.environ,**{key:str(value) for key,value in values.items()}})
    return subprocess.run([*prefix,'--project-name',values['COMPOSE_PROJECT_NAME'],'--env-file',str(STATE/'env'),'-f',str(ROOT/'compose.yml'),*args],cwd=ROOT,check=True,**kwargs)

def write_env(values):
    if (STATE/'env').exists():(STATE/'env').chmod(0o600)
    (STATE/'env').write_text(''.join(key+'='+json.dumps(str(value),ensure_ascii=False)+'\n' for key,value in sorted(values.items())))
    (STATE/'env').chmod(0o444)

def read_env():
    values={}
    for line in (STATE/'env').read_text().splitlines():
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
    values=server_host.shared_values(values)
    (STATE/'secrets').mkdir(mode=0o700,exist_ok=True)
    for name,value in {'app_key':secrets.token_urlsafe(64),'postgres_password':secrets.token_urlsafe(32),
        'db_password':secrets.token_urlsafe(32),'admin_password':password,'smtp_password':smtp_password or ''}.items():
        path=STATE/'secrets'/name
        path.write_text(value)
        # Host parent directories are 0700. Container-local Compose secrets are readable
        # by its unprivileged application UID, without exposing parent paths on host.
        path.chmod(0o444)
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


def save_release():
    result=compose('images','--format','json',stdout=subprocess.PIPE)
    (STATE/'image-lock.json').write_bytes(result.stdout)


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
    require_build=args.command in {'init','update'} and not getattr(args,'no_build',False)
    if args.command=='init':
        server_host.tools_ready(require_build)
        values=configure(args.config)
    elif (STATE/'env').exists():values=read_env()
    elif args.command in {'verify-backup','restore-backup'}:values={}
    elif args.command=='doctor':
        server_host.tools_ready(True);server_host.port_available('18080',[])
        print('Docker/Compose/Buildx доступны; локальный порт 18080 свободен. Системные настройки не изменены.');return
    else:raise ValueError('Сначала выполните init: конфигурация сервера не найдена')
    if args.command in {'init','up','update','doctor'}:
        values=server_host.shared_values(values,legacy=values.get('DEPLOYMENT_MODE')!='shared')
        containers,budget=preflight(values,require_build)
        print('Лимиты служб: '+str(budget['cpus'])+' CPU, '+str(budget['memory_mib'])+' МиБ памяти (сумма верхних границ).',flush=True)
        if args.command=='doctor':return
        write_env(values)
        if require_build:server_host.build_images(docker,values,ROOT)
        backup_key(values)
        # Migrate only this checkout's former edge; never touch another project's proxy.
        for item in containers:
            if (item.get('Config',{}).get('Labels') or {}).get('com.docker.compose.service')=='proxy':
                docker('stop',item['Id'],stdout=subprocess.DEVNULL)
        compose('up','--detach','--wait','--wait-timeout','600')
        compose('exec','-T','mail','python','backend/manage.py','check_smtp')
        verify_local(values);save_release()
        print('Plusfolio ready locally: http://127.0.0.1:'+values['LOCAL_PORT'])
        print('Connect the existing HTTPS proxy for '+values['PUBLIC_URL']+'; see proxy-config nginx|caddy|traefik, then check-public.')
        print('Save .deploy/backup.key separately; encrypted backups and retention are running.')
    elif args.command in {'status','logs','backup','prune-backups','download-backup','export-images','restore-database','stop'}:
        server_host.tools_ready()
        server_host.project_containers(docker,values,ROOT)
        operate(args,values)
    elif args.command=='check-public':verify_external(values);print('Public HTTPS verified: '+values['PUBLIC_URL'])
    elif args.command=='proxy-config':print(server_host.proxy_config(server_host.shared_values(values),args.kind))
    else:operate(args,values)


def operate(args,values):
    if args.command=='status':compose('ps')
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
        names=sorted(set(result.stdout.decode().split()))
        # Preserve image tags so a fresh host can use Compose after image load.
        docker('image','save','--output',str(output),*names);output.chmod(0o600)
    elif args.command=='restore-backup':
        path=Path(args.file).resolve();key=Path(args.key or STATE/'backup.key').resolve();destination=Path(args.into).resolve()
        if destination.exists():raise ValueError('Restore destination must not exist')
        destination.mkdir(parents=True,mode=0o700)
        docker('run','--rm','--network','none','--cpus','0.25','--memory','256m','--memory-swap','256m','--pids-limit','64','--cap-drop','ALL','--security-opt','no-new-privileges','--user',str(os.getuid())+':'+str(os.getgid()),'--mount',f'type=bind,src={path},dst=/backup.age,readonly',
            '--mount',f'type=bind,src={key},dst=/backup.key,readonly','--mount',f'type=bind,src={destination},dst=/output',
            getattr(args,'image',None) or values.get('PLUSFOLIO_APP_IMAGE','plusfolio-app:local'),'python','scripts/server_backup.py','--verify','/backup.age','--key','/backup.key','--into','/output','--empty-output')
        import shutil
        config=destination/'source/.deploy/env'
        restored={name:json.loads(value) for name,value in (line.split('=',1) for line in config.read_text().splitlines() if line)}
        restored['COMPOSE_PROJECT_NAME']='plusfolio-restored-'+str(time.time_ns())
        restored['INSTANCE_ID']=secrets.token_hex(16)
        restored=server_host.shared_values(restored,legacy=restored.get('DEPLOYMENT_MODE')!='shared')
        config.chmod(0o600)
        config.write_text(''.join(name+'='+json.dumps(str(value),ensure_ascii=False)+'\n' for name,value in sorted(restored.items())))
        config.chmod(0o444)
        for secret in (destination/'source/.deploy/secrets').iterdir():secret.chmod(0o444)
        shutil.copyfile(key,destination/'source/.deploy/backup.key');(destination/'source/.deploy/backup.key').chmod(0o600)
        print('Verified sources and database restored into '+str(destination))
        print('Run scripts/server.py restore-database '+str(destination/'database.dump')+' from '+str(destination/'source'))
    elif args.command=='restore-database':
        running=compose('ps','--status','running','--services',stdout=subprocess.PIPE).stdout.decode().split()
        if any(name not in {'db','redis'} for name in running):raise ValueError('Stop application workers before restoring; only a fresh database is allowed')
        compose('up','--detach','--wait','--wait-timeout','120','db','redis')
        with Path(args.file).open('rb') as stream:
            compose('run','--rm','--no-deps','-T','web','python','deploy/restore_database.py',stdin=stream)
        print('Restore complete. Run up to start the recovered service.')
    elif args.command=='stop':compose('stop')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init');init.add_argument('--no-build',action='store_true');init.add_argument('--config',help='JSON file for unattended setup; secrets never go in CLI arguments')
    update=sub.add_parser('update');update.add_argument('--no-build',action='store_true')
    for name in ['up','status','backup','prune-backups','stop','doctor','check-public']:sub.add_parser(name)
    proxy=sub.add_parser('proxy-config');proxy.add_argument('kind',choices=['nginx','caddy','traefik'])
    logs=sub.add_parser('logs');logs.add_argument('services',nargs='*')
    restore=sub.add_parser('restore-backup');restore.add_argument('file');restore.add_argument('--key');restore.add_argument('--into',required=True);restore.add_argument('--image',help='Loaded application image for recovery on a fresh host')
    database=sub.add_parser('restore-database');database.add_argument('file')
    check=sub.add_parser('verify-backup');check.add_argument('file');check.add_argument('--key');check.add_argument('--image')
    download=sub.add_parser('download-backup');download.add_argument('into')
    export=sub.add_parser('export-images');export.add_argument('file')
    args=parser.parse_args()
    try:run(args)
    except (ValueError,RuntimeError,subprocess.CalledProcessError) as exc:
        print('Setup did not complete: '+(str(exc) if isinstance(exc,(ValueError,RuntimeError)) else 'a deployment command failed; inspect service logs.'),file=sys.stderr)
        raise SystemExit(1)

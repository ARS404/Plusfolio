#!/usr/bin/env python3
"""One-command server setup. Secrets are read from prompts/files, never CLI arguments."""
import argparse,getpass,json,os,re,secrets,shlex,subprocess,sys,time,urllib.parse,urllib.request,ssl
from email.utils import parseaddr
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'.deploy'


def docker(*args,**kwargs):return subprocess.run(['docker',*args],cwd=ROOT,check=True,**kwargs)

def compose(*args,**kwargs):
    probe=subprocess.run(['docker','compose','version'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    prefix=['docker','compose'] if probe.returncode==0 else ['docker-compose']
    return subprocess.run([*prefix,'--env-file',str(STATE/'env'),'-f',str(ROOT/'compose.yml'),*args],cwd=ROOT,check=True,**kwargs)

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
    if (STATE/'env').exists():return read_env()
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
    project=data.get('project','plusfolio')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*',project):raise ValueError('Некорректное имя проекта')
    values={'INSTANCE_ID':secrets.token_hex(16),'COMPOSE_PROJECT_NAME':project,'PUBLIC_URL':url,'PUBLIC_HOST':parsed.hostname,'ADMIN_EMAIL':admin,'ADMIN_NAME':admin_name,
        'SMTP_HOST':host,'SMTP_PORT':port,'SMTP_USER':user,'SMTP_FROM':sender,'SMTP_TLS':tls,'SMTP_SSL':ssl_mode,
        'BIND_ADDRESS':data.get('bind_address','0.0.0.0'),'HTTP_PORT':data.get('http_port','80'),'HTTPS_PORT':data.get('https_port','443')}
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
        with path.open('wb') as stream:docker('run','--rm','--network','none','--entrypoint','age-keygen',image,stdout=stream)
        path.chmod(0o600)
    with path.open('rb') as stream:
        result=docker('run','--rm','-i','--network','none','--entrypoint','age-keygen',image,'-y',stdin=stream,stdout=subprocess.PIPE)
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


def run(args):
    if args.command=='init':values=configure(args.config)
    elif (STATE/'env').exists():values=read_env()
    elif args.command in {'verify-backup','restore-backup'}:values={}
    else:raise ValueError('Сначала выполните init: конфигурация сервера не найдена')
    if args.command in {'init','up','update'}:
        compose('config','--quiet')
        if args.command in {'init','update'}:compose('build','--pull')
        backup_key(values)
        compose('up','--detach','--wait','--wait-timeout','600')
        compose('exec','-T','mail','python','backend/manage.py','check_smtp')
        verify_external(values);save_release()
        print('Plusfolio ready: '+values['PUBLIC_URL'])
        print('Save .deploy/backup.key separately; automatic encrypted backups are running.')
    elif args.command=='status':compose('ps')
    elif args.command=='logs':compose('logs','--tail','80',*(args.services or []))
    elif args.command=='backup':compose('exec','-T','backup','python','scripts/server_backup.py')
    elif args.command=='verify-backup':
        path=Path(args.file).resolve();key=Path(args.key or STATE/'backup.key').resolve()
        docker('run','--rm','--network','none','--user','0:0','--mount',f'type=bind,src={path},dst=/backup.age,readonly',
            '--mount',f'type=bind,src={key},dst=/backup.key,readonly',values.get('PLUSFOLIO_APP_IMAGE','plusfolio-app:local'),
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
        destination.parent.mkdir(parents=True,exist_ok=True)
        docker('run','--rm','--network','none','--user','0:0','--mount',f'type=bind,src={path},dst=/backup.age,readonly',
            '--mount',f'type=bind,src={key},dst=/backup.key,readonly','--mount',f'type=bind,src={destination.parent},dst=/output',
            values.get('PLUSFOLIO_APP_IMAGE','plusfolio-app:local'),'python','scripts/server_backup.py','--verify','/backup.age','--key','/backup.key','--into','/output/'+destination.name)
        import shutil
        config=destination/'source/.deploy/env'
        restored={name:json.loads(value) for name,value in (line.split('=',1) for line in config.read_text().splitlines() if line)}
        restored['COMPOSE_PROJECT_NAME']='plusfolio-restored-'+str(int(time.time()))
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
    init=sub.add_parser('init');init.add_argument('--config',help='JSON file for unattended setup; secrets never go in CLI arguments')
    for name in ['up','update','status','backup','stop']:sub.add_parser(name)
    logs=sub.add_parser('logs');logs.add_argument('services',nargs='*')
    restore=sub.add_parser('restore-backup');restore.add_argument('file');restore.add_argument('--key');restore.add_argument('--into',required=True)
    database=sub.add_parser('restore-database');database.add_argument('file')
    check=sub.add_parser('verify-backup');check.add_argument('file');check.add_argument('--key')
    download=sub.add_parser('download-backup');download.add_argument('into')
    export=sub.add_parser('export-images');export.add_argument('file')
    args=parser.parse_args()
    try:run(args)
    except (ValueError,RuntimeError,subprocess.CalledProcessError) as exc:
        print('Setup did not complete: '+(str(exc) if isinstance(exc,(ValueError,RuntimeError)) else 'a deployment command failed; inspect service logs.'),file=sys.stderr)
        raise SystemExit(1)

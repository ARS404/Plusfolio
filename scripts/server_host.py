"""Shared-host safeguards. No host package, daemon, firewall or global builder changes."""
import hashlib,json,os,re,socket,subprocess
from pathlib import Path

DEFAULTS={
    'LOCAL_PORT':'18080','BUILD_CPUS':'1','BUILD_MEMORY':'1024m',
    'BACKUP_INTERVAL':'86400','BACKUP_RETENTION_DAYS':'14','BACKUP_MAX_COUNT':'14',
    'BACKUP_MAX_BYTES':'2147483648','BACKUP_KEEP_MIN':'2',
}


def tools_ready(require_build=False):
    commands=[(['docker','info','--format','{{json .}}'],'Docker недоступен текущему пользователю'),
              (['docker','compose','version'],'Нужен установленный Docker Compose v2')]
    if require_build:commands.append((['docker','buildx','version'],'Нужен установленный Docker Buildx'))
    info={}
    for command,message in commands:
        try:result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,text=True)
        except (FileNotFoundError,subprocess.CalledProcessError):
            raise RuntimeError(message+'. Обратитесь к администратору сервера; системные пакеты не изменялись.') from None
        if command[1]=='info':info=json.loads(result.stdout)
    if info.get('CgroupDriver')=='none' or any(info.get(key) is False for key in ['MemoryLimit','CPUCfsQuota','PidsLimit','SwapLimit']):
        raise RuntimeError('Docker не поддерживает обязательные лимиты cgroups. Настройку должен проверить администратор сервера.')
    if info.get('ServerVersion') and int(info['ServerVersion'].split('.')[0])<28:
        raise RuntimeError('Для изоляции loopback-порта нужен Docker Engine 28+. Автоматическое обновление отключено; согласуйте вариант с администратором.')
    return info


def shared_values(values,legacy=False):
    result={**DEFAULTS,**values,'DEPLOYMENT_MODE':'shared'}
    project=result['COMPOSE_PROJECT_NAME']
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*',project):raise ValueError('Некорректное имя проекта')
    for key,kind in [('PLUSFOLIO_APP_IMAGE','app'),('PLUSFOLIO_TEX_IMAGE','tex'),('PLUSFOLIO_EMBEDDINGS_IMAGE','embeddings')]:
        result.setdefault(key,f'plusfolio-{kind}:local' if legacy else f'{project}-{kind}:local')
    port=str(result['LOCAL_PORT'])
    if not port.isdigit() or not 1024<=int(port)<=65535:raise ValueError('Локальный порт должен быть в диапазоне 1024–65535')
    if not 0<float(result['BUILD_CPUS'])<=16:raise ValueError('BUILD_CPUS должен быть больше 0 и не больше 16')
    if not re.fullmatch(r'[1-9][0-9]*(?:m|g)',str(result['BUILD_MEMORY'])):raise ValueError('BUILD_MEMORY: укажите размер, например 1024m')
    from server_backup import retention_policy
    retention_policy(result)
    for old in ['BIND_ADDRESS','HTTP_PORT','HTTPS_PORT']:result.pop(old,None)
    return result


def project_containers(docker,values,root):
    ids=docker('ps','--all','--filter','label=com.docker.compose.project='+values['COMPOSE_PROJECT_NAME'],
               '--format','{{.ID}}',stdout=subprocess.PIPE).stdout.decode().split()
    if not ids:return []
    objects=json.loads(docker('inspect',*ids,stdout=subprocess.PIPE).stdout)
    for item in objects:
        owner=(item.get('Config',{}).get('Labels') or {}).get('com.docker.compose.project.working_dir')
        if not owner or Path(owner).resolve()!=Path(root).resolve():
            raise RuntimeError('Это имя Compose project занято контейнерами из другой папки. Выберите отдельное имя; чужие контейнеры не изменены.')
    return objects


def port_available(port,containers):
    for item in containers:
        if item.get('State',{}).get('Running') and (item.get('Config',{}).get('Labels') or {}).get('com.docker.compose.service')=='web':
            for bindings in (item.get('HostConfig',{}).get('PortBindings') or {}).values():
                if any(row.get('HostIp')=='127.0.0.1' and row.get('HostPort')==str(port) for row in bindings or []):return
    try:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            probe.bind(('127.0.0.1',int(port)))
    except OSError:raise RuntimeError('Локальный порт занят. Выберите другой LOCAL_PORT; процесс, занимающий порт, не изменён.') from None


def check_limits(config):
    memory=0;cpus=0
    for name,service in config['services'].items():
        limit=int(service.get('mem_limit',0));quota=float(service.get('cpus',0));pids=int(service.get('pids_limit',0))
        if limit<=0 or quota<=0 or pids<=0 or int(service.get('memswap_limit',0))!=limit:
            raise RuntimeError('Для каждой службы нужны CPU, память, запрет дополнительного swap и лимит процессов: '+name)
        if name!='initialize':memory+=limit;cpus+=quota
        for binding in service.get('ports',[]):
            if name!='web' or binding.get('host_ip')!='127.0.0.1' or int(binding['target'])!=8000:
                raise RuntimeError('Разрешён только локальный порт web на 127.0.0.1')
    return {'memory_mib':memory//1048576,'cpus':round(cpus,2)}


def build_images(docker,values,root,targets=None):
    """Private bounded builder; preserve the caller's current/default builder."""
    identity=values['INSTANCE_ID']+values['COMPOSE_PROJECT_NAME']+values['BUILD_MEMORY']+str(values['BUILD_CPUS'])
    name='plusfolio-'+hashlib.sha256(identity.encode()).hexdigest()[:16]
    available=docker('buildx','ls','--format','{{.Name}}',stdout=subprocess.PIPE).stdout.decode().split()
    if name not in available:
        quota=str(round(float(values['BUILD_CPUS'])*100000))
        docker('buildx','create','--name',name,'--driver','docker-container','--buildkitd-config',str(Path(root)/'deploy/buildkitd.toml'),
               '--driver-opt','memory='+values['BUILD_MEMORY'],'--driver-opt','memory-swap='+values['BUILD_MEMORY'],
               '--driver-opt','cpu-period=100000','--driver-opt','cpu-quota='+quota,
               '--driver-opt','cpu-shares=128','--driver-opt','restart-policy=no',stdout=subprocess.DEVNULL)
    env={**os.environ,**{key:str(value) for key,value in values.items()}}
    try:
        docker('buildx','bake','--builder',name,'--file',str(Path(root)/'compose.yml'),'--load',*(targets or ['web','tex','embeddings']),env=env)
    finally:docker('buildx','stop',name,stdout=subprocess.DEVNULL)
    return name


def proxy_config(values,kind):
    from urllib.parse import urlsplit
    address=urlsplit(values['PUBLIC_URL']);host=address.hostname
    if not re.fullmatch(r'[A-Za-z0-9.-]+',host or ''):raise ValueError('Некорректное доменное имя')
    port=int(values['LOCAL_PORT']);public_port=address.port or 443
    if kind=='nginx':
        return f'''# Добавьте в существующий HTTPS server-блок домена {host}; сертификаты остаются у его владельца.
location / {{
    proxy_pass http://127.0.0.1:{port};
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    client_max_body_size 8m;
    proxy_read_timeout 90s;
}}
'''
    if kind=='caddy':return f'''# Добавьте сайт в существующую конфигурацию Caddy; проверьте, что домен ещё не настроен.
{host}{(':'+str(public_port)) if public_port!=443 else ''} {{
    reverse_proxy 127.0.0.1:{port}
}}
'''
    project=values['COMPOSE_PROJECT_NAME']
    return f'''# Подключение к сети {project}_frontend выполняет администратор существующего Traefik.
# Маршрут добавляется через уже настроенный file provider; имя entryPoint уточните у администратора.
http:
  routers:
    {project}:
      rule: "Host(`{host}`)"
      entryPoints: [websecure]
      tls: {{}}
      service: {project}
  services:
    {project}:
      loadBalancer:
        passHostHeader: true
        servers:
          - url: "http://{project}-web:8000"
'''

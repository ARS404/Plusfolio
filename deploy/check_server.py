#!/usr/bin/env python3
"""Run from a clean checkout: build/start/test a disposable server stack."""
import argparse, json, subprocess, sys, time, urllib.request, hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import server
parser=argparse.ArgumentParser();parser.add_argument('--keep',action='store_true');parser.add_argument('--skip-build',action='store_true');parser.add_argument('--skip-regression',action='store_true');args=parser.parse_args()
server.STATE.mkdir(mode=0o700,exist_ok=True)
if (server.STATE/'env').exists():
    if not server.read_env().get('COMPOSE_PROJECT_NAME','').startswith('plusfolio-test-'):
        raise SystemExit('Refusing to use an existing non-test deployment')
else:
    config={'public_url':'https://localhost:18443','admin_email':'admin@delivery.example.test','admin_name':'Deployment test',
        'admin_password':'Synthetic-server-pass-2040!','smtp_host':'smtp-test','smtp_port':'2525','smtp_user':'','smtp_password':'',
        'smtp_from':'robot@delivery.example.test','smtp_tls':'0','smtp_ssl':'0','project':'plusfolio-test-'+str(int(time.time())),
        'local_port':'18080'}
    path=server.STATE/'test-input.json';path.write_text(json.dumps(config));path.chmod(0o600);server.configure(path)
probe=subprocess.run(['docker','compose','version'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
prefix=['docker','compose'] if probe.returncode==0 else ['docker-compose']
values=server.server_host.shared_values(server.read_env(),legacy=server.read_env().get('DEPLOYMENT_MODE')!='shared')
server.write_env(values)
base_compose=server.compose
command=[*prefix,'--project-name',values['COMPOSE_PROJECT_NAME'],'--env-file',str(server.STATE/'env'),'-f',str(ROOT/'compose.yml'),'-f',str(ROOT/'deploy/compose.test.yml')]
def compose(*argv,**kwargs):return subprocess.run([*command,*argv],cwd=ROOT,check=True,**kwargs)
server.compose=compose
neighbor='plusfolio-neighbor-check-'+str(time.time_ns())
neighbor_volume=neighbor+'-data'
neighbor_started=False
neighbor_before=None

def neighbor_status():
    details=json.loads(server.docker('inspect',neighbor,stdout=subprocess.PIPE).stdout)[0]
    canary=server.docker('exec',neighbor,'cat','/data/canary',stdout=subprocess.PIPE).stdout
    with urllib.request.urlopen('http://127.0.0.1:18081',timeout=10) as response:body=response.read()
    return details['Id'],details['State']['StartedAt'],details['RestartCount'],canary,hashlib.sha256(body).hexdigest()

try:
    server.server_host.tools_ready(not args.skip_build)
    base_config=json.loads(base_compose('config','--format','json',stdout=subprocess.PIPE).stdout)
    assert server.server_host.check_limits(base_config)=={'memory_mib':3392,'cpus':2.0}
    owned=server.server_host.project_containers(server.docker,values,ROOT)
    server.server_host.port_available(values['LOCAL_PORT'],owned)
    default_before=server.docker('buildx','inspect',stdout=subprocess.PIPE).stdout.splitlines()[0]
    server.docker('run','--detach','--name',neighbor,'--cpus','0.1','--memory','64m','--memory-swap','64m','--pids-limit','32',
        '--publish','127.0.0.1:18081:80','--mount','type=volume,src='+neighbor_volume+',dst=/data','caddy:2.11.7-alpine',stdout=subprocess.DEVNULL)
    neighbor_started=True
    server.docker('exec',neighbor,'sh','-c','printf neighbor-canary > /data/canary')
    for _ in range(30):
        try:neighbor_before=neighbor_status();break
        except Exception:time.sleep(.2)
    assert neighbor_before
    if not args.skip_build:
        builder=server.server_host.build_images(server.docker,values,ROOT)
        details=json.loads(server.docker('inspect','buildx_buildkit_'+builder+'0',stdout=subprocess.PIPE).stdout)[0]
        assert details['HostConfig']['Memory']==1073741824 and details['HostConfig']['CpuQuota']==100000
        assert not details['State']['Running']
    assert server.docker('buildx','inspect',stdout=subprocess.PIPE).stdout.splitlines()[0]==default_before
    assert neighbor_status()==neighbor_before,'Neighbor changed during build'
    compose('config','--quiet')
    server.backup_key(values)
    compose('up','--detach','--wait','--wait-timeout','600')
    # Exercise the actual shared-host CLI, including migration of its own former proxy.
    subprocess.run([sys.executable,str(ROOT/'scripts/server.py'),'doctor'],check=True,cwd=ROOT)
    subprocess.run([sys.executable,str(ROOT/'scripts/server.py'),'up'],check=True,cwd=ROOT)
    assert neighbor_status()==neighbor_before,'Neighbor changed during shared-host CLI startup'
    compose('up','--detach','--wait','--wait-timeout','600')
    compose('exec','-T','mail','python','backend/manage.py','check_smtp')
    server.verify_local(values)
    server.verify_external(values)
    containers=server.server_host.project_containers(server.docker,values,ROOT)
    for item in containers:
        limits=item['HostConfig']
        assert limits['NanoCpus']>0 and limits['Memory']>0 and limits['MemorySwap']==limits['Memory'] and limits['PidsLimit']>0
    assert neighbor_status()==neighbor_before,'Neighbor changed during installation'
    compose('exec','-T','tex','python','-c',"import os; assert sorted(os.listdir('/sys/class/net'))==['lo']; assert not os.path.exists('/app/backend/core/models.py'); assert not os.path.exists('/app/data'); assert not os.path.exists('/run/secrets')")
    exists=compose('exec','-T','db','psql','-U','postgres','-d','postgres','-At','-c',"SELECT 1 FROM pg_database WHERE datname='test_plusfolio'",stdout=subprocess.PIPE).stdout.strip()
    if not exists:compose('exec','-T','db','createdb','-U','postgres','--owner=plusfolio','test_plusfolio')
    compose('exec','-T','db','psql','-U','postgres','-d','test_plusfolio','-v','ON_ERROR_STOP=1','-c','CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;')
    if not args.skip_regression:compose('run','--rm','--no-deps','-T','web','python','deploy/postgres_tests.py')
    subprocess.run([sys.executable,str(ROOT/'deploy/smoke.py')],check=True,cwd=ROOT)
    print('Restart verification ...',flush=True)
    compose('restart','web','mail','indexer','tex')
    compose('up','--detach','--wait','--wait-timeout','300')
    server.verify_external(values)
    compose('stop','mail')
    compose('exec','-T','web','python','backend/manage.py','shell','-c',
        "from core.models import User,Circle,ApiToken; from core import services as s; s.invite(User.objects.filter(is_superuser=True).first(),'pending@delivery.example.test','student',Circle.objects.first()); ApiToken.objects.update(revoked_at=None)")
    compose('exec','-T','backup','python','-c',"from pathlib import Path; import os; old=Path('/backups/plusfolio-20000101T000000000000Z.tar.gz.age'); old.write_bytes(b'old'); os.utime(old,(946684800,946684800)); Path('/backups/foreign-canary.txt').write_bytes(b'keep')")
    compose('exec','-T','backup','python','scripts/server_backup.py')
    compose('exec','-T','backup','python','-c',"from pathlib import Path; assert not Path('/backups/plusfolio-20000101T000000000000Z.tar.gz.age').exists(); assert Path('/backups/foreign-canary.txt').read_bytes()==b'keep'; assert len(list(Path('/backups').glob('*.age')))>=2")
    output=server.STATE/'test-backups';output.mkdir(exist_ok=True)
    compose('cp','backup:/backups/.',str(output))
    newest=sorted(output.glob('*.age'))[-1]
    server.docker('run','--rm','--network','none','--user','0:0','--mount',f'type=bind,src={newest.resolve()},dst=/backup.age,readonly',
        '--mount',f'type=bind,src={(server.STATE/"backup.key").resolve()},dst=/backup.key,readonly',values.get('PLUSFOLIO_APP_IMAGE','plusfolio-app:local'),
        'python','scripts/server_backup.py','--verify','/backup.age','--key','/backup.key')
    restored=server.STATE/('restored-test-'+str(time.time_ns()))
    original_state=server.STATE
    try:
        # A recovery operator must not need the lost deployment configuration.
        server.STATE=original_state/'empty-operator'
        server.run(argparse.Namespace(command='restore-backup',file=str(newest),key=str(original_state/'backup.key'),into=str(restored),image=values['PLUSFOLIO_APP_IMAGE']))
    finally:server.STATE=original_state
    recovered=restored/'source'
    server.server_host.build_images(server.docker,values,recovered,targets=['web'])
    server.docker('run','--rm','--network','none','--cpus','0.3','--memory','512m','--memory-swap','512m','--pids-limit','64','-e','PLUSFOLIO_DEMO=1',values['PLUSFOLIO_APP_IMAGE'],'python','backend/manage.py','check')
    restore_db='restore_check_'+str(time.time_ns())
    compose('exec','-T','db','createdb','-U','postgres','--owner=plusfolio',restore_db)
    compose('exec','-T','db','psql','-U','postgres','-d',restore_db,'-v','ON_ERROR_STOP=1','-c','CREATE EXTENSION vector; CREATE EXTENSION pg_trgm;')
    with (restored/'database.dump').open('rb') as source:
        compose('run','--rm','--no-deps','-T','-e','POSTGRES_DB='+restore_db,'web','python','deploy/restore_database.py',stdin=source)
    query="SELECT (SELECT count(*) FROM core_user),(SELECT count(*) FROM core_problem),(SELECT count(*) FROM core_topic)"
    before=compose('exec','-T','db','psql','-U','postgres','-d','plusfolio','-At','-c',query,stdout=subprocess.PIPE).stdout
    after=compose('exec','-T','db','psql','-U','postgres','-d',restore_db,'-At','-c',query,stdout=subprocess.PIPE).stdout
    assert before==after,'Restored data counts differ'
    query="SELECT (SELECT count(*) FROM django_session)+(SELECT count(*) FROM core_apitoken WHERE revoked_at IS NULL)+(SELECT count(*) FROM core_invitation WHERE state='pending')+(SELECT count(*) FROM core_emailoutbox WHERE state IN ('queued','retry'))"
    assert compose('exec','-T','db','psql','-U','postgres','-d',restore_db,'-At','-c',query,stdout=subprocess.PIPE).stdout.strip()==b'0'
    compose('start','mail')
    assert neighbor_status()==neighbor_before,'Neighbor changed during restart/backup/restore'
    server.run(argparse.Namespace(command='stop'))
    assert neighbor_status()==neighbor_before,'Neighbor changed during application stop'
    if args.keep:
        compose('up','--detach','--wait','--wait-timeout','600');server.verify_local(values)
    print('SHARED SERVER / CPU-RAM LIMITS / NEIGHBOR UNCHANGED / SMTP / BACKUP RETENTION / DATABASE RESTORE VERIFIED',flush=True)
finally:
    if neighbor_started:
        server.docker('rm','--force',neighbor,stdout=subprocess.DEVNULL)
        server.docker('volume','rm',neighbor_volume,stdout=subprocess.DEVNULL)
    if not args.keep:compose('down','--volumes','--remove-orphans')

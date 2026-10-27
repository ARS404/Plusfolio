#!/usr/bin/env python3
"""Run from a clean checkout: build/start/test a disposable server stack."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import server
parser=argparse.ArgumentParser();parser.add_argument('--keep',action='store_true');parser.add_argument('--skip-build',action='store_true');args=parser.parse_args()
server.STATE.mkdir(mode=0o700,exist_ok=True)
if (server.STATE/'env').exists():
    if not server.read_env().get('COMPOSE_PROJECT_NAME','').startswith('plusfolio-test-'):
        raise SystemExit('Refusing to use an existing non-test deployment')
else:
    config={'public_url':'https://localhost:18443','admin_email':'admin@delivery.example.test','admin_name':'Deployment test',
        'admin_password':'Synthetic-server-pass-2040!','smtp_host':'smtp-test','smtp_port':'2525','smtp_user':'','smtp_password':'',
        'smtp_from':'robot@delivery.example.test','smtp_tls':'0','smtp_ssl':'0','project':'plusfolio-test-'+str(int(time.time())),
        'bind_address':'127.0.0.1','http_port':'18088','https_port':'18443'}
    path=server.STATE/'test-input.json';path.write_text(json.dumps(config));path.chmod(0o600);server.configure(path)
probe=subprocess.run(['docker','compose','version'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
prefix=['docker','compose'] if probe.returncode==0 else ['docker-compose']
command=[*prefix,'--env-file',str(server.STATE/'env'),'-f',str(ROOT/'compose.yml'),'-f',str(ROOT/'deploy/compose.test.yml')]
def compose(*argv,**kwargs):return subprocess.run([*command,*argv],cwd=ROOT,check=True,**kwargs)
server.compose=compose
try:
    values=server.read_env()
    compose('config','--quiet')
    if not args.skip_build:compose('build','--pull')
    server.backup_key(values)
    compose('up','--detach','--wait','--wait-timeout','600')
    compose('exec','-T','mail','python','backend/manage.py','check_smtp')
    server.verify_external(values)
    compose('exec','-T','tex','python','-c',"import os; assert sorted(os.listdir('/sys/class/net'))==['lo']; assert not os.path.exists('/app/backend/core/models.py'); assert not os.path.exists('/app/data'); assert not os.path.exists('/run/secrets')")
    exists=compose('exec','-T','db','psql','-U','postgres','-d','postgres','-At','-c',"SELECT 1 FROM pg_database WHERE datname='test_plusfolio'",stdout=subprocess.PIPE).stdout.strip()
    if not exists:compose('exec','-T','db','createdb','-U','postgres','--owner=plusfolio','test_plusfolio')
    compose('exec','-T','db','psql','-U','postgres','-d','test_plusfolio','-v','ON_ERROR_STOP=1','-c','CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;')
    compose('run','--rm','--no-deps','-T','web','python','deploy/postgres_tests.py')
    subprocess.run([sys.executable,str(ROOT/'deploy/smoke.py')],check=True,cwd=ROOT)
    print('Restart verification ...',flush=True)
    compose('restart','web','mail','indexer','tex')
    compose('up','--detach','--wait','--wait-timeout','300')
    server.verify_external(values)
    compose('stop','mail')
    compose('exec','-T','web','python','backend/manage.py','shell','-c',
        "from core.models import User,Circle,ApiToken; from core import services as s; s.invite(User.objects.filter(is_superuser=True).first(),'pending@delivery.example.test','student',Circle.objects.first()); ApiToken.objects.update(revoked_at=None)")
    compose('exec','-T','backup','python','scripts/server_backup.py')
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
        server.run(argparse.Namespace(command='restore-backup',file=str(newest),key=str(original_state/'backup.key'),into=str(restored)))
    finally:server.STATE=original_state
    recovered=restored/'source'
    server.docker('build','--target','application','--tag','plusfolio-restore-build:check','--file',str(recovered/'deploy/Dockerfile'),str(recovered))
    server.docker('run','--rm','--network','none','-e','PLUSFOLIO_DEMO=1','plusfolio-restore-build:check','python','backend/manage.py','check')
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
    print('SERVER INSTALLATION / SMTP / RESTART / ENCRYPTED BACKUP / DATABASE RESTORE VERIFIED',flush=True)
finally:
    if not args.keep:compose('down','--volumes','--remove-orphans')

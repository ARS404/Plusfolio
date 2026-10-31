#!/usr/bin/env python3
"""Reproducible disposable Linux/PostgreSQL pilot; never use the live deployment."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import math
from pathlib import Path
import ssl
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import server,server_storage

MEASURE=server.STATE/'capacity'
SERVICES=['db','redis','embeddings','tex','initialize','web','indexer','mail','backup','proxy']


def quiet(*args,**kwargs):
    return server.docker(*args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**kwargs).stdout


def phase(name):
    (MEASURE/'phase').write_text(name)
    print(name,flush=True)
    return time.monotonic()


def summary(samples):
    groups=defaultdict(list)
    for row in samples:groups[row['name']].append(row)
    result={}
    for name,rows in sorted(groups.items()):
        timings=sorted(row['ms'] for row in rows)
        result[name]={'requests':len(rows),'p50_ms':round(statistics.median(timings),1),
            'p95_ms':round(timings[max(0,math.ceil(.95*len(rows))-1)],1),
            'max_ms':round(max(timings),1),'errors':sum(row['status']!=200 for row in rows),
            'statuses':{str(status):sum(row['status']==status for row in rows) for status in sorted({row['status'] for row in rows})},
            'bytes':sum(row['bytes'] for row in rows),
            'semantic':sum(row.get('semantic',False) for row in rows),
            'pending':sum(row.get('pending',0) for row in rows)}
    return result


class Pilot:
    def __init__(self,args):
        self.args=args
        self.values=server.read_env()
        self.parent=self.values['COMPOSE_PROJECT_NAME']
        self.mapping_stop=threading.Event()
        self.report={'format':'plusfolio-capacity-v1','completed':False,'sampling_seconds':.25,
            'started_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
            'reused_dataset':args.reuse,
            'source_revision':quiet('image','inspect',args.app_image,'--format','{{index .Config.Labels "org.opencontainers.image.revision"}}').decode().strip(),
            'host':json.loads(quiet('info','--format','{"architecture":"{{.Architecture}}","cpus":{{.NCPU}},"memory":{{.MemTotal}},"cgroup_version":"{{.CgroupVersion}}"}')),
            'runs':{},'operations':{}}

    def compose(self,*args,**kwargs):
        files=server_storage.compose_files(server.read_env(),ROOT)+[ROOT/'deploy/compose.test.yml',ROOT/'deploy/capacity/compose.yml',MEASURE/'cgroups.yml']
        return subprocess.run(['docker','compose','--project-name',self.values['COMPOSE_PROJECT_NAME'],'--env-file',str(server.STATE/'env'),
            *(part for file in files for part in ['-f',str(file)]),*args],cwd=ROOT,check=True,**kwargs)

    def shell(self,code):
        return self.compose('exec','-T','web','python','backend/manage.py','shell','-c',code,stdout=subprocess.PIPE).stdout.decode().strip().splitlines()[-1]

    def sql(self,query):
        return self.compose('exec','-T','db','psql','-U','postgres','-d','plusfolio','-At','-c',query,stdout=subprocess.PIPE).stdout.decode().strip()

    def quota(self,value):
        quiet('run','--rm','--user','0:0','--network','none','--cpus','.1','--memory','32m','--memory-swap','32m',
            '--pids-limit','32','--cap-drop','ALL','--cap-add','DAC_OVERRIDE','--cgroupns','host','--mount','type=bind,src=/sys/fs/cgroup,dst=/cgroup',
            '--entrypoint','python',self.args.app_image,'-c',
            "from pathlib import Path; p=Path('/cgroup')/"+repr(self.parent)+";p.mkdir(exist_ok=True);(p/'cpu.max').write_text("+repr(value+' 100000')+")")

    def mapping(self):
        while not self.mapping_stop.is_set() and not (MEASURE/'stop').exists():
            ids=quiet('ps','--all','--no-trunc','--filter','label=com.docker.compose.project='+self.values['COMPOSE_PROJECT_NAME'],'--format','{{.ID}}').decode().split()
            try:output=quiet('inspect',*ids,'--format','{{.Id}} {{.State.Pid}} {{index .Config.Labels "com.docker.compose.service"}}') if ids else b''
            except subprocess.CalledProcessError as error:output=error.stdout  # containers can disappear during recreation
            rows=output.decode().splitlines()
            data={parts[0]:{'pid':int(parts[1]),'name':parts[2]} for row in rows if len(parts:=row.split())==3 and parts[1]!='0'}
            temporary=MEASURE/'services.tmp';temporary.write_text(json.dumps(data));temporary.replace(MEASURE/'services.json')
            self.mapping_stop.wait(1)

    def request(self,session,name,path,body=None):
        start=time.monotonic();value={};payload=b'';status=0
        try:
            headers={'Authorization':'Bearer '+session['token'],'Content-Type':'application/json'}
            request=urllib.request.Request(self.values['PUBLIC_URL']+path,headers=headers,
                data=json.dumps(body).encode() if body is not None else None)
            with urllib.request.urlopen(request,context=self.tls,timeout=60) as response:
                status=response.status;payload=response.read()
                if response.headers.get('Content-Type','').startswith('application/json'):value=json.loads(payload)
                if name=='pdf' and not payload.startswith(b'%PDF-'):status=599
        except urllib.error.HTTPError as error:status=error.code;error.close()
        except (OSError,ValueError,http.client.HTTPException):status=599
        return {'name':name,'ms':(time.monotonic()-start)*1000,'status':status,'bytes':len(payload),
                **{key:value[key] for key in ['semantic','pending'] if key in value}}

    def load(self,count,seconds):
        start=time.monotonic();gate=threading.Barrier(count)
        def client(index):
            session=self.fixture['sessions'][index];student=session['role']=='student'
            catalogue='/api/v1/my-materials/' if student else '/api/v1/materials/'
            plan=[('page','/'),('circles','/api/v1/circles'),
                ('student-tasks' if student else 'problem-catalogue',catalogue+'problem?pagination=1&page_size=50'),
                ('student-worksheets' if student else 'worksheet-catalogue',catalogue+'worksheet'),
                ('journal','/api/v1/circles/'+session['circle']+'/journal?issues=all'),
                ('analytics-personal' if student else 'analytics-group','/api/v1/analytics')]
            rows=[];iteration=0;gate.wait()
            while time.monotonic()-start<seconds:
                name,path=plan[(iteration+index)%len(plan)]
                rows.append(self.request(session,name,path))
                # Varied queries force real model calls instead of the query LRU cache.
                if iteration%6==0:
                    rows.append(self.request(session,'search','/api/v1/problem-search',
                        {'q':f'Треугольник и сумма углов, пример {index*1000+iteration+int(start)}','field':'statement','mode':'hybrid',
                         'scope':'my' if student else 'library','limit':10}))
                iteration+=1;time.sleep(.2)
            return rows
        with ThreadPoolExecutor(max_workers=count) as pool:
            rows=[row for batch in pool.map(client,range(count)) for row in batch]
        return {'seconds':round(time.monotonic()-start,2),'active_sessions':count,'think_seconds':.2,
                'resource_phase':(MEASURE/'phase').read_text().strip(),'metrics':summary(rows)}

    def wait_index(self,timeout=1800):
        start=time.monotonic()
        query="SELECT (SELECT count(*) FROM core_problemsearchdocument WHERE text<>'' AND embedding IS NULL)+(SELECT count(*) FROM core_cataloguesearchdocument WHERE text<>'' AND embedding IS NULL)"
        while True:
            count=int(self.sql(query))
            if count==0 and int(self.sql('SELECT count(*) FROM core_problemsearchdocument'))>=1500:return time.monotonic()-start
            if time.monotonic()-start>timeout:raise RuntimeError('Indexing did not finish')
            time.sleep(5)

    def backup(self, *, standalone=False):
        code="""import json,resource,time
from pathlib import Path
from scripts import server_backup as b
timings={}
def measured(function,key):
    def call(*args,**kwargs):
        started=time.monotonic()
        try:return function(*args,**kwargs)
        finally:timings[key]=round(time.monotonic()-started,2)
    return call
b._backup=measured(b._backup,'archive_seconds')
# backup imports server_s3 through the script search path.
import server_s3
server_s3.upload=measured(server_s3.upload,'s3_seconds')
started=time.monotonic()
while b.backup() is None:time.sleep(1)
timings.update(seconds=round(time.monotonic()-started,2),python_rss_peak_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
timings['charged_peak_bytes']=int(Path('/sys/fs/cgroup/memory.peak').read_text())
print('BACKUP_TIMING',json.dumps(timings))
"""
        command=['run','--rm','--no-deps','-T','backup'] if standalone else ['exec','-T','backup']
        output=self.compose(*command,'python','-c',code,stdout=subprocess.PIPE).stdout.decode()
        timings=json.loads(next(line.split(' ',1)[1] for line in output.splitlines() if line.startswith('BACKUP_TIMING ')))
        sizes=json.loads(self.compose(*command,'python','-c',
            "import json;from pathlib import Path;print(json.dumps({p.name:p.stat().st_size for p in Path('/backups').glob('plusfolio-*.tar.gz.age')}))",stdout=subprocess.PIPE).stdout)
        return {**timings,'archive_bytes':max(sizes.values()),'local_copies':len(sizes),'local_bytes':sum(sizes.values())}

    def run(self):
        phase('startup')
        self.quota('max')
        self.monitor='plusfolio-capacity-monitor-'+str(time.time_ns())
        quiet('run','--detach','--name',self.monitor,'--network','none','--user','0:0','--cpus','.03','--memory','32m','--memory-swap','32m',
            '--pids-limit','32','--read-only','--cap-drop','ALL','--cgroupns','host','--mount','type=bind,src=/sys/fs/cgroup,dst=/cgroup,readonly',
            '--mount','type=bind,src=/proc,dst=/host-proc,readonly','--mount','type=bind,src='+str(MEASURE)+',dst=/measure',
            '--mount','type=bind,src='+str(ROOT/'deploy/capacity/monitor.py')+',dst=/monitor.py,readonly',
            '--entrypoint','python',self.args.app_image,'/monitor.py')
        self.mapping_thread=threading.Thread(target=self.mapping);self.mapping_thread.start()
        try:
            until=time.monotonic()+30
            while not (MEASURE/'ready').exists():
                if time.monotonic()>until:raise RuntimeError('Resource sampler failed to start; no load was sent')
                time.sleep(.2)
            began=time.monotonic()
            self.compose('up','--detach','object-store','smtp-test')
            self.compose('run','--rm','--no-deps','-T','backup','python','-c',
                "import sys,time;sys.path.insert(0,'scripts');from server_s3 import client;s=client()\n"
                "for n in range(30):\n"
                "    try:\n"
                "        try:s.head_bucket(Bucket='plusfolio-capacity')\n"
                "        except s.exceptions.ClientError as error:\n"
                "            if error.response['ResponseMetadata']['HTTPStatusCode']!=404:raise\n"
                "            s.create_bucket(Bucket='plusfolio-capacity',CreateBucketConfiguration={'LocationConstraint':'ru-central1'})\n"
                "        break\n"
                "    except Exception:\n"
                "        if n==29:raise\n"
                "        time.sleep(1)\n"
                "s.put_bucket_versioning(Bucket='plusfolio-capacity',VersioningConfiguration={'Status':'Enabled'})")
            self.compose('up','--detach','--wait','--wait-timeout','600')
            self.report['operations']['startup_seconds']=round(time.monotonic()-began,2)
            server.compose=self.compose
            server.verify_external(self.values)
            self.tls=ssl.create_default_context(cafile=str(server.STATE/'local-ca.crt'))
            if not self.args.reuse:
                self.compose('stop','indexer')
                phase('seed')
                seed=(ROOT/'deploy/capacity/seed.py').read_text()+"\nPath('/app/.local/capacity.json').write_text(json.dumps(seed()))\n"
                self.compose('exec','-T','web','python','backend/manage.py','shell','-c',seed)
            self.fixture=json.loads(self.compose('exec','-T','web','cat','/app/.local/capacity.json',stdout=subprocess.PIPE).stdout)
            self.report['counts']=self.fixture['counts']
            phase('initial-indexing')
            self.compose('start','indexer')
            self.report['operations']['indexing_seconds']=round(self.wait_index(),2)
            for profile in ['shared','dedicated-pilot']:
                self.values['RESOURCE_PROFILE']=profile;server.write_env(self.values)
                phase(profile+'-restart')
                self.compose('up','--detach','--wait','--wait-timeout','600')
                for count in [5,10]:
                    phase(profile+'-'+str(count)+'-sessions')
                    self.report['runs'][profile+'-'+str(count)]=self.load(count,self.args.seconds)
                phase(profile+'-pdf')
                self.shell("import shutil;from django.conf import settings;shutil.rmtree(settings.LOCAL_DIR/'pdf-cache',ignore_errors=True);print('Own PDF cache cleared')")
                pdf=[]
                for sheet in self.fixture['worksheets'][:3]:
                    pdf.append(self.request(self.fixture['sessions'][0],'pdf','/api/v1/materials/worksheet/'+sheet+'/pdf?solutions=1'))
                self.report['operations'][profile+'-pdf']=summary(pdf)
            phase('guaranteed-cpu-proxy')
            self.quota('100000')
            self.report['runs']['dedicated-one-cpu-10']=self.load(10,self.args.seconds)
            phase('concurrent-background')
            self.shell("from core.models import ProblemSearchDocument; ProblemSearchDocument.objects.filter(pk__in=list(ProblemSearchDocument.objects.values_list('pk',flat=True)[:300])).update(embedding=None)")
            self.shell("import time;from core import services as s; from core.models import User,Circle; a=User.objects.get(email='admin@capacity.example.test');c=Circle.objects.first(); suffix=str(time.time_ns()); [s.invite(a,'queued'+suffix+str(i)+'@capacity.example.test','student',c) for i in range(20)]")
            with ThreadPoolExecutor(max_workers=2) as pool:
                backup=pool.submit(self.backup)
                pdf=pool.submit(self.request,self.fixture['sessions'][0],'pdf',
                    '/api/v1/materials/worksheet/'+self.fixture['worksheets'][4]+'/pdf?solutions=1')
                self.report['runs']['background-one-cpu-10']=self.load(10,self.args.seconds)
                self.report['operations']['backup']=backup.result()
                self.report['operations']['background-pdf']=summary([pdf.result()])
            self.report['operations']['reindex_remaining_seconds']=round(self.wait_index(),2)
            self.report['operations']['mail_states']=json.loads(self.shell("import json; from django.db.models import Count;from core.models import EmailOutbox;print(json.dumps(list(EmailOutbox.objects.values('state').annotate(count=Count('pk')))))"))
            phase('update')
            self.report['operations']['preupdate_backup']=self.backup()
            began=time.monotonic()
            self.compose('up','--detach','--force-recreate','--wait','--wait-timeout','600',*SERVICES)
            self.report['operations']['update_seconds']=round(time.monotonic()-began,2)
            self.report['disk']={'database_bytes':int(self.sql("SELECT pg_database_size(current_database())")),
                'indexes_bytes':int(self.sql("SELECT sum(pg_indexes_size(relid)) FROM pg_stat_user_tables")),
                'wal_bytes':int(self.sql("SELECT COALESCE(sum(size),0) FROM pg_ls_waldir()")),
                'relations_bytes':int(self.sql("SELECT sum(pg_total_relation_size(relid)) FROM pg_stat_user_tables"))}
            self.report['disk']['images']=[json.loads(line) for line in quiet('image','inspect',self.args.app_image,self.args.tex_image,self.args.embedding_image,
                '--format','{"id":"{{.Id}}","size":{{.Size}}}').decode().splitlines()]
            phase('recovery')
            from capacity.storage import verify,image_storage
            self.report['storage_recovery']=verify(self)
            phase('image-storage')
            previous=[]
            if self.args.previous_release:
                previous=list(json.loads(self.args.previous_release.read_text())['images'].values())
            self.report['image_storage']=image_storage(server.docker,
                [self.args.app_image,self.args.tex_image,self.args.embedding_image],previous,MEASURE)
            self.report['completed']=True
        finally:
            self.mapping_stop.set();self.mapping_thread.join()
            (MEASURE/'stop').touch()
            quiet('wait',self.monitor)
            quiet('rm',self.monitor)
            if not self.args.keep:self.compose('down','--volumes','--remove-orphans')
            self.report['resources']=summarize_resources(MEASURE/'samples.jsonl')
            for run in self.report['runs'].values():
                if self.report['resources'].get(run['resource_phase'],{}).get('coverage_pct',0)<95:
                    self.report['completed']=False
            self.args.output.parent.mkdir(parents=True,exist_ok=True)
            self.args.output.write_text(json.dumps(self.report,indent=2,ensure_ascii=False)+'\n')
        print('Capacity report: '+str(self.args.output),flush=True)
        if not self.report['completed']:raise RuntimeError('Incomplete resource measurements; report is not a capacity validation')


def summarize_resources(path):
    groups=defaultdict(list)
    for line in path.read_text().splitlines():
        row=json.loads(line);groups[row['phase']].append(row)
    result={}
    for name,rows in groups.items():
        elapsed=max(rows[-1]['at']-rows[0]['at'],.001)
        parent_seconds=(rows[-1]['parent_cpu'].get('usage_usec',0)-rows[0]['parent_cpu'].get('usage_usec',0))/1e6
        services={}
        for service in sorted({key for row in rows for key in row['services']}):
            snapshots=[row['services'][service] for row in rows if service in row['services']]
            by_id=defaultdict(list)
            for item in snapshots:by_id[item['id']].append(item)
            services[service]={'working_set_peak_bytes':max(s['working_set'] for s in snapshots),
                'charged_sample_peak_bytes':max(s['memory'] for s in snapshots),
                'lifetime_charged_peak_bytes':max(s['peak'] for s in snapshots),
                'oom_kills':sum(max(s['events']['oom_kill'] for s in entries) for entries in by_id.values()),
                'cpu_seconds':round(sum(entries[-1]['cpu']['usage_usec']-entries[0]['cpu']['usage_usec'] for entries in by_id.values())/1e6,3),
                'throttled_periods':sum(entries[-1]['cpu']['nr_throttled']-entries[0]['cpu']['nr_throttled'] for entries in by_id.values()),
                'cpu_periods':sum(entries[-1]['cpu']['nr_periods']-entries[0]['cpu']['nr_periods'] for entries in by_id.values()),
                'throttled_seconds':round(sum(entries[-1]['cpu']['throttled_usec']-entries[0]['cpu']['throttled_usec'] for entries in by_id.values())/1e6,3)}
        result[name]={'samples':len(rows),'sampled_seconds':round(elapsed,2),
            'parent_average_cpus':round(parent_seconds/elapsed,3),
            'host_used_peak_bytes':max(row['host']['used'] for row in rows),
            'coverage_pct':round(100*sum(set(SERVICES)-{'initialize'}<=set(row['services']) for row in rows)/len(rows),1),
            'host_available_min_bytes':min(row['host']['available'] for row in rows),
            'host_oom_kills':rows[-1]['host']['oom_kill']-rows[0]['host']['oom_kill'],
            'swap_peak_bytes':max(row['host']['swap_used'] for row in rows),
            'stack_working_set_peak_bytes':max(sum(value['working_set'] for key,value in row['services'].items() if key!='object-store' and key!='smtp-test') for row in rows),
            'parent_cpu_throttled_seconds':round((rows[-1]['parent_cpu'].get('throttled_usec',0)-rows[0]['parent_cpu'].get('throttled_usec',0))/1e6,3),
            'services':services}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-image',default='plusfolio-app:local')
    parser.add_argument('--tex-image',default='plusfolio-tex:local')
    parser.add_argument('--embedding-image',default='plusfolio-embeddings:local')
    parser.add_argument('--seconds',type=int,default=45)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--keep',action='store_true')
    parser.add_argument('--previous-release',type=Path,help='Previous release images.json; all referenced images must already be local')
    parser.add_argument('--reuse',action='store_true',help='Retune only this retained disposable test project; do not reseed')
    args=parser.parse_args()
    if args.reuse:
        values=server.read_env()
        expected={'ADMIN_EMAIL':'admin@capacity.example.test','SMTP_HOST':'smtp-test',
                  'PUBLIC_URL':'https://localhost:18443','BACKUP_S3_ENDPOINT':'https://object-store:5000'}
        if (not values.get('COMPOSE_PROJECT_NAME','').startswith('plusfolio-test-capacity-') or
                any(values.get(key)!=value for key,value in expected.items())):
            raise SystemExit('Refusing a non-capacity deployment')
        for name in ['stop','ready']: (MEASURE/name).unlink(missing_ok=True)
        (MEASURE/'samples.jsonl').unlink(missing_ok=True)
        (MEASURE/'parent').write_text(values['COMPOSE_PROJECT_NAME'])
        (MEASURE/'cgroups.yml').write_text('services:\n'+''.join('  '+name+':\n    cgroup_parent: /'+values['COMPOSE_PROJECT_NAME']+'\n' for name in SERVICES))
        Pilot(args).run()
        return
    if (server.STATE/'env').exists():raise SystemExit('Use a fresh disposable checkout without .deploy/env')
    info=server.server_host.tools_ready()
    if info.get('OSType')!='linux' or str(info.get('CgroupVersion'))!='2' or info.get('CgroupDriver')!='cgroupfs':
        raise SystemExit('This isolated CPU-quota benchmark requires Linux cgroup v2 with cgroupfs; do not change a shared or production Docker daemon')
    MEASURE.mkdir(parents=True,mode=0o700)
    certs=MEASURE/'certs';certs.mkdir()
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(certs/'server.key'),'-out',str(certs/'server.crt'),
        '-days','2','-subj','/CN=object-store','-addext','subjectAltName=DNS:object-store,DNS:localhost,IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    credentials=MEASURE/'s3-credentials.json';credentials.write_text(json.dumps({'access_key_id':'synthetic','secret_access_key':'synthetic'}));credentials.chmod(0o600)
    config={'public_url':'https://localhost:18443','admin_email':'admin@capacity.example.test','admin_name':'Capacity test',
        'admin_password':'Synthetic-capacity-password-2040!','smtp_host':'smtp-test','smtp_port':'2525','smtp_tls':'0','smtp_ssl':'0',
        'smtp_user':'','smtp_password':'','smtp_from':'robot@capacity.example.test','project':'plusfolio-test-capacity-'+str(time.time_ns()),'local_port':'18080',
        'backup_s3':{'endpoint':'https://object-store:5000','bucket':'plusfolio-capacity','prefix':'pilot/','storage_class':'STANDARD','credentials_file':str(credentials)}}
    config_path=MEASURE/'input.json';config_path.write_text(json.dumps(config));config_path.chmod(0o600)
    values=server.configure(config_path)
    values.update(PLUSFOLIO_APP_IMAGE=args.app_image,PLUSFOLIO_TEX_IMAGE=args.tex_image,PLUSFOLIO_EMBEDDINGS_IMAGE=args.embedding_image)
    server.write_env(values);server.backup_key(values)
    (MEASURE/'parent').write_text(values['COMPOSE_PROJECT_NAME'])
    (MEASURE/'cgroups.yml').write_text('services:\n'+''.join('  '+name+':\n    cgroup_parent: /'+values['COMPOSE_PROJECT_NAME']+'\n' for name in SERVICES))
    (MEASURE/'services.json').write_text('{}');(MEASURE/'phase').write_text('prepare')
    pilot=Pilot(args)
    pilot.run()


if __name__=='__main__':main()

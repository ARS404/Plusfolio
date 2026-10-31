"""Recovery and versioned-S3 checks for the disposable capacity stack only."""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import subprocess
import tarfile
import time

S3_CHECK = '''
import json,os,sys,time
from pathlib import Path
sys.path.insert(0,'scripts')
from server_s3 import client,download
assert os.environ['BACKUP_S3_BUCKET']=='plusfolio-capacity'
assert os.environ['BACKUP_S3_ENDPOINT']=='https://object-store:5000'
s=client();bucket='plusfolio-capacity';key='pilot/capacity-version-canary'
lifecycle={'Rules':[
    {'ID':'pilot-retention','Status':'Enabled','Filter':{'Prefix':'pilot/'},'Expiration':{'Days':14},
     'NoncurrentVersionExpiration':{'NoncurrentDays':1},'AbortIncompleteMultipartUpload':{'DaysAfterInitiation':1}},
    {'ID':'pilot-expired-delete-markers','Status':'Enabled','Filter':{'Prefix':'pilot/'},
     'Expiration':{'ExpiredObjectDeleteMarker':True}}]}
s.put_bucket_lifecycle_configuration(Bucket=bucket,LifecycleConfiguration=lifecycle)
assert s.get_bucket_lifecycle_configuration(Bucket=bucket)['Rules']==lifecycle['Rules']
old=s.put_object(Bucket=bucket,Key=key,Body=b'old-test-version')['VersionId']
new=s.put_object(Bucket=bucket,Key=key,Body=b'new-test-version')['VersionId']
marker=s.delete_object(Bucket=bucket,Key=key)['VersionId']
assert s.get_object(Bucket=bucket,Key=key,VersionId=old)['Body'].read()==b'old-test-version'
s.delete_object(Bucket=bucket,Key=key,VersionId=old)
try:s.get_object(Bucket=bucket,Key=key,VersionId=old)
except s.exceptions.ClientError as error:assert error.response['ResponseMetadata']['HTTPStatusCode']==404
else:raise AssertionError('Old version still exists')
s.delete_object(Bucket=bucket,Key=key,VersionId=new)
s.delete_object(Bucket=bucket,Key=key,VersionId=marker)
remaining=s.list_object_versions(Bucket=bucket,Prefix=key)
assert not remaining.get('Versions') and not remaining.get('DeleteMarkers')
versions=s.list_object_versions(Bucket=bucket,Prefix='pilot/').get('Versions',[])
newest=max((row for row in versions if row['Key'].endswith('.age')),key=lambda row:row['LastModified'])
target=Path('/backups/capacity-download-'+str(time.time_ns())+'.age')
download('s3://'+bucket+'/'+newest['Key'],target,os.environ)
print(json.dumps({'download':str(target),'bytes':newest['Size'],'stored_versions':len(versions),
    'stored_bytes':sum(row['Size'] for row in versions),'version_deletion_verified':True,
    'lifecycle_configuration_verified':True,'lifecycle_scheduler_executed':False}))
'''


class ByteCounter:
    def __init__(self):self.size=0
    def write(self,data):self.size+=len(data);return len(data)
    def flush(self):pass


def component_sizes(directory):
    """Separate gzip(level=1) tar streams; figures include each component's headers."""
    groups=defaultdict(list)
    for path in directory.rglob('*'):
        if not path.is_file():continue
        name=path.relative_to(directory).as_posix()
        kind=('database' if name=='database.dump' else 'model' if name.startswith('model/') else
              'tex' if name.startswith('source/.local/') else 'source_and_config')
        groups[kind].append((name,path))
    result={}
    for kind,paths in groups.items():
        counter=ByteCounter()
        with tarfile.open(fileobj=counter,mode='w|gz',compresslevel=1) as archive:
            for name,path in sorted(paths):
                info=tarfile.TarInfo(name);info.size=path.stat().st_size;info.mode=0o600
                with path.open('rb') as stream:archive.addfile(info,stream)
        result[kind]={'gzip_tar_bytes':counter.size,'source_bytes':sum(path.stat().st_size for _,path in paths)}
    return result


def verify(pilot, *, standalone=False):
    import server
    measure=server.STATE/'capacity'
    command=['run','--rm','--no-deps','-T','backup'] if standalone else ['exec','-T','backup']
    result=json.loads(pilot.compose(*command,'python','-c',S3_CHECK,stdout=subprocess.PIPE).stdout)
    archive=measure/Path(result['download']).name
    with archive.open('xb') as target:
        pilot.compose(*command,'python','-c',
            "import shutil,sys;shutil.copyfileobj(open(sys.argv[1],'rb'),sys.stdout.buffer,1024*1024)",
            result['download'],stdout=target)
    restored=measure/('restored-'+str(time.time_ns()))
    server.operate(argparse.Namespace(command='restore-backup',file=str(archive),key=str(server.STATE/'backup.key'),
        into=str(restored),image=pilot.args.app_image),pilot.values)
    database='capacity_restore_'+str(time.time_ns())
    pilot.compose('exec','-T','db','createdb','-U','postgres','--owner=plusfolio',database)
    pilot.compose('exec','-T','db','psql','-U','postgres','-d',database,'-v','ON_ERROR_STOP=1','-c',
                  'CREATE EXTENSION vector; CREATE EXTENSION pg_trgm;',stdout=subprocess.DEVNULL)
    query='SELECT (SELECT count(*) FROM core_user),(SELECT count(*) FROM core_problem),(SELECT count(*) FROM core_worksheet),(SELECT count(*) FROM core_solve),(SELECT count(*) FROM core_assignment)'
    before=pilot.sql(query)
    try:
        with (restored/'database.dump').open('rb') as stream:
            pilot.compose('run','--rm','--no-deps','-T','-e','POSTGRES_DB='+database,'web',
                          'python','deploy/restore_database.py',stdin=stream)
        after=pilot.compose('exec','-T','db','psql','-U','postgres','-d',database,'-At','-c',query,stdout=subprocess.PIPE).stdout.decode().strip()
        assert before==after,(before,after)
        result.update(restored_counts=[int(n) for n in after.split('|')],restore_verified=True,
                      components=component_sizes(restored))
    finally:pilot.compose('exec','-T','db','dropdb','-U','postgres',database)
    return result


def image_storage(docker,current,previous,into):
    """Docker's OCI export preserves compressed layer blobs; deduplicate by blob hash."""
    result={}
    blobs={}
    unpacked={}
    for kind,images in [('current',current),('previous',previous)]:
        if not images:
            blobs[kind]={}
            unpacked[kind]={}
            result[kind]={'archive_bytes':0,'unique_blob_bytes':0,'unpacked_layer_bytes':0}
            continue
        target=Path(into)/(kind+'-images.tar')
        docker('image','save','--output',str(target),*images,stdout=subprocess.DEVNULL)
        entries={};layers=set();expanded={}
        with tarfile.open(target) as archive:
            for member in archive:
                if member.isfile() and member.name.startswith('blobs/sha256/'):
                    entries[member.name]=member.size
                    if member.size<1024*1024:
                        with archive.extractfile(member) as stream:
                            prefix=stream.read(1)
                            if prefix==b'{':
                                metadata=json.loads(prefix+stream.read())
                                layers.update('blobs/'+row['digest'].replace(':','/') for row in metadata.get('layers',[]))
            for name in layers:
                with archive.extractfile(name) as stream:
                    header=stream.read(2);stream.seek(0)
                    if header==b'\x1f\x8b':
                        with gzip.GzipFile(fileobj=stream) as plain:
                            expanded[name]=sum(len(block) for block in iter(lambda:plain.read(1024*1024),b''))
                    elif header==b'\x28\xb5':raise ValueError('Zstd layer size is not measured by this gzip benchmark')
                    else:expanded[name]=entries[name]
        blobs[kind]=entries
        unpacked[kind]=expanded
        result[kind]={'archive_bytes':target.stat().st_size,'unique_blob_bytes':sum(entries.values()),
                      'unpacked_layer_bytes':sum(expanded.values())}
        target.unlink()
    all_blobs={**blobs['current'],**blobs['previous']}
    result['combined_unique_blob_bytes']=sum(all_blobs.values())
    result['previous_extra_blob_bytes']=sum(size for name,size in blobs['previous'].items() if name not in blobs['current'])
    result['combined_unpacked_layer_bytes']=sum({**unpacked['current'],**unpacked['previous']}.values())
    return result


def registry_storage(endpoint, groups):
    """Read OCI descriptors from the anonymous, disposable registry used by the test."""
    import hashlib
    import urllib.request
    accept=','.join(['application/vnd.oci.image.index.v1+json','application/vnd.oci.image.manifest.v1+json',
                     'application/vnd.docker.distribution.manifest.list.v2+json','application/vnd.docker.distribution.manifest.v2+json'])
    manifests={}
    def collect(repository,reference):
        key=(repository,reference)
        if key in manifests:return manifests[key]
        request=urllib.request.Request(endpoint+'/v2/'+repository+'/manifests/'+reference,headers={'Accept':accept})
        with urllib.request.urlopen(request,timeout=30) as response:raw=response.read()
        data=json.loads(raw)
        result={'sha256:'+hashlib.sha256(raw).hexdigest():len(raw)}
        for entry in data.get('manifests',[]):result.update(collect(repository,entry['digest']))
        descriptors=data.get('layers',[])
        if 'config' in data:descriptors=[data['config'],*descriptors]
        for entry in descriptors:result[entry['digest']]=entry['size']
        manifests[key]=result
        return result
    sets={};result={}
    for name,references in groups.items():
        blobs={}
        for repository,reference in references:blobs.update(collect(repository,reference))
        sets[name]=blobs;result[name+'_blob_bytes']=sum(blobs.values())
    combined={digest:size for values in sets.values() for digest,size in values.items()}
    result['combined_referenced_blob_bytes']=sum(combined.values())
    without_cache={digest:size for name,values in sets.items() if name!='cache' for digest,size in values.items()}
    result['cache_extra_blob_bytes']=sum(size for digest,size in sets.get('cache',{}).items() if digest not in without_cache)
    return result

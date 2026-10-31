"""Storage, immutable releases and off-server recovery; only synthetic data."""
import argparse,hashlib,io,json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import server,server_storage,server_images,server_backup,server_s3

RELEASE={'version':'1.0.0','status':'development','revision':'a'*40}


class StorageTests(unittest.TestCase):
    def test_dedicated_cpu_profile_is_explicit_and_does_not_change_shared_default(self):
        self.assertEqual([p.name for p in server_storage.compose_files({},ROOT)],['compose.yml'])
        values,_=server_storage.configuration({'resource_profile':'dedicated-pilot'})
        self.assertEqual(values,{'RESOURCE_PROFILE':'dedicated-pilot'})
        self.assertEqual([p.name for p in server_storage.compose_files(values,ROOT)],
                         ['compose.yml','compose.dedicated-pilot.yml'])
        with self.assertRaises(ValueError):server_storage.validate({'RESOURCE_PROFILE':'unknown'})

    def test_missing_or_wrong_mount_never_creates_a_database_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'data';target.mkdir()
            with patch('server_storage.os.path.ismount',return_value=False):
                with self.assertRaisesRegex(RuntimeError,'не смонтирован'):
                    server_storage.check_paths({'DB_DATA_DIR':str(target),'DB_MOUNTPOINT':str(root)},Mock(),{})
            absent=root/'absent'
            with self.assertRaises(RuntimeError):server_storage.check_paths({'DB_DATA_DIR':str(absent)},Mock(),{})
            self.assertFalse(absent.exists());self.assertEqual(list(target.iterdir()),[])
    def test_existing_volume_cannot_silently_keep_the_previous_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            docker=Mock(return_value=Mock(stdout=json.dumps([{'Options':{'device':'/old-ssd'}}]).encode()))
            config={'volumes':{'database':{'name':'own_database'}}}
            with self.assertRaisesRegex(RuntimeError,'Перенесите данные'):
                server_storage.check_paths({'DB_DATA_DIR':directory},docker,config)
            docker.assert_called_once();self.assertEqual(docker.call_args.args[:2],('volume','inspect'))
    def test_overlays_are_independent_and_external_database_requires_tls(self):
        values={'DB_DATA_DIR':'/ssd/postgres','BACKUP_DIR':'/hdd/backups','BACKUP_S3_BUCKET':'own'}
        names=[path.name for path in server_storage.compose_files(values,ROOT)]
        self.assertEqual(names,['compose.yml','compose.database-disk.yml','compose.backup-disk.yml','compose.s3.yml'])
        for changes in [{'DB_DATA_DIR':'relative'},{'POSTGRES_HOST':'remote'},{'BACKUP_S3_BUCKET':'own','BACKUP_S3_PREFIX':'../other'},{'BACKUP_S3_BUCKET':'own','BACKUP_S3_PREFIX':'instance/','BACKUP_S3_ENDPOINT':'http://remote'}]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):server_storage.validate(changes)
    def test_configuration_reads_secrets_from_files_and_restores_to_fresh_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);password=root/'password';password.write_text('synthetic')
            ca=root/'ca';ca.write_text('synthetic CA')
            credentials=root/'s3';credentials.write_text(json.dumps({'access_key_id':'synthetic','secret_access_key':'synthetic'}))
            values,files=server_storage.configuration({'backup_dir':'/hdd/backups','backup_s3':{'bucket':'own','prefix':'instance/','credentials_file':str(credentials),'storage_class':'COLD'},
                'database':{'host':'db.example.test','port':6432,'name':'plusfolio','user':'app','password_file':str(password),'ca_file':str(ca)}})
            self.assertEqual(values['PGSSLMODE'],'verify-full');self.assertEqual(values['POSTGRES_PORT'],'6432')
            self.assertNotIn('synthetic',json.dumps(values));self.assertEqual(set(files),{'db_password','db_ca','backup_s3_credentials'})
            restored=server_storage.for_restore({**values,'COMPOSE_PROJECT_NAME':'old','INSTANCE_ID':'old'})
            self.assertEqual(restored,{'COMPOSE_PROJECT_NAME':'old','INSTANCE_ID':'old'})
            self.assertEqual(values['POSTGRES_HOST'],'db.example.test')


class ImageTests(unittest.TestCase):
    def make_manifest(self,path,**changes):
        data={'format':'plusfolio-images-v1','release':RELEASE,'platform':'linux/amd64',
              'images':{kind:'registry.example.test/own/'+kind+'@sha256:'+'b'*64 for kind in server_images.IMAGES},**changes}
        path.write_text(json.dumps(data));return data
    def image(self):
        return {'Os':'linux','Architecture':'amd64','Config':{'Labels':{
            'org.opencontainers.image.version':'1.0.0','org.opencontainers.image.revision':'a'*40,'io.plusfolio.release-status':'development'}}}
    def test_pull_checks_digest_version_platform_and_revision_before_configuration_changes(self):
        with tempfile.TemporaryDirectory() as directory,patch('release.build_metadata',return_value=RELEASE):
            path=Path(directory)/'images.json';data=self.make_manifest(path)
            docker=Mock(return_value=Mock(stdout=json.dumps([self.image()]).encode()))
            values=server_images.pull(docker,ROOT,path)
            self.assertEqual(values,{key:data['images'][kind] for kind,key in server_images.IMAGES.items()})
            self.assertEqual(docker.call_count,6)
            wrong=self.image();wrong['Architecture']='arm64'
            docker.return_value=Mock(stdout=json.dumps([wrong]).encode())
            with self.assertRaisesRegex(ValueError,'платформа'):server_images.pull(docker,ROOT,path)
            self.make_manifest(path,images={kind:'registry.example.test/'+kind+':latest' for kind in server_images.IMAGES})
            with self.assertRaisesRegex(ValueError,'digest'):server_images.manifest(path,ROOT)
            self.make_manifest(path,release={**RELEASE,'revision':'c'*40})
            with self.assertRaisesRegex(ValueError,'commit'):server_images.manifest(path,ROOT)
    def test_registry_cache_and_publishing_reuse_the_bounded_private_builder(self):
        import server_host
        values=server_host.shared_values({'COMPOSE_PROJECT_NAME':'own','INSTANCE_ID':'synthetic','BUILD_CACHE_REGISTRY':'registry.example.test/separate/cache'})
        docker=Mock(return_value=Mock(stdout=b'default\n'))
        server_host.build_images(docker,values,ROOT,push=True,platform='linux/amd64',metadata='/tmp/metadata.json')
        bake=next(call.args for call in docker.call_args_list if call.args[:2]==('buildx','bake'))
        self.assertIn('--push',bake);self.assertNotIn('--load',bake)
        self.assertIn('web.cache-to=type=registry,ref=registry.example.test/separate/cache/web,mode=max,image-manifest=true,oci-mediatypes=true',bake)
        self.assertIn('*.platform=linux/amd64',bake)
        self.assertEqual(docker.call_args.args[:2],('buildx','stop'))
    def test_offline_archive_preserves_digest_images_and_detects_corruption_before_load(self):
        with tempfile.TemporaryDirectory() as directory:
            archive=Path(directory)/'images.tar';image='registry.example.test/own/app@sha256:'+'b'*64
            image_id='sha256:'+'c'*64
            def docker(*args,**kwargs):
                if args[:2]==('image','save'):
                    Path(args[3]).write_bytes(b'synthetic image archive')
                return Mock(stdout=json.dumps([{'Id':image_id}]).encode())
            server_images.export_archive(docker,[image],archive)
            aliases=server_images.import_archive(docker,archive)
            self.assertTrue(aliases[image].startswith('plusfolio-recovery/image:'))
            with self.assertRaises(ValueError):server_images.export_archive(docker,[image],archive)
            archive.chmod(0o600);archive.write_bytes(b'corrupt')
            runner=Mock(side_effect=AssertionError('must not load corrupt archive'))
            with self.assertRaisesRegex(ValueError,'сумма'):server_images.import_archive(runner,archive)
            runner.assert_not_called()

    def test_failed_preupdate_backup_prevents_migrations_and_keeps_existing_configuration(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(server,'STATE',Path(directory)):
            values=server.server_host.shared_values({'COMPOSE_PROJECT_NAME':'own','INSTANCE_ID':'synthetic'})
            server.write_env(values);before=(server.STATE/'env').read_bytes()
            running=[{'State':{'Running':True},'Config':{'Labels':{'com.docker.compose.service':'web'}}}]
            with patch('server.preflight',return_value=(running,{'cpus':2,'memory_mib':3392})),patch('server.compose',side_effect=RuntimeError('synthetic backup failure')) as compose,patch('server.backup_key') as key,patch('builtins.print'):
                with self.assertRaisesRegex(RuntimeError,'backup failure'):
                    server.run(argparse.Namespace(command='update',no_build=True,release=None))
            self.assertEqual((server.STATE/'env').read_bytes(),before);key.assert_not_called()
            self.assertEqual(compose.call_args.args[:3],('exec','-T','backup'))


class S3Tests(unittest.TestCase):
    values={'BACKUP_S3_BUCKET':'own','BACKUP_S3_PREFIX':'instance/','BACKUP_S3_STORAGE_CLASS':'COLD'}
    def test_upload_sends_only_encrypted_file_and_checks_remote_size_and_checksum(self):
        from botocore.exceptions import ClientError
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'plusfolio-test.tar.gz.age';path.write_bytes(b'synthetic-encrypted-bytes')
            checksum=hashlib.sha256(path.read_bytes()).hexdigest()
            head={'ContentLength':path.stat().st_size,'Metadata':{'sha256':checksum}}
            missing=ClientError({'ResponseMetadata':{'HTTPStatusCode':404},'Error':{'Code':'NoSuchKey'}},'HeadObject')
            s3=Mock();s3.head_object.side_effect=[missing,head]
            with patch('server_s3.client',return_value=s3):
                self.assertEqual(server_s3.upload(path,self.values),'s3://own/instance/'+path.name)
                self.assertEqual(s3.upload_file.call_args.kwargs['ExtraArgs'],{'StorageClass':'COLD','Metadata':{'sha256':checksum}})
                s3.upload_file.reset_mock();s3.head_object.side_effect=None;s3.head_object.return_value=head
                server_s3.upload(path,self.values)
                s3.upload_file.assert_not_called()
                s3.head_object.return_value={**head,'ContentLength':path.stat().st_size+1}
                with self.assertRaises(RuntimeError):server_s3.upload(path,self.values)
    def test_failed_offsite_upload_keeps_two_local_snapshots_and_never_marks_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            archives=[root/f'plusfolio-20261031T00000000000{n}Z.tar.gz.age' for n in range(1,4)]
            for archive in archives:archive.write_bytes(b'encrypted')
            archive=archives[-1]
            with patch.dict(os.environ,{'BACKUP_MAX_COUNT':'2'}),patch('server_backup.Path',side_effect=lambda name:root if name=='/backups' else Path(name)),patch('server_backup._backup',return_value=archive),patch('server_s3.upload',side_effect=RuntimeError('upload failed')):
                with self.assertRaises(RuntimeError):server_backup.backup()
            self.assertFalse((root/'last-success').exists());self.assertEqual(archive.read_bytes(),b'encrypted')
            self.assertEqual(sorted(root.glob('*.age')),archives[-2:])
            self.assertEqual((root/'.upload-pending').read_text(),archive.name)
    def test_worker_retries_the_same_archive_but_manual_update_always_gets_a_fresh_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=root/'plusfolio-20261031T000000000001Z.tar.gz.age';old.write_bytes(b'first')
            new=root/'plusfolio-20261031T000000000002Z.tar.gz.age';new.write_bytes(b'second')
            os.utime(old,(time.time()-3600,)*2)
            (root/'.upload-pending').write_text(old.name)
            with patch.dict(os.environ,{'BACKUP_S3_BUCKET':'synthetic'}),patch('server_backup.Path',side_effect=lambda name:root if name=='/backups' else Path(name)),patch('server_backup._backup',return_value=new) as create,patch('server_s3.upload',return_value=None) as upload:
                self.assertEqual(server_backup.backup(retry_pending=True),old);create.assert_not_called()
                self.assertFalse((root/'.upload-pending').exists())
                self.assertEqual(float((root/'last-success').read_text()),old.stat().st_mtime)
                (root/'.upload-pending').write_text(old.name)
                self.assertEqual(server_backup.backup(),new);create.assert_called_once()
                self.assertEqual([call.args[0] for call in upload.call_args_list],[old,new])
    def test_stale_pending_upload_never_stops_daily_local_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=root/'plusfolio-20261030T000000000001Z.tar.gz.age';old.write_bytes(b'old')
            os.utime(old,(time.time()-90000,)*2)
            new=root/'plusfolio-20261031T000000000001Z.tar.gz.age';new.write_bytes(b'fresh')
            (root/'.upload-pending').write_text(old.name)
            with patch.dict(os.environ,{'BACKUP_S3_BUCKET':'synthetic','BACKUP_INTERVAL':'86400'}),patch('server_backup.Path',side_effect=lambda name:root if name=='/backups' else Path(name)),patch('server_backup._backup',return_value=new) as create,patch('server_s3.upload',return_value=None):
                self.assertEqual(server_backup.backup(retry_pending=True),new);create.assert_called_once()
            self.assertEqual(float((root/'last-success').read_text()),new.stat().st_mtime)
    def test_download_checks_real_bytes_removes_failed_partial_and_never_overwrites(self):
        body=b'encrypted synthetic archive';checksum=hashlib.sha256(body).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'backup.age';s3=Mock()
            def response(**kwargs):return {'Body':io.BytesIO(body),'ContentLength':len(body),'Metadata':{'sha256':checksum}}
            s3.get_object.side_effect=response
            with patch('server_s3.client',return_value=s3):
                server_s3.download('s3://own/instance/backup.tar.gz.age',path,self.values)
                self.assertEqual(path.read_bytes(),body);self.assertEqual(path.stat().st_mode & 0o777,0o600)
                with self.assertRaises(FileExistsError):server_s3.download('s3://own/instance/backup.tar.gz.age',path,self.values)
                self.assertEqual(path.read_bytes(),body)
                broken=Path(directory)/'broken.age';s3.get_object.side_effect=lambda **kwargs:{**response(),'Metadata':{'sha256':'wrong'}}
                with self.assertRaises(RuntimeError):server_s3.download('s3://own/instance/backup.tar.gz.age',broken,self.values)
                self.assertFalse(broken.exists())
                with self.assertRaises(ValueError):server_s3.download('s3://other/instance/backup.tar.gz.age',broken,self.values)


if __name__=='__main__':unittest.main()

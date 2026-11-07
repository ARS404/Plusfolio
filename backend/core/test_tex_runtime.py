import hashlib,importlib.util,io,json,os,subprocess,sys,tarfile
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock,patch
from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase,override_settings
from .documents import project_for,render_pdf
from .tex_runtime import check_workspace,job_directory,prune_jobs,run_compiler


class CompilerWorkspaceTests(SimpleTestCase):
    def test_remote_preview_encodes_project_once_and_sends_without_frame_copy(self):
        project=project_for(SimpleNamespace(title='Предпросмотр',description=''),[])
        response=json.dumps({'pdf':'JVBERi10ZXN0','warnings':[]}).encode()
        class Socket:
            def __init__(self):self.frames=[]
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def settimeout(self,*args):pass
            def connect(self,*args):pass
            def sendall(self,value):self.frames.append(value)
            def makefile(self,*args):return io.BytesIO(str(len(response)).encode()+b'\n'+response)
        client=Socket()
        with TemporaryDirectory() as directory,override_settings(LOCAL_DIR=Path(directory),TEX_SOCKET='fake'):
            with patch('core.tex_remote.socket.socket',return_value=client),patch('core.documents.json.dumps',wraps=json.dumps) as encode:
                self.assertEqual(render_pdf(project,cache=False),b'%PDF-test')
            self.assertEqual(sum(call.args[0] is project for call in encode.call_args_list),1)
            self.assertEqual(len(client.frames),2)
            self.assertEqual(int(client.frames[0]),len(client.frames[1]))
            self.assertEqual(json.loads(client.frames[1]),project)
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_oversized_cached_pdf_is_rejected_before_reading(self):
        from .tex_cache import ArtifactCache,pdf_cache
        from .tex_project import MAX_PDF_BYTES
        with TemporaryDirectory() as directory,override_settings(LOCAL_DIR=Path(directory)):
            cache=pdf_cache();cache.directory.mkdir()
            path=cache.directory/('a'*64+'.pdf')
            with path.open('wb') as stream:stream.truncate(MAX_PDF_BYTES+1)
            original=Path.open
            def open_file(candidate,*args,**kwargs):
                if candidate==path:raise AssertionError('Oversized cache entry must not be read')
                return original(candidate,*args,**kwargs)
            with patch.object(Path,'open',open_file):self.assertIsNone(cache.get('a'*64))
            self.assertFalse(path.exists())
            bounded=ArtifactCache(Path(directory)/'small','pdf',max_bytes=8,max_entries=1,max_age=60,max_artifact_bytes=4)
            self.assertFalse(bounded.put('a'*64,b'12345'))

    def test_deep_workspace_keeps_only_one_directory_iterator_open(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);deep=root
            for _ in range(60):deep=deep/'d';deep.mkdir()
            (deep/'file').write_bytes(b'ok')
            original=os.scandir;active=0;peak=0
            class TrackedDirectory:
                def __init__(self,path):self.directory=original(path)
                def __enter__(self):
                    nonlocal active,peak
                    active+=1;peak=max(peak,active);return self.directory
                def __exit__(self,*args):
                    nonlocal active
                    self.directory.close();active-=1
            with patch('core.tex_runtime.os.scandir',TrackedDirectory):
                self.assertEqual(check_workspace(root),{'bytes':2,'entries':61})
            self.assertEqual(peak,1);self.assertEqual(active,0)

    def test_fast_finished_compiler_still_obeys_file_count_limit_and_cleans_job(self):
        with TemporaryDirectory() as directory:
            jobs=Path(directory)/'jobs'
            process=Mock(returncode=0);process.wait.return_value=0;process.poll.return_value=0
            with self.assertRaisesRegex(ValueError,'2048'),patch('core.tex_runtime.subprocess.Popen',return_value=process):
                with job_directory(jobs) as work:
                    for index in range(2049):(work/str(index)).touch()
                    run_compiler(['finished'],work,{})
            self.assertEqual(list(jobs.iterdir()),[])

    def test_workspace_scan_never_follows_file_or_directory_symlinks(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);work=root/'work';outside=root/'outside';work.mkdir();outside.mkdir()
            (outside/'large').write_bytes(b'x'*1024)
            (work/'file-link').symlink_to(outside/'large');(work/'dir-link').symlink_to(outside,target_is_directory=True)
            (work/'actual').write_bytes(b'ok')
            self.assertEqual(check_workspace(work,max_bytes=2),{'entries':1,'bytes':2})
            self.assertEqual((outside/'large').stat().st_size,1024)

    def test_preview_cleanup_uses_stable_root_and_preserves_live_jobs_and_linked_resources(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);local=root/'runtime';local.mkdir();resources=root/'trusted';resources.mkdir()
            (resources/'font').write_bytes(b'keep')
            previews=root/'.local/tex-previews';previews.mkdir(parents=True)
            with job_directory(previews) as active,override_settings(BASE_DIR=root,LOCAL_DIR=local):
                orphan=previews/('job-'+'e'*32);orphan.mkdir();(orphan/'tectonic-cache').symlink_to(resources,target_is_directory=True)
                nested=orphan/'tex-jobs'/('job-'+'d'*32);nested.mkdir(parents=True);(nested/'main.tex').write_text('abandoned draft')
                os.utime(orphan,(0,0));os.utime(active,(0,0));output=io.StringIO();call_command('tex_cache',stdout=output)
                self.assertEqual(json.loads(output.getvalue())['abandoned_previews']['removed'],1)
                self.assertFalse(orphan.exists());self.assertTrue(active.exists())
                self.assertEqual((resources/'font').read_bytes(),b'keep')

            self.assertEqual(list(previews.iterdir()),[])

    def test_orphan_removed_by_another_worker_does_not_abort_cleanup(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);orphan=root/('job-'+'f'*32);orphan.mkdir();os.utime(orphan,(0,0))
            original_stat=Path.stat;original_dir=Path.is_dir;original_link=Path.is_symlink
            def stat(path,*args,**kwargs):
                if path==orphan:raise FileNotFoundError()
                return original_stat(path,*args,**kwargs)
            def is_dir(path,*args,**kwargs):return True if path==orphan else original_dir(path,*args,**kwargs)
            def is_symlink(path):return False if path==orphan else original_link(path)
            with patch.object(Path,'stat',stat),patch.object(Path,'is_dir',is_dir),patch.object(Path,'is_symlink',is_symlink):
                self.assertEqual(prune_jobs(root),{'removed':0})


    def test_uncached_preview_serializes_once_without_calculating_cache_fingerprint(self):
        project=project_for(SimpleNamespace(title='Предпросмотр',description=''),[])
        with TemporaryDirectory() as directory,override_settings(LOCAL_DIR=Path(directory),TEX_SOCKET='fake'):
            import json
            with patch('core.tex_remote.compile_project',return_value=b'%PDF-test'),patch('core.documents.json.dumps',wraps=json.dumps) as encode,patch('core.documents.hashlib.sha256') as fingerprint:
                self.assertEqual(render_pdf(project,cache=False),b'%PDF-test')
            self.assertEqual(sum(call.args[0] is project for call in encode.call_args_list),1)
            fingerprint.assert_not_called();self.assertEqual(list(Path(directory).iterdir()),[])


class TrustedPreparationTests(SimpleTestCase):
    def load_installer(self):
        spec=importlib.util.spec_from_file_location('setup_tex_test',settings.BASE_DIR/'scripts/setup_tex.py')
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'download_asset':SimpleNamespace(download=Mock())}):spec.loader.exec_module(module)
        return module

    def test_receipt_killed_before_publish_is_reclaimed_without_hashing_legacy_temporaries(self):
        from .tex_resources import PREPARATION_FILE,PREPARATION_SOURCES,record_preparation,resource_files
        with TemporaryDirectory() as directory:
            root=Path(directory)
            for name in PREPARATION_SOURCES:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('trusted preparation source')
            cache=root/'.local/tectonic-cache';cache.mkdir(parents=True);(cache/'font').write_bytes(b'trusted')
            stale=cache/('.prepared-'+'a'*32+'.tmp');stale.write_bytes(b'abandoned');os.utime(stale,(0,0))
            fresh=cache/('.prepared-'+'b'*32+'.tmp');fresh.write_bytes(b'possibly active')
            outside=root/'outside';outside.write_bytes(b'keep')
            link=cache/('.prepared-'+'c'*32+'.tmp');link.symlink_to(outside)
            self.assertEqual(set(resource_files(cache)),{'font'})
            command=("import os,signal,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
                     "import core.tex_resources as resources\n"
                     "def interrupted(source,target):\n"
                     " print(source,flush=True);os.kill(os.getpid(),signal.SIGKILL)\n"
                     "resources.os.replace=interrupted\n"
                     "resources.record_preparation(Path(sys.argv[2]),Path(sys.argv[3]))")
            killed=subprocess.run([sys.executable,'-c',command,str(settings.BASE_DIR/'backend'),str(root),str(cache)],stdout=subprocess.PIPE,check=False)
            self.assertLess(killed.returncode,0)
            staged=Path(killed.stdout.decode().strip());self.assertTrue(staged.exists());self.assertFalse((cache/PREPARATION_FILE).exists())
            os.utime(staged.parent,(0,0));record_preparation(root,cache)
            self.assertFalse(staged.parent.exists());self.assertEqual(list((cache.parent/'.tex-preparation-jobs').iterdir()),[])
            self.assertFalse(stale.exists());self.assertTrue(fresh.exists());self.assertTrue(link.is_symlink());self.assertEqual(outside.read_bytes(),b'keep')
            self.assertEqual(json.loads((cache/PREPARATION_FILE).read_bytes())['resources'],{'font':hashlib.sha256(b'trusted').hexdigest()})

    def test_compiler_installation_streams_verified_archive_and_replaces_atomically(self):
        module=self.load_installer()
        with TemporaryDirectory() as directory:
            root=Path(directory);asset=root/'compiler.tar.gz';binary=root/'tectonic';payload=b'compiler'*100000
            with tarfile.open(asset,'w:gz') as archive:
                member=tarfile.TarInfo('release/tectonic');member.size=len(payload);archive.addfile(member,io.BytesIO(payload))
            with asset.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            binary.write_bytes(b'previous')
            def interrupted(source,target):target.write(b'partial');raise OSError('interrupted')
            with patch.object(module.shutil,'copyfileobj',side_effect=interrupted),self.assertRaises(OSError):module.install_compiler(asset,binary,digest)
            self.assertEqual(binary.read_bytes(),b'previous');self.assertEqual(set(root.iterdir()),{asset,binary})
            with self.assertRaisesRegex(RuntimeError,'checksum'):module.install_compiler(asset,binary,'0'*64)
            self.assertEqual(binary.read_bytes(),b'previous')
            with patch.object(Path,'read_bytes',side_effect=AssertionError('must not load the archive or compiler into memory')):
                module.install_compiler(asset,binary,digest)
            self.assertEqual(binary.read_bytes(),payload);self.assertTrue(binary.stat().st_mode&0o100)
            self.assertEqual(set(root.iterdir()),{asset,binary})

    def test_resource_snapshot_replaces_old_files_without_following_links(self):
        module=self.load_installer()
        with TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';destination=root/'cache';outside=root/'outside'
            source.mkdir();outside.mkdir();(outside/'keep').write_bytes(b'private')
            (source/'resource').write_bytes(b'current');(source/'plusfolio-prepared.json').write_bytes(b'receipt')
            (source/('.prepared-'+'a'*32+'.tmp')).write_bytes(b'abandoned metadata')
            (source/'linked-file').symlink_to(outside/'keep');(source/'linked-directory').symlink_to(outside,target_is_directory=True)
            destination.symlink_to(outside,target_is_directory=True)
            module.copy_resources(source,destination)
            self.assertFalse(destination.is_symlink())
            self.assertEqual({p.name for p in destination.iterdir()},{'resource','plusfolio-prepared.json'})
            self.assertEqual((outside/'keep').read_bytes(),b'private')
            self.assertEqual({p.name for p in root.iterdir()},{'source','cache','outside','.tex-resource-jobs'})
            self.assertEqual(list((root/'.tex-resource-jobs').iterdir()),[])
            (destination/'obsolete').write_bytes(b'old bundle')
            module.copy_resources(source,destination)
            self.assertEqual({p.name for p in destination.iterdir()},{'resource','plusfolio-prepared.json'})

    def test_failed_snapshot_copy_or_publication_preserves_existing_resources(self):
        module=self.load_installer()
        for failure in ['copy','publish']:
            with self.subTest(failure=failure),TemporaryDirectory() as directory:
                root=Path(directory);source=root/'source';destination=root/'cache';source.mkdir();destination.mkdir()
                (source/'new').write_bytes(b'new');(destination/'old').write_bytes(b'keep')
                original_replace=Path.replace
                def replace(path,target):
                    if path.name=='cache' and path.parent.parent.name=='.tex-resource-jobs':
                        raise OSError('interrupted publication')
                    return original_replace(path,target)
                if failure=='copy':context=patch.object(module.shutil,'copy2',side_effect=OSError('interrupted copy'))
                else:context=patch.object(Path,'replace',replace)
                with context,self.assertRaises(OSError):module.copy_resources(source,destination)
                self.assertEqual((destination/'old').read_bytes(),b'keep')
                self.assertEqual({p.name for p in root.iterdir()},{'source','cache','.tex-resource-jobs'})
                self.assertEqual(list((root/'.tex-resource-jobs').iterdir()),[])

    def test_resource_snapshot_budget_is_checked_before_copying(self):
        module=self.load_installer()
        from .tex_resources import MAX_RESOURCE_BYTES
        with TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.mkdir();destination=root/'cache';destination.mkdir()
            (destination/'old').write_bytes(b'keep')
            with (source/'huge').open('wb') as stream:stream.truncate(MAX_RESOURCE_BYTES+1)
            with patch.object(module.shutil,'copy2') as copy,self.assertRaises(ValueError):module.copy_resources(source,destination)
            copy.assert_not_called()
            self.assertEqual((destination/'old').read_bytes(),b'keep')
            self.assertEqual({p.name for p in root.iterdir()},{'source','cache'})

    def test_snapshot_reclaims_killed_job_without_removing_a_live_lease(self):
        module=self.load_installer()
        with TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source';source.mkdir();(source/'resource').write_bytes(b'current')
            jobs=root/'.tex-resource-jobs'
            command=("import os,signal,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
                     "from core.tex_runtime import job_directory\n"
                     "with job_directory(sys.argv[2]) as work:\n"
                     " (work/'abandoned').write_bytes(b'partial');print(work,flush=True);os.kill(os.getpid(),signal.SIGKILL)")
            with job_directory(jobs) as active:
                killed=subprocess.run([sys.executable,'-c',command,str(settings.BASE_DIR/'backend'),str(jobs)],stdout=subprocess.PIPE,check=False)
                self.assertLess(killed.returncode,0)
                orphan=Path(killed.stdout.decode().strip());self.assertTrue((orphan/'abandoned').exists());os.utime(orphan,(0,0));os.utime(active,(0,0))
                module.copy_resources(source,root/'cache')
                self.assertFalse(orphan.exists());self.assertTrue(active.exists())
            self.assertEqual(list(jobs.iterdir()),[])

    def test_template_timeout_cleans_its_leased_workspace(self):
        module=self.load_installer()
        with TemporaryDirectory() as directory:
            root=Path(directory);templates=root/'backend/core/tex_templates';templates.mkdir(parents=True)
            (templates/'math-a4-v2.tex').write_text('trusted template')
            with patch.object(module,'ROOT',root),patch.object(module.subprocess,'run',side_effect=subprocess.TimeoutExpired('compiler',60)),redirect_stdout(io.StringIO()):
                with self.assertRaises(subprocess.TimeoutExpired):module.prepare_templates('compiler',root/'cache',root/'config',offline=True)
            self.assertEqual(list((root/'.local/tex-setup-jobs').iterdir()),[])

    def test_cached_preparation_checks_each_supported_template_once(self):
        self.check_preparation(cached=True,expected=['v2','v1'])

    def test_downloaded_preparation_keeps_final_offline_verification(self):
        self.check_preparation(cached=False,expected=['v2','v2','v2','v1'])

    def test_portable_preparation_checks_a_copy_and_never_downloads_resources(self):
        self.check_portable_preparation(complete=True)

    def test_portable_preparation_rejects_missing_packages_without_online_fallback(self):
        self.check_portable_preparation(complete=False)

    def check_portable_preparation(self,*,complete):
        module=self.load_installer()
        with TemporaryDirectory() as directory:
            root=Path(directory);tools=root/'.local/tools';tools.mkdir(parents=True);(tools/'tectonic').write_bytes(b'compiler')
            resources=root/'.local/tectonic-cache';resources.mkdir();(resources/'resource').write_bytes(b'frozen bytes')
            templates=root/'backend/core/tex_templates';templates.mkdir(parents=True)
            for version in ['v1','v2']:(templates/f'math-a4-{version}.tex').write_text(version)
            def compile(command,**kwargs):
                self.assertIn('--only-cached',command)
                cache=Path(kwargs['env']['TECTONIC_CACHE_DIR'])
                self.assertNotEqual(cache,resources)
                (cache/'resource').write_bytes(b'compiler cache mutation')
                (cache/'generated-format').write_bytes(b'temporary format')
                return SimpleNamespace(returncode=0 if complete else 1)
            with patch.object(module,'ROOT',root),patch.object(module.subprocess,'check_output',return_value='Tectonic 0.17.0'),patch.object(module.subprocess,'run',side_effect=compile) as run,patch.object(module,'record_preparation') as record,redirect_stdout(io.StringIO()):
                if complete:module.main(['--offline'])
                else:
                    with self.assertRaisesRegex(RuntimeError,'incomplete'):module.main(['--offline'])
            self.assertEqual(run.call_count,2 if complete else 1)
            record.assert_not_called()
            self.assertEqual(list(resources.iterdir()),[resources/'resource'])
            self.assertEqual((resources/'resource').read_bytes(),b'frozen bytes')
            self.assertEqual(list((root/'.local/tex-setup-jobs').iterdir()),[])

    def check_preparation(self,*,cached,expected):
        module=self.load_installer()
        with TemporaryDirectory() as directory:
            root=Path(directory);tools=root/'.local/tools';tools.mkdir(parents=True);(tools/'tectonic').write_bytes(b'compiler')
            templates=root/'backend/core/tex_templates';templates.mkdir(parents=True)
            for version in ['v1','v2']:(templates/f'math-a4-{version}.tex').write_text(version)
            for name in ['scripts/setup_tex.py','backend/core/tex_resources.py','backend/core/tex_runtime.py']:
                source=root/name;source.parent.mkdir(parents=True,exist_ok=True);source.write_text('trusted installer')
            seen=[]
            def compile(command,**kwargs):
                seen.append((Path(kwargs['cwd'])/'template.tex').read_text())
                return SimpleNamespace(returncode=0 if cached or len(seen)>1 else 1)
            with patch.object(module,'ROOT',root),patch.dict(os.environ,{'PLUSFOLIO_TEX_SHARED_CACHE':str(root/'.local/tectonic-cache')}),patch.object(module.subprocess,'check_output',return_value='Tectonic 0.17.0'),patch.object(module.subprocess,'run',side_effect=compile),redirect_stdout(io.StringIO()):
                module.main([])
            self.assertEqual(seen,expected)

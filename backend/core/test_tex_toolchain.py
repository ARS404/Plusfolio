import importlib.util
import io
import json
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import zipfile
from django.conf import settings
from django.test import SimpleTestCase,TestCase,override_settings
from rest_framework.test import APIClient
from .documents import project_for
from .tex_toolchain import SOURCE_FILES,build_contract,toolchain_archive
from .models import User
from .tex_resources import PREPARATION_FILE, record_preparation, trusted_paths


@override_settings(TEX_RESOURCE_DIR=None)
class PortableToolchainTests(SimpleTestCase):
    def prepared_fixture(self,root):
        for name in SOURCE_FILES:
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text("VERSION='0.17.0'\n" if name=='scripts/setup_tex.py' else 'trusted source')
        resources=root/'.local/tectonic-cache';resources.mkdir(parents=True)
        (resources/'tcolorbox.sty').write_bytes(b'trusted package')
        record_preparation(root,resources)
        return resources

    def test_export_requires_successful_preparation_for_current_templates_and_resources(self):
        from .documents import CompilerUnavailable
        with TemporaryDirectory() as directory:
            root=Path(directory);resources=self.prepared_fixture(root)
            original=(resources/PREPARATION_FILE).read_bytes()
            for change in ['missing receipt','missing tcolorbox','changed template','changed preparation runtime','new resource']:
                with self.subTest(change=change):
                    if change=='missing receipt':(resources/PREPARATION_FILE).unlink()
                    elif change=='missing tcolorbox':(resources/'tcolorbox.sty').unlink()
                    elif change=='changed template':(root/'backend/core/tex_templates/math-a4-v2.tex').write_text('updated template')
                    elif change=='changed preparation runtime':(root/'backend/core/tex_runtime.py').write_text('updated runtime')
                    else:(resources/'unexpected.sty').write_text('unexpected')
                    with self.assertRaises(CompilerUnavailable):build_contract(root,resources)
                    (resources/PREPARATION_FILE).write_bytes(original)
                    (resources/'tcolorbox.sty').write_bytes(b'trusted package')
                    (root/'backend/core/tex_templates/math-a4-v2.tex').write_text('trusted source')
                    (root/'backend/core/tex_runtime.py').write_text('trusted source')
                    (resources/'unexpected.sty').unlink(missing_ok=True)
            build_contract(root,resources)

    def test_image_resources_override_stale_persistent_volume_and_backup_uses_them(self):
        import shutil
        with TemporaryDirectory() as directory:
            root=Path(directory);old=self.prepared_fixture(root);image=root/'tex-runtime/tectonic-cache'
            shutil.copytree(old,image)
            (old/'tcolorbox.sty').unlink()
            with override_settings(BASE_DIR=root,LOCAL_DIR=root/'.local',TEX_RESOURCE_DIR=image):
                current=build_contract()
                self.assertEqual(current,build_contract(root,image))
                with toolchain_archive(open_file=True) as stream,zipfile.ZipFile(stream) as archive:
                    self.assertEqual(archive.read('.local/tectonic-cache/tcolorbox.sty'),b'trusted package')
            paths=trusted_paths(root,{'PLUSFOLIO_TEX_RESOURCE_DIR':str(image),'PLUSFOLIO_TEX_COMPILER':str(root/'tex-runtime/tools/tectonic')})
            self.assertEqual(paths['tectonic-cache'],image)
            self.assertEqual(paths['tools'],root/'tex-runtime/tools')
            self.assertEqual(trusted_paths(root,{})['tectonic-cache'],old)

    def test_oversized_resource_trees_and_receipts_fail_before_hashing_payloads(self):
        from .documents import CompilerUnavailable
        with TemporaryDirectory() as directory:
            root=Path(directory);resources=self.prepared_fixture(root)
            with patch('core.tex_resources.MAX_RESOURCE_ENTRIES',1),patch('core.tex_toolchain._file_digest') as digest:
                with self.assertRaises(CompilerUnavailable):build_contract(root,resources)
                digest.assert_not_called()
            with (resources/'oversized').open('wb') as stream:stream.truncate(256*1024*1024+1)
            with patch('core.tex_toolchain._file_digest') as digest:
                with self.assertRaises(CompilerUnavailable):build_contract(root,resources)
                digest.assert_not_called()
            (resources/'oversized').unlink()
            with (resources/PREPARATION_FILE).open('wb') as stream:stream.truncate(2*1024*1024+1)
            with self.assertRaises(CompilerUnavailable):build_contract(root,resources)

    def test_archive_size_limit_cleans_partial_output_during_compression(self):
        from .documents import CompilerUnavailable
        with TemporaryDirectory() as directory:
            root=Path(directory);resources=self.prepared_fixture(root)
            (resources/'incompressible').write_bytes(os.urandom(2*1024*1024))
            record_preparation(root,resources)
            with override_settings(BASE_DIR=root,LOCAL_DIR=root/'.local',TEX_ARCHIVE_CACHE_MAX_BYTES=256*1024):
                with self.assertRaises(CompilerUnavailable):toolchain_archive()
            self.assertEqual([path.name for path in (root/'.local/tex-toolchains').iterdir()],['.lock'])

    def test_archive_rejects_concurrent_file_changes_and_removes_partial_zip(self):
        from .documents import CompilerUnavailable
        from .tex_toolchain import _contract
        with TemporaryDirectory() as directory:
            root=Path(directory);self.prepared_fixture(root)
            def changed(files):
                contract=_contract(files)
                (root/'docs/tex-preflight.md').write_text('changed during archive creation')
                return contract
            with override_settings(BASE_DIR=root,LOCAL_DIR=root/'.local'),patch('core.tex_toolchain._contract',side_effect=changed):
                with self.assertRaises(CompilerUnavailable):toolchain_archive()
            self.assertEqual([path.name for path in (root/'.local/tex-toolchains').iterdir()],['.lock'])

    def test_disabled_archive_cache_returns_service_unavailable_without_building(self):
        from .documents import CompilerUnavailable
        from .tex_cache import ArtifactCache
        with TemporaryDirectory() as directory:
            for count,age,size in [(0,60,1024),(1,0,1024),(1,60,0)]:
                with self.subTest(count=count,age=age,size=size),patch('core.tex_cache.toolchain_cache',return_value=ArtifactCache(directory,'zip',size,count,age)),patch('core.tex_toolchain.toolchain_files') as files:
                    with self.assertRaises(CompilerUnavailable):toolchain_archive(open_file=True)
                    files.assert_not_called()

    def test_open_archive_remains_readable_after_lru_eviction(self):
        from .tex_cache import ArtifactCache
        with TemporaryDirectory() as directory:
            root=Path(directory)
            for name in SOURCE_FILES:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text("VERSION='0.17.0'\n" if name=='scripts/setup_tex.py' else 'trusted source')
            resources=root/'.local/tectonic-cache';resources.mkdir(parents=True);(resources/'resource').write_bytes(b'trusted font');record_preparation(root,resources)
            with override_settings(BASE_DIR=root,LOCAL_DIR=root/'.local'),toolchain_archive(open_file=True) as stream:
                path=Path(stream.name)
                ArtifactCache(path.parent,'zip',0,0,0).prune()
                self.assertFalse(path.exists())
                with zipfile.ZipFile(stream) as archive:self.assertIn('toolchain-manifest.json',archive.namelist())

    def test_contract_covers_only_selected_sources_and_resources_and_changes_with_them(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            for name in SOURCE_FILES:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text("VERSION='0.17.0'\n" if name=='scripts/setup_tex.py' else 'trusted source')
            cache=root/'.local/tectonic-cache';cache.mkdir(parents=True);(cache/'resource').write_bytes(b'trusted font');record_preparation(root,cache)
            (root/'.local/app.key').write_text('not exported')
            first=build_contract(root,cache)
            self.assertEqual(first['compiler']['version'],'0.17.0')
            self.assertNotIn('.local/app.key',first['files'])
            self.assertEqual(first['contract_id'],build_contract(root,cache)['contract_id'])
            with override_settings(BASE_DIR=root,LOCAL_DIR=root/'.local'):
                archive=toolchain_archive()
                with zipfile.ZipFile(archive) as data:
                    self.assertEqual(set(data.namelist()),set(first['files'])|{'toolchain-manifest.json'})
                    self.assertEqual(json.loads(data.read('toolchain-manifest.json'))['contract_id'],first['contract_id'])
            (cache/'resource').write_bytes(b'changed font');record_preparation(root,cache)
            self.assertNotEqual(first['contract_id'],build_contract(root,cache)['contract_id'])

    def test_warm_contract_reuses_digests_and_invalidates_preserved_mtime_and_replacements(self):
        from .tex_toolchain import _file_digest
        _file_digest.cache_clear()
        with TemporaryDirectory() as directory:
            root=Path(directory)
            for name in SOURCE_FILES:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text("VERSION='0.17.0'\n" if name=='scripts/setup_tex.py' else 'trusted source')
            cache=root/'.local/tectonic-cache';cache.mkdir(parents=True)
            resource=cache/'resource';resource.write_bytes(b'first');record_preparation(root,cache)
            first=build_contract(root,cache)
            digest=hashlib.file_digest
            with patch('core.tex_toolchain.hashlib.file_digest',wraps=digest) as reads:
                self.assertEqual(first,build_contract(root,cache))
            self.assertEqual(reads.call_count,0)
            info=resource.stat();resource.write_bytes(b'other')
            os.utime(resource,ns=(info.st_atime_ns,info.st_mtime_ns))
            record_preparation(root,cache);changed=build_contract(root,cache)
            self.assertNotEqual(first['contract_id'],changed['contract_id'])
            replacement=cache/'replacement';replacement.write_bytes(b'final')
            os.utime(replacement,ns=(info.st_atime_ns,info.st_mtime_ns));replacement.replace(resource);record_preparation(root,cache)
            self.assertNotEqual(changed['contract_id'],build_contract(root,cache)['contract_id'])
            extra=cache/'extra';extra.write_bytes(b'extra');record_preparation(root,cache)
            self.assertIn('.local/tectonic-cache/extra',build_contract(root,cache)['files'])
            extra.unlink();record_preparation(root,cache);self.assertNotIn('.local/tectonic-cache/extra',build_contract(root,cache)['files'])

    def test_hidden_solution_source_is_neither_validated_nor_added_to_project(self):
        from django.core.exceptions import ValidationError
        task=SimpleNamespace(pk='hidden',statement='Условие',solution='',statement_tex='',
                             solution_tex=r'\documentclass{article}',attribution={})
        sheet=SimpleNamespace(title='Листок',description='')
        project=project_for(sheet,[task],[],True)
        self.assertFalse(any(name.startswith('solutions/') for name in project))
        with self.assertRaises(ValidationError):project_for(sheet,[task],[task.pk],True)

    def test_draft_preview_uses_the_same_project_builder_without_a_database(self):
        path=settings.BASE_DIR/'scripts/preview_tex.py'
        spec=importlib.util.spec_from_file_location('preview_test',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        row={'title':'Проверка','description':'Описание задачи','statement':'Вычислите $2+2$.','solution':'Ответ: $4$.',
             'statement_tex':'','solution_tex':''}
        projects=module.draft_projects({'kind':'problem','problems':[row]})
        task=SimpleNamespace(pk='draft-001',attribution={},**row)
        sheet=SimpleNamespace(title='Проверка',description='Описание задачи',is_problem=True,template_version='math-a4-v2')
        self.assertEqual(projects['statement'],project_for(sheet,[task],[task.pk],False))
        self.assertEqual(projects['with-solutions'],project_for(sheet,[task],[task.pk],True))
        with self.assertRaises(ValueError):module.draft_projects({'kind':'problem','problems':[{**row,'solution':''}]})
        with self.assertRaises(ValueError):module.draft_projects({'kind':'problem','problems':[{**row,'id':'../outside'}]})


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ToolchainAccessTests(TestCase):
    def test_archive_response_owns_and_closes_the_opened_cache_handle(self):
        teacher=User.objects.create_user('archive@toolchain.example','unused',name='Сборка',roles=['teacher'])
        client=APIClient();client.force_authenticate(user=teacher);stream=io.BytesIO(b'archive')
        with patch('core.tex_api.toolchain_archive',return_value=stream) as archive:
            result=client.get('/api/v1/tex/toolchain/archive')
        self.assertEqual(result.status_code,200);archive.assert_called_once_with(open_file=True)
        self.assertEqual(b''.join(result.streaming_content),b'archive')
        result.close();self.assertTrue(stream.closed)

    def test_read_only_teachers_can_download_contract_but_students_and_analysts_cannot(self):
        from .authentication import create_token
        for role in ['student','analyst','teacher','admin']:
            user=User.objects.create_user(role+'@toolchain.example','unused',name='Тест сборки',roles=[role])
            client=APIClient();client.force_authenticate(user=user)
            with patch('core.tex_api.build_contract',return_value={'contract_id':'example'}) as build:
                response=client.get('/api/v1/tex/toolchain')
                self.assertEqual(response.status_code,200 if role in ['teacher','admin'] else 403)
                self.assertEqual(build.called,role in ['teacher','admin'])
            if role=='teacher':
                _,secret=create_token(user,{'read_only':True})
                token_client=APIClient();token_client.credentials(HTTP_AUTHORIZATION='Bearer '+secret)
                with patch('core.tex_api.build_contract',return_value={'contract_id':'example'}):
                    self.assertEqual(token_client.get('/api/v1/tex/toolchain').status_code,200)

import importlib.util
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


class PortableToolchainTests(SimpleTestCase):
    def test_contract_covers_only_selected_sources_and_resources_and_changes_with_them(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            for name in SOURCE_FILES:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text("VERSION='0.17.0'\n" if name=='scripts/setup_tex.py' else 'trusted source')
            cache=root/'.local/tectonic-cache';cache.mkdir(parents=True);(cache/'resource').write_bytes(b'trusted font')
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
            (cache/'resource').write_bytes(b'changed font')
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
            resource=cache/'resource';resource.write_bytes(b'first')
            first=build_contract(root,cache)
            digest=hashlib.file_digest
            with patch('core.tex_toolchain.hashlib.file_digest',wraps=digest) as reads:
                self.assertEqual(first,build_contract(root,cache))
            self.assertEqual(reads.call_count,0)
            info=resource.stat();resource.write_bytes(b'other')
            os.utime(resource,ns=(info.st_atime_ns,info.st_mtime_ns))
            changed=build_contract(root,cache)
            self.assertNotEqual(first['contract_id'],changed['contract_id'])
            replacement=cache/'replacement';replacement.write_bytes(b'final')
            os.utime(replacement,ns=(info.st_atime_ns,info.st_mtime_ns));replacement.replace(resource)
            self.assertNotEqual(changed['contract_id'],build_contract(root,cache)['contract_id'])
            extra=cache/'extra';extra.write_bytes(b'extra')
            self.assertIn('.local/tectonic-cache/extra',build_contract(root,cache)['files'])
            extra.unlink();self.assertNotIn('.local/tectonic-cache/extra',build_contract(root,cache)['files'])

    def test_draft_preview_uses_the_same_project_builder_without_a_database(self):
        path=settings.BASE_DIR/'scripts/preview_tex.py'
        spec=importlib.util.spec_from_file_location('preview_test',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        row={'title':'Проверка','description':'Описание задачи','statement':'Вычислите $2+2$.','solution':'Ответ: $4$.',
             'statement_tex':'','solution_tex':''}
        projects=module.draft_projects({'kind':'problem','problems':[row]})
        task=SimpleNamespace(pk='draft-001',attribution={},**row)
        sheet=SimpleNamespace(title='Проверка',description='Описание задачи',is_problem=True,template_version='math-a4-v1')
        self.assertEqual(projects['statement'],project_for(sheet,[task],[task.pk],False))
        self.assertEqual(projects['with-solutions'],project_for(sheet,[task],[task.pk],True))
        with self.assertRaises(ValueError):module.draft_projects({'kind':'problem','problems':[{**row,'solution':''}]})
        with self.assertRaises(ValueError):module.draft_projects({'kind':'problem','problems':[{**row,'id':'../outside'}]})


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ToolchainAccessTests(TestCase):
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

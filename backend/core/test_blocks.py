import base64,hashlib,io,json,os,sys,time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase,SimpleTestCase,override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from PIL import Image,PngImagePlugin
from . import services as s
from .content import normalize_blocks,serialize_blocks
from .documents import project_for,render_pdf,response
from .image_assets import normalize_image
from .models import User,ImageAsset,WorksheetBlock,WorksheetItem,Assignment
from .tex_cache import ArtifactCache
from .tex_project import project_files
from .worksheets import update,copy


def png(color='black'):
    output=io.BytesIO();image=Image.new('RGB',(40,20),color);image.save(output,format='PNG');return output.getvalue()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class WorksheetBlockTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo',verbosity=0)
        cls.teacher=User.objects.get(email='teacher@plusfolio.example');cls.student=User.objects.get(email='student@plusfolio.example')
        cls.mentor=User.objects.get(email='mentor@plusfolio.example');cls.circle=cls.teacher.teacher.teaching.first().circle
        cls.problem=cls.circle.issues.first().worksheet.items.first().problem
        cls.topic=str(cls.problem.topics.first().pk)
    def client_for(self,user=None):
        client=APIClient();client.force_authenticate(user=user or self.teacher);return client
    def asset(self,user=None,color='black'):
        response=self.client_for(user).post('/api/images',{'file':__import__('django.core.files.uploadedfile',fromlist=['SimpleUploadedFile']).SimpleUploadedFile('image.png',png(color),content_type='image/png')},format='multipart')
        self.assertIn(response.status_code,[200,201],response.data)
        return response.data['id']
    def sheet(self,blocks):
        with patch('core.documents.render_pdf',return_value=b'%PDF-1.4 test'):
            return s.create_material(self.teacher,'worksheet',{'title':'Блоки','topics':[self.topic],'blocks':blocks})
    def text(self,**values):return {'kind':'text','style':'definition','title':'Инвариант','text':'Величина сохраняется.','tex':'','images':[],**values}
    def task(self):return {'kind':'problem','problem_id':str(self.problem.pk)}

    def test_interleaved_blocks_number_only_tasks_and_keep_task_projection(self):
        sheet=self.sheet([self.text(),self.task(),self.text(style='remark',title='Подсказка')])
        self.assertEqual(sheet.template_version,'math-a4-v2')
        self.assertEqual(list(sheet.items.values_list('problem_id',flat=True)),[self.problem.pk])
        project=project_for(sheet,[self.problem])
        self.assertIn(r'\begin{definition}[{Инвариант}]',project['blocks/001.tex'])
        self.assertIn('start=1',project['problems.tex']);self.assertNotIn('start=2',project['problems.tex'])
        self.assertLess(project['problems.tex'].index('blocks/001'),project['problems.tex'].index('tasks/001'))
        self.assertLess(project['problems.tex'].index('tasks/001'),project['problems.tex'].index('blocks/003'))

    def test_edit_preserves_text_images_and_issued_revision(self):
        asset=self.asset();blocks=[self.text(images=[{'id':asset,'width':50,'align':'center','caption':'Рисунок'}]),self.task()]
        sheet=self.sheet(blocks);original=serialize_blocks(sheet);before=project_for(sheet,[self.problem])
        with patch('core.documents.render_pdf',return_value=b'%PDF-1.4 test'):
            changed=update(self.teacher,sheet.document_id,{'version':1,'title':'Новая редакция'})
        self.assertEqual(serialize_blocks(changed),original)
        self.assertEqual(project_for(sheet,[self.problem]),before)
        with self.assertRaises(s.Conflict):update(self.teacher,sheet.document_id,{'version':1,'title':'Устаревшая'})
        with self.assertRaises(ValidationError):update(self.teacher,sheet.document_id,{'version':2,'problems':[]})
        with self.assertRaises(ValidationError):sheet.blocks.first().save()

    def test_copy_as_owner_preserves_all_blocks(self):
        sheet=self.sheet([self.text(),self.task()])
        cloned=copy(self.teacher,sheet.pk)
        self.assertEqual(serialize_blocks(sheet),serialize_blocks(cloned))
        self.assertNotEqual(sheet.document_id,cloned.document_id)

    def test_text_only_sheet_can_be_issued_without_solve_columns(self):
        sheet=self.sheet([self.text()]);s.issue_worksheet(self.teacher,self.circle,sheet.pk,timezone.localdate())
        self.assertEqual(sheet.items.count(),0)
        issue=sheet.issues.get();self.assertGreater(Assignment.objects.filter(issue=issue).count(),0)
        response=self.client_for(self.student).get(f'/api/circles/{self.circle.pk}/journal?issues={issue.pk}')
        self.assertEqual(response.status_code,200);self.assertEqual(response.data['blocks'][0]['problems'],[])
        self.assertEqual(response.data['solves'],[])
        self.assertEqual(self.client_for().get(f'/api/circles/{self.circle.pk}/journal/export?issues={issue.pk}').status_code,200)

    def test_invalid_duplicate_empty_and_unavailable_blocks_are_rejected(self):
        for blocks in [[],[self.task(),self.task()],[{'kind':'unknown'}],[self.text(text='',title='')]]:
            with self.subTest(blocks=blocks),self.assertRaises(ValidationError):normalize_blocks(blocks)
        asset=self.asset(self.mentor)
        with self.assertRaises(ValidationError):self.sheet([self.text(images=[{'id':asset}])])

    def test_images_are_deduplicated_and_private_until_their_content_is_available(self):
        asset=self.asset();self.assertEqual(self.asset(),asset)
        self.assertEqual(ImageAsset.objects.filter(pk=asset).count(),1)
        self.assertEqual(self.client_for(self.student).get('/api/images/'+asset).status_code,404)
        self.assertEqual(self.client_for(self.student).post('/api/images',{'data':base64.b64encode(png()).decode()},format='json').status_code,403)
        self.assertEqual(self.client_for(self.mentor).get('/api/images/'+asset).status_code,404)
        sheet=self.sheet([self.text(images=[{'id':asset}])]);s.issue_worksheet(self.teacher,self.circle,sheet.pk,timezone.localdate())
        self.assertEqual(self.client_for(self.student).get('/api/images/'+asset).status_code,200)

    def test_solution_images_are_filtered_from_json_files_and_direct_downloads(self):
        statement=self.asset(color='red');solution=self.asset(color='blue')
        problem=s.create_material(self.teacher,'problem',{'topics':[self.topic],'statement':'Условие','solution':'Секретное решение',
            'statement_images':[{'id':statement}],'solution_images':[{'id':solution}]})
        with patch('core.documents.render_pdf',return_value=b'%PDF-1.4 test'):
            sheet=s.create_material(self.teacher,'worksheet',{'title':'Картинки','topics':[self.topic],'problems':[str(problem.pk)]})
        s.issue_worksheet(self.teacher,self.circle,sheet.pk,timezone.localdate())
        material=self.client_for(self.student).get('/api/my-problems/'+str(problem.pk))
        self.assertEqual(material.status_code,200);self.assertNotIn('solution_images',material.data)
        closed=project_for(sheet,[problem],[],True)
        self.assertIn('assets/'+statement+'.png',closed);self.assertNotIn('assets/'+solution+'.png',closed)
        self.assertEqual(self.client_for(self.student).get('/api/images/'+solution).status_code,404)
        self.assertEqual(self.client_for(self.student).get('/api/images/'+statement).status_code,200)
        discussed=s.mark(self.teacher,self.circle,problem.pk,{'value':True,'version':0},discussion=True)
        s.mark(self.teacher,self.circle,problem.pk,{'value':True,'version':discussed['version']},solution_visibility=True)
        self.assertEqual(self.client_for(self.student).get('/api/images/'+solution).status_code,200)
        self.assertIn('assets/'+solution+'.png',project_for(sheet,[problem],[problem.pk],True))

    def test_image_and_revision_links_are_immutable(self):
        asset=self.asset();row=ImageAsset.objects.get(pk=asset)
        with self.assertRaises(ValidationError):row.save()
        sheet=self.sheet([self.text(images=[{'id':asset}])])
        with self.assertRaises(ValidationError):sheet.blocks.first().assets.clear()

    def test_preview_has_no_database_or_disk_cache_side_effects(self):
        from .models import Worksheet
        before=Worksheet.objects.count()
        with patch('core.documents.render_pdf',return_value=b'%PDF-1.4 test') as render:
            result=self.client_for().post('/api/worksheets/preview',{'title':'Черновик','blocks':[self.text()]},format='json')
        self.assertEqual(result.status_code,200);self.assertEqual(Worksheet.objects.count(),before)
        self.assertEqual(render.call_args.kwargs,{'cache':False})

    def test_read_only_tokens_can_preview_but_cannot_upload_images(self):
        from .authentication import create_token
        _,secret=create_token(self.teacher,{'read_only':True})
        client=APIClient();client.credentials(HTTP_AUTHORIZATION='Bearer '+secret)
        with patch('core.documents.render_pdf',return_value=b'%PDF-1.4 test'):
            self.assertEqual(client.post('/api/v1/worksheets/preview',{'blocks':[self.text()]},format='json').status_code,200)
        self.assertEqual(client.post('/api/v1/images',{'data':base64.b64encode(png()).decode()},format='json').status_code,403)


class ImageValidationTests(SimpleTestCase):
    def test_decodes_png_jpeg_and_strips_metadata(self):
        source=io.BytesIO();meta=PngImagePlugin.PngInfo();meta.add_text('private','should disappear')
        Image.new('RGB',(40,20),'red').save(source,format='PNG',pnginfo=meta)
        data,width,height=normalize_image(source.getvalue())
        self.assertEqual((width,height),(40,20));self.assertNotIn(b'should disappear',data)
        source=io.BytesIO();Image.new('RGB',(10,10),'blue').save(source,format='JPEG')
        self.assertTrue(normalize_image(source.getvalue())[0].startswith(b'\x89PNG'))

    def test_invalid_oversized_and_vector_inputs_are_rejected(self):
        for source in [b'<svg/>',b'not an image',b'x'*(2*1024*1024+1)]:
            with self.subTest(size=len(source)),self.assertRaises(ValidationError):normalize_image(source)
        source=io.BytesIO();Image.new('1',(8193,2)).save(source,format='PNG')
        with self.assertRaises(ValidationError):normalize_image(source.getvalue())

    def test_normalization_applies_orientation_and_removes_embedded_profiles(self):
        source=io.BytesIO();exif=Image.Exif();exif[274]=6;exif[315]='private-author'
        Image.new('RGB',(40,20),'red').save(source,format='JPEG',exif=exif,icc_profile=b'private-color-profile')
        data,width,height=normalize_image(source.getvalue())
        self.assertEqual((width,height),(20,40))
        self.assertNotIn(b'private-color-profile',data);self.assertNotIn(b'private-author',data)
        with Image.open(io.BytesIO(data)) as normalized:
            self.assertFalse(normalized.getexif());self.assertNotIn('icc_profile',normalized.info)

    def test_normalization_keeps_transparency_when_metadata_is_removed(self):
        for mode,color,options,alpha in [('RGBA',(255,0,0,100),{},100),('RGB',(255,0,0),{'transparency':(255,0,0)},0)]:
            with self.subTest(mode=mode):
                source=io.BytesIO();Image.new(mode,(2,2),color).save(source,format='PNG',**options)
                payload,_,_=normalize_image(source.getvalue())
                with Image.open(io.BytesIO(payload)) as normalized:
                    self.assertEqual(normalized.convert('RGBA').getpixel((0,0))[3],alpha)


class TexCacheTests(SimpleTestCase):
    def test_abandoned_jobs_are_removed_but_active_leases_are_respected(self):
        from .tex_runtime import job_directory,prune_jobs
        with TemporaryDirectory() as directory:
            root=Path(directory)
            with job_directory(root) as active:
                os.utime(active,(0,0));prune_jobs(root);self.assertTrue(active.exists())
                orphan=root/('job-'+'f'*32);orphan.mkdir();(orphan/'main.log').write_text('old')
                os.utime(orphan,(0,0));self.assertEqual(prune_jobs(root)['removed'],1);self.assertFalse(orphan.exists())
            self.assertEqual(list(root.iterdir()),[])

    def test_lru_limits_bytes_count_age_and_orphan_temp_files(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);cache=ArtifactCache(root,'pdf',100,2,86400)
            for index in range(3):cache.put(str(index)*64,b'%PDF-'+bytes([index])*20)
            self.assertLessEqual(cache.prune()['files'],2);self.assertLessEqual(cache.prune()['bytes'],100)
            self.assertIsNone(cache.get('0'*64))
            stale=root/('f'*64+'.a.tmp');stale.write_bytes(b'old');os.utime(stale,(0,0))
            font=root/'trusted-font';font.write_bytes(b'keep')
            pdf=next(root.glob('*.pdf'));os.utime(pdf,(0,0))
            cache.prune();self.assertFalse(stale.exists());self.assertFalse(pdf.exists());self.assertTrue(font.exists())

    def test_symlinks_and_external_attachments_are_never_followed_or_removed(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);private=root/'attachment.png';private.write_bytes(b'preserve')
            cache=ArtifactCache(root/'pdf','pdf',1,1,1);cache.directory.mkdir()
            (cache.directory/('f'*64+'.pdf')).symlink_to(private)
            cache.prune();self.assertEqual(private.read_bytes(),b'preserve');self.assertIsNone(cache.get('f'*64))

    def test_diagnostics_survive_cache_hits_and_uncached_previews_do_not_grow_disk(self):
        project=project_for(SimpleNamespace(title='Листок',description=''),[])
        with TemporaryDirectory() as directory,override_settings(LOCAL_DIR=Path(directory),TEX_SOCKET='fake'):
            def compile(socket,project,diagnostics):diagnostics.update(warnings=['test warning']);return b'%PDF-1.4 test'
            with patch('core.tex_remote.compile_project',side_effect=compile) as compiler:
                render_pdf(project);diagnostics={};render_pdf(project,diagnostics)
                self.assertEqual(compiler.call_count,1);self.assertEqual(diagnostics['warnings'],['test warning'])
                before=set(Path(directory).rglob('*'))
                for index in range(20):render_pdf({**project,'variables.tex':str(index)},cache=False)
                self.assertEqual(before,set(Path(directory).rglob('*')))

    def test_job_is_killed_when_temporary_disk_budget_is_exceeded(self):
        from .tex_runtime import run_compiler
        with TemporaryDirectory() as directory:
            command=[sys.executable,'-c',"import pathlib,time;pathlib.Path('spill').write_bytes(b'x'*4096);time.sleep(10)"]
            with self.assertRaisesRegex(ValueError,'Временные файлы'):
                run_compiler(command,directory,{'PATH':'/usr/bin:/bin'},max_bytes=1024)

    def test_transport_rejects_paths_and_oversized_image_payloads(self):
        project=project_for(SimpleNamespace(title='Листок',description=''),[])
        for name,value in [('../outside.tex','x'),('assets/../../secret',{'base64':'x'}),('blocks/bad.tex',{'base64':'x'})]:
            with self.subTest(name=name),self.assertRaises(ValueError):project_files({**project,name:value})

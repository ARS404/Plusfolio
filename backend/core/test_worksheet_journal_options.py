import csv,io,importlib.util
from unittest.mock import patch
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.http import QueryDict
from django.test import TestCase,override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from . import services as s
from .analytics import report
from .content import serialize_blocks
from .documents import project_for
from .models import Circle,User,Problem,Worksheet
from .worksheets import copy,update


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class WorksheetJournalOptionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo',verbosity=0)
        cls.teacher=User.objects.get(email='teacher@plusfolio.example');cls.student=User.objects.get(email='student@plusfolio.example')
        cls.circle=Circle.objects.get(name='Математическая мастерская')
        cls.topic=str(Problem.objects.first().topics.first().pk)
        cls.problems=[s.create_material(cls.teacher,'problem',{'title':f'Упражнение {i}','statement':f'Условие {i}.','solution':f'Ответ {i}.','topics':[cls.topic]}) for i in range(4)]
    def client_for(self,user=None):
        client=APIClient();client.force_authenticate(user=user or self.teacher);return client
    def blocks(self,flags=(False,True,False,True)):
        return [{'kind':'problem','problem_id':str(problem.pk),'include_in_journal':flag} for problem,flag in zip(self.problems,flags)]
    def sheet(self,**values):
        return s.create_material(self.teacher,'worksheet',{'title':'Настройки задач','topics':[self.topic],'numbering_start':0,'blocks':self.blocks(),**values})
    def issue(self,sheet):
        s.issue_worksheet(self.teacher,self.circle,sheet.pk,timezone.localdate());return sheet.issues.get()

    def test_options_persist_and_all_tasks_remain_in_full_material(self):
        sheet=self.sheet();data=self.client_for().get('/api/worksheet-documents/'+str(sheet.document_id)).data
        self.assertEqual(data['numbering_start'],0);self.assertEqual(data['problem_count'],4)
        self.assertEqual([b['include_in_journal'] for b in data['blocks']],[False,True,False,True])
        self.assertEqual(list(sheet.items.values_list('include_in_journal',flat=True)),[False,True,False,True])
        self.assertEqual([p['id'] for p in data['problems']],[str(p.pk) for p in self.problems])
        default=s.create_material(self.teacher,'worksheet',{'title':'Прежний формат','topics':[self.topic],'problems':[str(self.problems[0].pk)]})
        self.assertEqual(default.numbering_start,1);self.assertTrue(default.items.get().include_in_journal)
        self.assertTrue(serialize_blocks(default)[0]['include_in_journal'])

    def test_journal_exports_and_solution_numbers_match_full_pdf(self):
        sheet=self.sheet();issue=self.issue(sheet)
        response=self.client_for().get(f'/api/circles/{self.circle.pk}/journal',{'issues':issue.pk})
        self.assertEqual(response.status_code,200)
        tasks=response.data['blocks'][0]['problems']
        self.assertEqual([(p['id'],p['worksheet_position']) for p in tasks],[(str(self.problems[1].pk),1),(str(self.problems[3].pk),3)])
        project=project_for(sheet,self.problems,[p.pk for p in self.problems],True)
        for number in range(4):
            self.assertIn(f'start={number}',project['problems.tex'])
            self.assertIn(r'\textbf{'+str(number)+'.}',project['solutions.tex'])
        self.assertEqual(len([name for name in project if name.startswith('tasks/')]),4)
        exported=self.client_for().get(f'/api/circles/{self.circle.pk}/journal/export',{'issues':issue.pk,'file_format':'tsv'})
        rows=list(csv.reader(io.StringIO(exported.content.decode('utf-8-sig')),delimiter='\t'))
        self.assertEqual(rows[1][1:],[f'№1 · {self.problems[1].title}',f'№3 · {self.problems[3].title}','Решено'])
        for index,status in [(0,400),(1,200)]:
            result=self.client_for().post(f'/api/circles/{self.circle.pk}/problems/{self.problems[index].pk}/solve',{'student_id':self.student.student.pk,'value':True,'version':0},format='json')
            self.assertEqual(result.status_code,status)

    def test_zero_can_be_included_and_all_tasks_can_be_excluded(self):
        for flags,expected in [((True,False,False,False),[0]),((False,False,False,False),[])]:
            with self.subTest(flags=flags):
                sheet=self.sheet(blocks=self.blocks(flags));issue=self.issue(sheet)
                data=self.client_for().get(f'/api/circles/{self.circle.pk}/journal',{'issues':issue.pk}).data
                self.assertEqual([p['worksheet_position'] for p in data['blocks'][0]['problems']],expected)
                if expected:
                    exported=self.client_for().get(f'/api/circles/{self.circle.pk}/journal/export',{'issues':issue.pk,'file_format':'tsv'})
                    self.assertIn('№0 ·',exported.content.decode('utf-8-sig'))
                self.assertEqual(sheet.items.count(),4)

    def test_copy_edit_and_issued_versions_preserve_their_settings(self):
        sheet=self.sheet();issue=self.issue(sheet);original=serialize_blocks(sheet)
        clone=copy(self.teacher,sheet.pk)
        self.assertEqual(clone.numbering_start,0);self.assertEqual(serialize_blocks(clone),original)
        revised=update(self.teacher,sheet.document_id,{'version':1,'title':'Исправлен заголовок'})
        self.assertEqual(revised.numbering_start,0);self.assertEqual(serialize_blocks(revised),original)
        changed=update(self.teacher,sheet.document_id,{'version':2,'numbering_start':1,'blocks':self.blocks((True,True,True,True))})
        self.assertEqual(changed.numbering_start,1);self.assertEqual(issue.worksheet_id,sheet.pk)
        sheet.refresh_from_db();self.assertEqual(sheet.numbering_start,0);self.assertEqual(serialize_blocks(sheet),original)
        with self.assertRaises(ValidationError):update(self.teacher,clone.document_id,{'version':1,'problems':[str(p.pk) for p in self.problems]})

    def test_progress_excludes_untracked_tasks(self):
        params=QueryDict('circle='+str(self.circle.pk));before=report(self.student,params)['assigned_pairs']
        assigned=self.client_for(self.student).get('/api/account').data['student']['assigned']
        self.issue(self.sheet())
        self.assertEqual(report(self.student,params)['assigned_pairs']-before,2)
        self.assertEqual(self.client_for(self.student).get('/api/account').data['student']['assigned']-assigned,2)

    def test_invalid_numbering_and_flags_are_rejected(self):
        before=Worksheet.objects.count()
        for value in [True,False,None,'0',-1,2]:
            with self.subTest(start=value),self.assertRaises(ValidationError):self.sheet(numbering_start=value)
        for value in [0,1,None,'false']:
            blocks=self.blocks();blocks[0]['include_in_journal']=value
            with self.subTest(flag=value),self.assertRaises(ValidationError):self.sheet(blocks=blocks)
        self.assertEqual(Worksheet.objects.count(),before)

    def test_draft_preview_and_portable_builder_use_same_numbers(self):
        with patch('core.documents.render_pdf',return_value=b'%PDF-1.4 test') as render:
            result=self.client_for().post('/api/worksheets/preview',{'title':'Черновик','numbering_start':0,'blocks':self.blocks()},format='json')
        self.assertEqual(result.status_code,200);self.assertEqual(render.call_args.kwargs,{'cache':False})
        self.assertIn('start=0',render.call_args.args[0]['problems.tex'])
        spec=importlib.util.spec_from_file_location('preview_options',settings.BASE_DIR/'scripts/preview_tex.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        projects=module.draft_projects({'kind':'worksheet','worksheet':{'title':'Черновик','numbering_start':0},'blocks':self.blocks(),
            'problems':[{'id':str(p.pk),'title':p.title,'statement':p.statement,'solution':p.solution} for p in self.problems]})
        self.assertIn('start=0',projects['statement']['problems.tex']);self.assertIn(r'\textbf{0.}',projects['with-solutions']['solutions.tex'])

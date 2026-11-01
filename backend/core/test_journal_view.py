import csv,io
from collections import Counter
from datetime import timedelta
from django.core.management import call_command
from django.test import TestCase,override_settings
from django.utils import timezone
from openpyxl import load_workbook
from rest_framework.test import APIClient
from .models import AuditEvent,Circle,Discussion,User,WorksheetIssue


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class JournalViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo',verbosity=0)
        cls.teacher=User.objects.get(email='teacher@plusfolio.example')
        cls.student=User.objects.get(email='student@plusfolio.example')
        cls.circle=Circle.objects.get(name='Математическая мастерская')
        cls.other=Circle.objects.get(name='Олимпиадный старт')
        Discussion.objects.filter(circle=cls.circle).update(discussed=False,solution_visible=False)
    def client_for(self,user=None):
        client=APIClient();client.force_authenticate(user=user or self.teacher);return client
    def journal(self,params=None,user=None):
        result=self.client_for(user).get(f'/api/circles/{self.circle.pk}/journal',params or {})
        self.assertEqual(result.status_code,200);return result.data
    def discuss(self,problem_id,circle=None):
        Discussion.objects.update_or_create(circle=circle or self.circle,problem_id=problem_id,
            defaults={'discussed':True,'changed_by':self.teacher})

    def test_both_orders_sort_by_issue_date_then_id_and_keep_selection(self):
        issues=list(self.circle.issues.order_by('pk'))
        WorksheetIssue.objects.filter(pk=issues[0].pk).update(issued_on=timezone.localdate())
        WorksheetIssue.objects.filter(pk=issues[1].pk).update(issued_on=timezone.localdate()-timedelta(days=20))
        params={'issues':','.join(str(issue.pk) for issue in issues)}
        newest=self.journal(params)['blocks'];oldest=self.journal({**params,'order':'oldest'})['blocks']
        self.assertEqual([b['issue_id'] for b in oldest],[b['issue_id'] for b in reversed(newest)])
        self.assertEqual(oldest[0]['issue_id'],issues[1].pk)
        WorksheetIssue.objects.filter(pk__in=[issue.pk for issue in issues]).update(issued_on=timezone.localdate())
        self.assertEqual([b['issue_id'] for b in self.journal({**params,'order':'oldest'})['blocks']],sorted(issue.pk for issue in issues))

    def test_hide_is_local_to_circle_and_preserves_numbers_without_changing_results(self):
        original=self.journal()['blocks'];counts=Counter(p['id'] for b in original for p in b['problems'])
        hidden=next(pid for pid,count in counts.items() if count>1)
        other=next(pid for pid in counts if pid!=hidden)
        self.discuss(hidden);self.discuss(other,self.other)
        before=AuditEvent.objects.count()
        for user in [self.teacher,self.student]:
            result=self.journal({'hide_discussed':'1'},user)
            self.assertEqual(result['can_write'],user==self.teacher)
            by_id={b['issue_id']:b for b in result['blocks']}
            for block in original:
                expected=[(p['id'],index) for index,p in enumerate(block['problems'],1) if p['id']!=hidden]
                actual=[(p['id'],p['worksheet_position']) for p in by_id.get(block['issue_id'],{'problems':[]})['problems']]
                self.assertEqual(actual,expected)
            self.assertTrue(any(p['id']==other for b in result['blocks'] for p in b['problems']))
            self.assertFalse(any(s['problem_id']==hidden for key in ['solves','discussions'] for s in result[key]))
            if user==self.student:self.assertTrue(all('solution' not in p for b in result['blocks'] for p in b['problems']))
        self.assertEqual(AuditEvent.objects.count(),before)
        self.assertEqual(sum(len(b['problems']) for b in self.journal()['blocks']),sum(len(b['problems']) for b in original))

    def test_all_hidden_tasks_keep_legacy_single_issue_response_valid(self):
        block=self.journal()['blocks'][0]
        for problem in block['problems']:self.discuss(problem['id'])
        params={'issues':str(block['issue_id']),'hide_discussed':'1'}
        self.assertEqual(self.journal(params)['blocks'],[])
        response=self.client_for().get(f'/api/circles/{self.circle.pk}/journal/{block["issue_id"]}',params)
        self.assertEqual(response.status_code,200);self.assertEqual(response.data['problems'],[])
        self.assertEqual(response.data['worksheet']['id'],block['worksheet']['id'])

    def test_xlsx_and_tsv_match_filtered_columns_original_numbers_and_order(self):
        original=self.journal();self.discuss(original['blocks'][0]['problems'][0]['id'])
        params={'issues':','.join(str(b['issue_id']) for b in original['blocks']),
                'hide_discussed':'1','order':'oldest','q':f'S-{self.student.student.pk}'}
        visible=self.journal(params);expected=[]
        for block in visible['blocks']:
            expected.extend(f'№{p["worksheet_position"]} · {p["title"]}' for p in block['problems'])
            expected.append('Решено')
        response=self.client_for().get(f'/api/circles/{self.circle.pk}/journal/export',params)
        self.assertEqual(response.status_code,200)
        sheet=load_workbook(io.BytesIO(response.content)).active
        self.assertEqual([cell.value for cell in sheet[6]][1:],expected)
        self.assertEqual(sheet.max_row,8)
        block_titles=[cell.value for cell in sheet[5]][1:]
        block_titles=[title for title in block_titles if title is not None]
        self.assertEqual(len(block_titles),len(visible['blocks']))
        self.assertTrue(all(title.startswith(block['worksheet']['title']+' · ') for title,block in zip(block_titles,visible['blocks'])))
        response=self.client_for().get(f'/api/circles/{self.circle.pk}/journal/export',{**params,'file_format':'tsv'})
        self.assertEqual(response.status_code,200)
        rows=list(csv.reader(io.StringIO(response.content.decode('utf-8-sig')),delimiter='\t'))
        self.assertEqual(rows[1][1:],expected);self.assertEqual(len(rows),4)

    def test_invalid_options_are_rejected_for_both_screen_and_export(self):
        for params in [{'hide_discussed':'true'},{'hide_discussed':'2'},{'order':'random'}]:
            for suffix in ['','/export']:
                with self.subTest(params=params,suffix=suffix):
                    response=self.client_for().get(f'/api/circles/{self.circle.pk}/journal'+suffix,params)
                    self.assertEqual(response.status_code,400)

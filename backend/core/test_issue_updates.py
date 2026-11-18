import csv
import io
from datetime import timedelta
from openpyxl import load_workbook
from django.core.management import call_command
from django.test import SimpleTestCase,TestCase,override_settings
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient
from . import services as s
from .analytics import report
from .models import Assignment,AuditEvent,Circle,Discussion,Enrollment,Problem,Solve,Tag,User,WorksheetIssue
from .worksheets import update


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class IssueUpdateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo',verbosity=0)
        cls.teacher=User.objects.get(email='teacher@plusfolio.example')
        cls.student=User.objects.get(email='student@plusfolio.example')
        cls.circle=Circle.objects.get(name='Математическая мастерская')
        topic=str(Problem.objects.first().topics.first().pk)
        cls.problem_tag=Tag.objects.create(kind='problem',name='Часть листка')
        cls.tasks=[s.create_material(cls.teacher,'problem',{'title':f'Обновление {i}','statement':f'Условие {i}','solution':'Ответ','topics':[topic],'tags':[cls.problem_tag.pk] if i==0 else []}) for i in range(4)]
        cls.tag=Tag.objects.create(kind='worksheet',name='Тест обновления')
        cls.sheet=s.create_material(cls.teacher,'worksheet',{'title':'Выданный листок','topics':[topic],'tags':[cls.tag.pk],'problems':[str(p.pk) for p in cls.tasks[:3]]})
        cls.issue=s.issue_worksheet(cls.teacher,cls.circle,cls.sheet.pk,timezone.localdate()-timedelta(days=1),visible_to_students=True)
        Solve.objects.create(student=cls.student.student,problem=cls.tasks[0],solved=True,changed_by=cls.teacher,source_circle=cls.circle)
        Discussion.objects.create(circle=cls.circle,problem=cls.tasks[1],discussed=True,solution_visible=True,changed_by=cls.teacher)

    def client_for(self,user=None):
        client=APIClient();client.force_authenticate(user=user or self.teacher);return client

    def path(self,suffix=''):
        return f'/api/v1/circles/{self.circle.pk}/issues/{self.issue.pk}'+suffix

    def revision(self):
        return update(self.teacher,self.sheet.document_id,{'version':1,'numbering_start':0,'blocks':[{'kind':'problem','problem_id':str(self.tasks[i].pk)} for i in [0,2,3]]})

    def params(self,**extra):
        return {'circle':str(self.circle.pk),'worksheet_tag':str(self.tag.pk),**extra}

    def test_worksheet_circle_links_follow_issue_replacement_and_permissions(self):
        revised=self.revision()
        other=Circle.objects.get(name='Олимпиадный старт')
        s.issue_worksheet(self.teacher,other,revised.pk,timezone.localdate())
        teacher=self.client_for();student=self.client_for(self.student)
        doc_path=f'/api/worksheet-documents/{self.sheet.document_id}'
        first_path=f'/api/worksheets/{self.sheet.pk}/circles'
        revised_path=f'/api/worksheets/{revised.pk}/circles'

        default=teacher.get(doc_path)
        self.assertEqual(default.data['id'],str(revised.pk))
        self.assertEqual(default.data['available_revisions'],[2,1])
        old=teacher.get(doc_path,{'revision':1})
        self.assertEqual(old.data['id'],str(self.sheet.pk))
        self.assertEqual(student.get(doc_path,{'revision':1}).status_code,404)
        self.assertEqual([row['id'] for row in teacher.get(first_path).data],[str(self.circle.pk)])
        self.assertEqual(teacher.get(revised_path).data[0]['id'],str(other.pk))
        self.assertFalse(teacher.get(revised_path).data[0]['visible_to_students'])
        self.assertEqual(student.get(revised_path).data,[])

        changed=teacher.patch(self.path(),{'version':self.issue.version,'worksheet_id':str(revised.pk)},format='json')
        self.assertEqual(changed.status_code,200,changed.data)
        self.assertEqual(teacher.get(first_path).data,[])
        self.assertEqual({row['id'] for row in teacher.get(revised_path).data},{str(other.pk),str(self.circle.pk)})
        self.assertEqual([row['id'] for row in student.get(revised_path).data],[str(self.circle.pk)])

    def test_staged_issue_stays_private_until_published_and_assigns_current_students(self):
        task=self.tasks[3]
        sheet=s.create_material(self.teacher,'worksheet',{'title':'Будущий листок','topics':[str(self.sheet.topics.first().pk)],
            'problems':[str(task.pk)]})
        base=f'/api/circles/{self.circle.pk}'
        teacher=self.client_for();student=self.client_for(self.student)
        created=teacher.post(base+'/issues',{'worksheet_id':str(sheet.pk),'issued_on':timezone.localdate().isoformat()},format='json')
        self.assertEqual(created.status_code,200,created.data)
        row=next(issue for issue in created.data if issue['worksheet_id']==str(sheet.pk))
        issue=WorksheetIssue.objects.get(pk=row['id'])
        path=f'{base}/issues/{issue.pk}'
        pdf=path+'/pdf'
        params={'circle':str(self.circle.pk)}
        self.assertFalse(row['visible_to_students']);self.assertFalse(issue.assignments.exists())
        self.assertFalse(teacher.get(path).data['visible_to_students'])
        self.assertFalse(teacher.get(f'{base}/journal/{issue.pk}').data['visible_to_students'])
        self.assertNotIn(issue.pk,{item['id'] for item in student.get(base+'/issues').data})
        self.assertNotIn(issue.pk,{item['issue_id'] for item in student.get(base+'/journal').data['blocks']})
        self.assertNotIn(issue.pk,{item['id'] for item in student.get('/api/my-materials/worksheet').data})
        self.assertNotIn(str(task.pk),{item['id'] for item in student.get('/api/my-materials/problem').data})
        assigned_before=student.get('/api/account').data['student']['assigned']
        self.assertNotIn(str(task.pk),{item['problem_id'] for item in student.get('/api/analytics',params).data['rows']})
        self.assertFalse(student.get('/api/catalogue-search',{'kind':'worksheet','scope':'issued','circle':str(self.circle.pk),
            'q':f'W-{sheet.document.number_id}'}).data['results'])
        for hidden in (path,pdf,f'/api/my-issues/{issue.pk}',f'/api/my-issues/{issue.pk}/pdf',
                       f'{base}/journal/{issue.pk}',f'/api/my-problems/{task.pk}',f'/api/materials/problem/{task.pk}',
                       f'/api/materials/worksheet/{sheet.pk}',f'/api/materials/worksheet/{sheet.pk}/pdf'):
            with self.subTest(hidden=hidden):
                self.assertEqual(student.get(hidden,params).status_code,404)
        self.assertEqual(student.get(base+'/journal/export',{'issues':issue.pk}).status_code,404)
        self.assertEqual(teacher.post(f'{base}/problems/{task.pk}/solve',{'student_id':self.student.student.pk,'value':True,
            'version':0},format='json').status_code,400)
        analyst=self.client_for(User.objects.get(email='analyst@plusfolio.example'))
        self.assertFalse(analyst.get(path).data['visible_to_students'])
        self.assertEqual(analyst.post(path+'/publish',{'version':1},format='json').status_code,403)
        self.assertEqual(teacher.post(path+'/publish',{'version':0},format='json').status_code,409)

        former=self.circle.enrollments.exclude(student=self.student.student).first().student
        s.unenroll(self.teacher,self.circle,former.user.email)
        newcomer=User.objects.create_user('new-issue-pupil@example.test',name='Новый школьник',roles=['student'])
        s.enroll(self.teacher,self.circle,newcomer.email)
        self.assertFalse(issue.assignments.exists())
        self.circle.archived=True;self.circle.save(update_fields=['archived'])
        self.assertEqual(teacher.post(path+'/publish',{'version':1},format='json').status_code,403)
        self.circle.archived=False;self.circle.save(update_fields=['archived'])

        opened=teacher.post(path+'/publish',{'version':1},format='json')
        self.assertEqual(opened.status_code,200,opened.data)
        self.assertTrue(opened.data['visible_to_students']);self.assertEqual(opened.data['version'],2)
        self.assertEqual(set(issue.assignments.values_list('student_id',flat=True)),
                         set(self.circle.enrollments.filter(left_at=None).values_list('student_id',flat=True)))
        self.assertFalse(issue.assignments.filter(student=former).exists())
        self.assertEqual(student.get(f'/api/my-issues/{issue.pk}').status_code,200)
        self.assertEqual(student.get(f'{base}/journal/{issue.pk}').status_code,200)
        self.assertEqual(student.get('/api/account').data['student']['assigned'],assigned_before+1)
        self.assertIn(str(task.pk),{item['problem_id'] for item in student.get('/api/analytics',params).data['rows']})
        self.assertEqual(teacher.post(path+'/publish',{'version':1},format='json').data['version'],2)
        self.assertEqual(AuditEvent.objects.filter(circle=self.circle,kind='worksheet.issue.publish').count(),1)

    def test_staged_export_omits_shared_global_marks(self):
        sheet=s.create_material(self.teacher,'worksheet',{'title':'Скрытая копия','topics':[str(self.sheet.topics.first().pk)],
            'problems':[str(self.tasks[0].pk)]})
        issue=s.issue_worksheet(self.teacher,self.circle,sheet.pk,timezone.localdate())
        path=f'/api/circles/{self.circle.pk}/journal/export'
        for file_format in ['tsv','xlsx']:
            response=self.client_for().get(path,{'issues':issue.pk,'file_format':file_format})
            self.assertEqual(response.status_code,200)
            if file_format=='tsv':
                rows=list(csv.reader(io.StringIO(response.content.decode('utf-8-sig')),delimiter='\t'))
                self.assertIn('Скрыт от школьников',rows[0][1])
                self.assertTrue(all(row[1:]==['—','—'] for row in rows[3:]))
            else:
                workbook=load_workbook(io.BytesIO(response.content),read_only=True)
                try:
                    self.assertIn('Скрыт от школьников',workbook.active.cell(5,2).value)
                    self.assertTrue(all(row[1:]==('—','—') for row in workbook.active.iter_rows(min_row=8,values_only=True)))
                finally:
                    workbook.close()

    def test_update_retargets_only_this_issue_preserving_assignments_and_global_marks(self):
        other=Circle.objects.exclude(pk=self.circle.pk).filter(teaching__teacher__user=self.teacher).first()
        second=s.issue_worksheet(self.teacher,other,self.sheet.pk,timezone.localdate(),visible_to_students=True)
        revised=self.revision();before=list(self.issue.assignments.order_by('pk').values_list('pk','student_id','assigned_at'))
        options=self.client_for().get(self.path('/editing'))
        self.assertEqual(options.status_code,200)
        version=next(row for row in options.data['versions'] if row['id']==str(revised.pk))
        self.assertEqual((version['added'],version['removed']),(1,1))
        changed=self.client_for().patch(self.path(),{'version':1,'worksheet_id':str(revised.pk)},format='json')
        self.assertEqual(changed.status_code,200,changed.data)
        self.issue.refresh_from_db();self.assertEqual(self.issue.version,2);self.assertEqual(self.issue.worksheet_id,revised.pk)
        self.assertEqual(list(self.issue.assignments.order_by('pk').values_list('pk','student_id','assigned_at')),before)
        self.assertEqual(self.issue.number,changed.data['number'])
        self.assertTrue(Solve.objects.get(student=self.student.student,problem=self.tasks[0]).solved)
        self.assertTrue(Discussion.objects.get(circle=self.circle,problem=self.tasks[1]).solution_visible)
        journal=self.client_for().get(f'/api/circles/{self.circle.pk}/journal',{'issues':self.issue.pk}).data
        self.assertEqual([(p['id'],p['worksheet_position']) for p in journal['blocks'][0]['problems']],[(str(self.tasks[i].pk),n) for n,i in enumerate([0,2,3])])
        self.assertTrue(AuditEvent.objects.filter(kind='worksheet.issue.update',circle=self.circle).exists())
        stale=self.client_for().patch(self.path(),{'version':1,'issued_on':timezone.localdate().isoformat()},format='json')
        self.assertEqual(stale.status_code,409)
        self.assertEqual(self.client_for(self.student).get(f'/api/my-issues/{self.issue.pk}').data['worksheet_id'],str(revised.pk))
        second.refresh_from_db();self.assertEqual(second.worksheet_id,self.sheet.pk)
        self.assertEqual(WorksheetIssue.objects.filter(worksheet=self.sheet).count(),1)
        self.assertEqual(self.sheet.items.count(),3)

    def test_date_edit_permissions_and_unavailable_or_different_documents(self):
        for user in [self.student,User.objects.get(email='analyst@plusfolio.example')]:
            self.assertEqual(self.client_for(user).get(self.path('/editing')).status_code,403)
            self.assertEqual(self.client_for(user).patch(self.path(),{'version':1},format='json').status_code,403)
        other=s.create_material(self.teacher,'worksheet',{'title':'Другой листок','topics':[str(self.sheet.topics.first().pk)],'problems':[str(self.tasks[0].pk)]})
        self.assertEqual(self.client_for().patch(self.path(),{'version':1,'worksheet_id':str(other.pk)},format='json').status_code,400)
        self.assertEqual(self.client_for().patch(self.path(),{'version':1,'issued_on':(timezone.localdate()+timedelta(days=1)).isoformat()},format='json').status_code,400)
        result=self.client_for().patch(self.path(),{'version':1,'issued_on':timezone.localdate().isoformat()},format='json')
        self.assertEqual(result.status_code,200);self.assertEqual(result.data['version'],2)
        self.circle.archived=True;self.circle.save()
        self.assertEqual(self.client_for().patch(self.path(),{'version':2},format='json').status_code,403)

    def test_solve_after_discussion_is_blocked_but_existing_solve_can_be_removed(self):
        path=f'/api/circles/{self.circle.pk}/problems/{self.tasks[1].pk}/solve'
        self.assertEqual(self.client_for().post(path,{'student_id':self.student.student.pk,'value':True,'version':0},format='json').status_code,400)
        self.assertFalse(Solve.objects.filter(student=self.student.student,problem=self.tasks[1]).exists())
        Discussion.objects.create(circle=self.circle,problem=self.tasks[0],discussed=True,changed_by=self.teacher)
        result=self.client_for().post(f'/api/circles/{self.circle.pk}/problems/{self.tasks[0].pk}/solve',{'student_id':self.student.student.pk,'value':False,'version':1},format='json')
        self.assertEqual(result.status_code,200)

    def test_personal_discussion_checkbox_and_empty_denominator(self):
        included=report(self.student,self.params())
        self.assertEqual((included['assigned_pairs'],included['solved_pairs'],included['counts']['available_pairs'],included['counts']['discussed_unsolved_pairs']),(3,1,1,1))
        excluded=report(self.student,self.params(include_discussed='0'))
        self.assertEqual((excluded['assigned_pairs'],excluded['solved_pairs'],excluded['percent']),(2,1,50))
        self.assertEqual(excluded['counts']['discussed_unsolved_pairs'],0)
        self.assertEqual({row['problem_id'] for row in excluded['rows']},{str(self.tasks[i].pk) for i in [0,2]})
        for task in [self.tasks[0],self.tasks[2]]:Discussion.objects.create(circle=self.circle,problem=task,discussed=True,changed_by=self.teacher)
        empty=report(self.student,self.params(include_discussed='0'))
        self.assertEqual(empty['assigned_pairs'],0);self.assertIsNone(empty['percent']);self.assertEqual(empty['counts']['full_worksheet_count'],0)
        self.assertEqual(self.client_for(self.student).get('/api/analytics',self.params(include_discussed='bad')).status_code,400)

    def test_same_task_remains_available_in_another_assigned_circle(self):
        other=Circle.objects.exclude(pk=self.circle.pk).filter(teaching__teacher__user=self.teacher).first()
        Enrollment.objects.get_or_create(circle=other,student=self.student.student,left_at=None)
        second=s.issue_worksheet(self.teacher,other,self.sheet.pk,timezone.localdate(),visible_to_students=True)
        Assignment.objects.get_or_create(issue=second,student=self.student.student)
        data=report(self.student,{'worksheet_tag':str(self.tag.pk),'include_discussed':'0'})
        self.assertEqual((data['assigned_pairs'],data['solved_pairs'],data['counts']['available_pairs']),(3,1,2))
        narrowed=report(self.student,self.params(include_discussed='0'))
        self.assertEqual(narrowed['assigned_pairs'],2)
        Discussion.objects.create(circle=other,problem=self.tasks[1],discussed=True,changed_by=self.teacher)
        self.assertEqual(report(self.student,{'worksheet_tag':str(self.tag.pk),'include_discussed':'0'})['assigned_pairs'],2)

    def test_private_revision_is_not_exposed_to_another_teacher_and_readonly_cannot_write(self):
        revised=self.revision()
        peer=User.objects.filter(teacher__teaching__circle=self.circle).exclude(pk=self.teacher.pk).first()
        self.assertIsNotNone(peer)
        result=self.client_for(peer).get(self.path('/editing'))
        self.assertEqual(result.status_code,200)
        self.assertNotIn(str(revised.pk),[row['id'] for row in result.data['versions']])
        self.assertEqual(self.client_for(peer).patch(self.path(),{'version':1,'worksheet_id':str(revised.pk)},format='json').status_code,400)
        from .authentication import create_token
        _,secret=create_token(self.teacher,{'read_only':True})
        client=APIClient();client.credentials(HTTP_AUTHORIZATION='Bearer '+secret)
        self.assertEqual(client.get(self.path('/editing')).status_code,200)
        self.assertEqual(client.patch(self.path(),{'version':1,'worksheet_id':str(revised.pk)},format='json').status_code,403)

    def test_worksheet_completion_still_requires_all_eligible_tasks_with_tag_filters(self):
        tag=self.problem_tag
        partial=report(self.student,self.params(include_discussed='0',problem_tag=str(tag.pk)))
        self.assertEqual((partial['assigned_pairs'],partial['solved_pairs']),(1,1))
        self.assertEqual(partial['counts']['full_worksheet_count'],0)
        Solve.objects.create(student=self.student.student,problem=self.tasks[2],solved=True,changed_by=self.teacher,source_circle=self.circle)
        self.assertEqual(report(self.student,self.params(include_discussed='0',problem_tag=str(tag.pk)))['counts']['full_worksheet_count'],1)
        self.assertEqual(report(self.student,self.params())['counts']['full_worksheet_count'],0)

    def test_edit_options_use_only_lightweight_metadata_and_fixed_query_count(self):
        from .issue_updates import options
        self.revision()
        with CaptureQueriesContext(connection) as queries:result=options(self.teacher,self.circle,self.issue.pk)
        self.assertEqual(len(queries),4)
        self.assertEqual(len(result['versions']),2)
        self.assertTrue(all('"core_worksheet"."description"' not in row['sql'] for row in queries))
        self.assertTrue(all('"core_problem"."statement"' not in row['sql'] for row in queries))

    def test_old_issued_version_is_kept_outside_the_fifty_recent_versions(self):
        from .issue_updates import options
        from .models import Worksheet,WorksheetItem
        versions=Worksheet.objects.bulk_create([Worksheet(document=self.sheet.document,author=self.teacher,published=True,revision=i,title=f'Версия {i}',description='x'*30000) for i in range(2,54)])
        WorksheetItem.objects.bulk_create([WorksheetItem(worksheet=row,problem=self.tasks[0],position=1) for row in versions])
        with CaptureQueriesContext(connection) as queries:result=options(self.teacher,self.circle,self.issue.pk)
        self.assertEqual(len(queries),5)
        self.assertEqual(len(result['versions']),51)
        self.assertEqual(result['versions'][0]['revision'],53)
        original=result['versions'][-1]
        self.assertEqual((original['id'],original['added'],original['removed']),(str(self.sheet.pk),0,0))


class CompletionSetTests(SimpleTestCase):
    def test_full_completion_respects_different_recipient_groups(self):
        from .analytics import _completed_recipients
        recipients={1,2,3};required=[('a',frozenset({1,2})),('b',frozenset({2,3}))]
        self.assertEqual(_completed_recipients(recipients,required,{'a':{1},'b':{3}}),2)
        self.assertEqual(recipients,{1,2,3})
        self.assertEqual(_completed_recipients(recipients,((pid,recipients) for pid in ['a','b']),{'a':{1,2},'b':{2,3}}),1)

from datetime import timedelta
from django.core.management import call_command
from django.test import TestCase,override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from . import services as s
from .models import User, Circle, Worksheet, WorksheetDocument, Assignment, Topic, Tag, Discussion, Enrollment
from .worksheets import publish


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class WorksheetWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo',verbosity=0)
        cls.teacher=User.objects.get(email='teacher@plusfolio.example')
        cls.mentor=User.objects.get(email='mentor@plusfolio.example')
        cls.admin=User.objects.get(email='admin@plusfolio.example')
        cls.student=User.objects.get(email='student@plusfolio.example')
        cls.analyst=User.objects.get(email='analyst@plusfolio.example')
        cls.circle=Circle.objects.get(name='Математическая мастерская')
        cls.source=cls.circle.issues.first().worksheet

    def client_for(self,user):
        client=APIClient();client.force_authenticate(user=user);return client

    def copy(self,user=None,source=None):
        response=self.client_for(user or self.mentor).post(f'/api/worksheets/{(source or self.source).pk}/copy',{},format='json')
        self.assertEqual(response.status_code,201,response.data)
        return response.data

    def update(self,user,data,**changes):
        return self.client_for(user).patch('/api/worksheet-documents/'+data['document_id'],{'version':data['revision'],**changes},format='json')

    def test_copy_is_personal_owned_and_admin_can_review_it(self):
        data=self.copy()
        self.assertEqual(data['author_id'],self.mentor.pk);self.assertFalse(data['is_public'])
        self.assertTrue(data['can_edit']);self.assertEqual(data['problem_ids'],[str(pk) for pk in self.source.items.values_list('problem_id',flat=True)])
        for user in [self.teacher,self.analyst,self.student]:
            client=self.client_for(user)
            self.assertEqual(client.get('/api/worksheet-documents/'+data['document_id']).status_code,404)
            for ending in ['', '/pdf','/tex','/project']:
                self.assertEqual(client.get('/api/materials/worksheet/'+data['id']+ending).status_code,404)
            self.assertNotIn(data['id'],[row['id'] for row in client.get('/api/materials/worksheet').data])
        reviewed=self.client_for(self.admin).get('/api/worksheet-documents/'+data['document_id'])
        self.assertEqual(reviewed.status_code,200);self.assertTrue(reviewed.data['can_publish']);self.assertFalse(reviewed.data['can_edit'])

    def test_only_author_edits_and_only_admin_publishes(self):
        data=self.copy()
        for user in [self.teacher,self.admin,self.analyst,self.student]:
            self.assertEqual(self.update(user,data,title='Чужая правка').status_code,403)
        for user in [self.mentor,self.teacher,self.analyst,self.student]:
            self.assertEqual(self.client_for(user).post('/api/worksheet-documents/'+data['document_id']+'/publish',{'version':1},format='json').status_code,403)
        changed=self.update(self.mentor,data,title='Личный вариант',description=data['description'],
            topics=data['topics'],tags=[],problems=list(reversed(data['problem_ids'])))
        self.assertEqual(changed.status_code,200);self.assertEqual(changed.data['revision'],2)
        self.assertEqual(changed.data['document_id'],data['document_id'])
        self.assertEqual(changed.data['tags'],[])
        self.assertEqual(changed.data['problem_ids'],list(reversed(data['problem_ids'])))
        public=self.client_for(self.admin).post('/api/worksheet-documents/'+data['document_id']+'/publish',{'version':2},format='json')
        self.assertEqual(public.status_code,200);self.assertTrue(public.data['is_public'])
        visible=self.client_for(self.teacher).get('/api/materials/worksheet',{'scope':'public'}).data
        self.assertIn(changed.data['id'],[row['id'] for row in visible])

    def test_issued_revision_assignments_and_tex_stay_unchanged_after_edit(self):
        data=self.copy(self.teacher)
        issued=s.issue_worksheet(self.teacher,self.circle,data['id'],timezone.localdate()-timedelta(days=1))
        assigned=list(Assignment.objects.filter(issue=issued).values_list('pk','student_id','assigned_at'))
        old_ids=data['problem_ids'];replacement=list(reversed(old_ids[:-1]))
        changed=self.update(self.teacher,data,title='Исправленный листок',description='Новая редакция',problems=replacement)
        self.assertEqual(changed.status_code,200,changed.data)
        issued.refresh_from_db();self.assertEqual(str(issued.worksheet_id),data['id'])
        self.assertEqual(list(Assignment.objects.filter(issue=issued).values_list('pk','student_id','assigned_at')),assigned)
        detail=self.client_for(self.student).get(f'/api/my-issues/{issued.pk}').data
        self.assertEqual(detail['title'],data['title']);self.assertEqual(detail['problem_ids'],old_ids)
        source=self.client_for(self.teacher).get(f'/api/circles/{self.circle.pk}/issues/{issued.pk}/tex')
        self.assertEqual(source.status_code,200);self.assertIn(data['title'],source.content.decode());self.assertNotIn('Исправленный листок',source.content.decode())
        other=Circle.objects.get(name='Олимпиадный старт')
        new_issue=s.issue_worksheet(self.teacher,other,changed.data['id'],timezone.localdate())
        self.assertEqual(new_issue.worksheet.title,'Исправленный листок')
        duplicate=self.client_for(self.teacher).post(f'/api/circles/{self.circle.pk}/issues',{'worksheet_id':changed.data['id'],'issued_on':timezone.localdate().isoformat()},format='json')
        self.assertEqual(duplicate.status_code,400)

    def test_public_version_stays_until_admin_publishes_new_revision(self):
        data=self.copy(self.teacher)
        publish(self.admin,data['document_id'],{'version':1})
        changed=self.update(self.teacher,data,title='Ещё не опубликовано').data
        self.assertFalse(changed['is_public']);self.assertTrue(changed['has_unpublished_changes'])
        reader=self.client_for(self.mentor)
        current=reader.get('/api/worksheet-documents/'+data['document_id']).data
        self.assertEqual(current['id'],data['id']);self.assertEqual(current['title'],data['title'])
        self.assertEqual(reader.get('/api/materials/worksheet/'+changed['id']).status_code,404)
        publish(self.admin,data['document_id'],{'version':2})
        self.assertEqual(reader.get('/api/worksheet-documents/'+data['document_id']).data['id'],changed['id'])

    def test_edit_and_publish_conflicts_do_not_overwrite_newer_revision(self):
        data=self.copy();self.assertEqual(self.update(self.mentor,data,title='Новая версия').status_code,200)
        before=Worksheet.objects.count()
        self.assertEqual(self.update(self.mentor,data,title='Устаревшая правка').status_code,409)
        response=self.client_for(self.admin).post('/api/worksheet-documents/'+data['document_id']+'/publish',{'version':1},format='json')
        self.assertEqual(response.status_code,409);self.assertEqual(Worksheet.objects.count(),before)
        self.assertIsNone(WorksheetDocument.objects.get(pk=data['document_id']).public_revision_id)

    def test_analyst_and_student_can_edit_personal_copies_without_revealing_solutions(self):
        for user in [self.analyst,self.student]:
            with self.subTest(user=user.pk):
                data=self.copy(user)
                self.assertEqual(self.update(user,data,title='Моя подборка').status_code,200)
                if user==self.student:
                    self.assertTrue(all('solution' not in row for row in data['problems']))
                    source=self.client_for(user).get('/api/materials/worksheet/'+data['id']+'/tex')
                    self.assertEqual(source.status_code,403)
                public=self.client_for(user).post('/api/worksheet-documents/'+data['document_id']+'/publish',{'version':1},format='json')
                self.assertEqual(public.status_code,403)

    def test_hidden_copy_cannot_be_copied_or_injected_into_another_sheet(self):
        hidden=self.copy()
        self.assertEqual(self.client_for(self.teacher).post('/api/worksheets/'+hidden['id']+'/copy',{},format='json').status_code,404)
        personal=self.copy(self.student)
        topic=Topic.objects.filter(parent__isnull=False,is_other=False,archived=False).first()
        unknown=s.create_material(self.teacher,'problem',{'title':'Не выдавалась','statement':'Условие','solution':'Скрыто','topics':[str(topic.pk)]})
        response=self.update(self.student,personal,problems=[str(unknown.pk)])
        self.assertEqual(response.status_code,400)

    def test_copy_does_not_keep_solution_access_after_membership_is_revoked(self):
        problem=self.source.items.first().problem
        Discussion.objects.update_or_create(circle=self.circle,problem=problem,defaults={'discussed':True,'solution_visible':True,'changed_by':self.teacher})
        data=self.copy(self.student)
        self.assertIn('solution',next(row for row in data['problems'] if row['id']==str(problem.pk)))
        Enrollment.objects.filter(student__user=self.student,left_at=None).update(left_at=timezone.now())
        response=self.client_for(self.student).get('/api/worksheet-documents/'+data['document_id'])
        self.assertEqual(response.status_code,200)
        self.assertTrue(all('solution' not in row and 'solution_tex' not in row for row in response.data['problems']))

    def test_new_worksheets_are_private_even_for_admin_and_keep_typed_filters(self):
        topic=Topic.objects.filter(parent__isnull=False,is_other=False,archived=False).first()
        tag=Tag.objects.filter(kind='worksheet',archived=False).first()
        response=self.client_for(self.admin).post('/api/materials/worksheet',{'title':'Новый личный листок','topics':[str(topic.pk)],'tags':[tag.pk],'problems':[str(self.source.items.first().problem_id)]},format='json')
        self.assertEqual(response.status_code,201);self.assertFalse(response.data['is_public'])
        own=self.client_for(self.admin).get('/api/materials/worksheet',{'scope':'mine','tag':tag.pk,'topic':str(topic.pk)}).data
        self.assertIn(response.data['id'],[row['id'] for row in own])
        self.assertEqual(self.client_for(self.teacher).get('/api/materials/worksheet',{'scope':'all'}).status_code,403)

    def test_invalid_edit_rolls_back_revision_and_document_pointer(self):
        data=self.copy();before=Worksheet.objects.count()
        response=self.update(self.mentor,data,problems=[])
        self.assertEqual(response.status_code,400);self.assertEqual(Worksheet.objects.count(),before)
        self.assertEqual(str(WorksheetDocument.objects.get(pk=data['document_id']).current_revision_id),data['id'])

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase,SimpleTestCase,override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from . import services as s
from .identifiers import typed_id
from .models import User, Student, Circle, Topic, WorksheetDocument, Problem, Tag, Enrollment

class IdentifierParsingTests(SimpleTestCase):
    def test_case_whitespace_zero_padding_and_overflow(self):
        self.assertEqual(typed_id(' p - 00123 '),('problem',123))
        self.assertEqual(typed_id('S-0'),('student',None))
        self.assertEqual(typed_id('W-'+('9'*160)),('worksheet',None))
        self.assertEqual(typed_id('U-9223372036854775808'),('user',None))
        self.assertIsNone(typed_id('mathematics'))

@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class EntityIdentifierTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo',verbosity=0)
        cls.admin=User.objects.get(email='admin@plusfolio.example')
        cls.teacher=User.objects.get(email='teacher@plusfolio.example')
        cls.mentor=User.objects.get(email='mentor@plusfolio.example')
        cls.student=User.objects.get(email='student@plusfolio.example')
        cls.circle=Circle.objects.get(name='Математическая мастерская')
        cls.sheet=cls.circle.issues.first().worksheet
        cls.problem=cls.sheet.items.first().problem

    def client_for(self,user):
        client=APIClient();client.force_authenticate(user=user);return client

    def get(self,user,path,query):
        result=self.client_for(user).get('/api/'+path,{'q':query})
        self.assertEqual(result.status_code,200,result.data);return result.data

    def test_ids_exposed_in_account_materials_circles_members_topics_and_tags(self):
        client=self.client_for(self.student)
        me=client.get('/api/account').data['user']
        self.assertEqual(me['public_id'],f'U-{self.student.pk}')
        self.assertEqual(me['student_public_id'],f'S-{self.student.student.pk}')
        circle=self.get(self.student,'circles',f'C-{self.circle.number_id}')[0]
        self.assertEqual(circle['public_id'],f'C-{self.circle.number_id}')
        members=client.get(f'/api/circles/{self.circle.pk}/members').data
        self.assertTrue(all(row['public_id'].startswith('S-') for row in members))
        self.assertFalse(any('email' in row for row in members))
        for kind,obj,prefix in [('problem',self.problem,'P'),('worksheet',self.sheet,'W')]:
            detail=client.get(f'/api/materials/{kind}/{obj.pk}').data
            number=obj.number_id if kind=='problem' else obj.document.number_id
            self.assertEqual(detail['public_id'],f'{prefix}-{number}')
        topic=Topic.objects.first();tag=Tag.objects.first()
        self.assertEqual(self.get(self.admin,'topics',f'TOP-{topic.number_id}')['topics'][0]['id'],str(topic.pk))
        self.assertEqual(self.get(self.admin,'tags',f'TAG-{tag.pk}')[0]['id'],tag.pk)

    def test_separate_types_and_problem_source_numbers_do_not_collide(self):
        target=Problem.objects.create(author=self.admin,statement='x',solution='hidden',published=True)
        other=Problem.objects.create(author=self.admin,source='problems.ru',source_id=str(target.number_id),statement='y',solution='z',published=True)
        rows=self.get(self.teacher,'materials/problem',f'p-{target.number_id:05d}')
        self.assertEqual([row['id'] for row in rows],[str(target.pk)])
        self.assertEqual({row['id'] for row in self.get(self.teacher,'materials/problem',str(target.number_id))},{str(target.pk),str(other.pk)})
        self.assertEqual(self.get(self.teacher,'materials/problem',f'W-{target.number_id}'),[])
        self.assertEqual(self.get(self.teacher,'materials/problem','P-'+('9'*100)),[])
        self.assertEqual(self.get(self.teacher,'materials/problem',str(target.pk))[0]['id'],str(target.pk))

    def test_student_picker_distinguishes_user_and_student_identity(self):
        self.assertNotEqual(self.student.pk,self.student.student.pk)
        path=f'circles/{self.circle.pk}/student-search'
        for text in [f'S-{self.student.student.pk}',f'U-{self.student.pk}',str(self.student.student.pk)]:
            rows=self.get(self.teacher,path,text)
            self.assertEqual([row['id'] for row in rows],[self.student.student.pk])
            self.assertNotIn('email',rows[0]);self.assertIn('•••',rows[0]['email_hint'])
        self.assertEqual(self.get(self.teacher,path,f'P-{self.student.student.pk}'),[])
        self.assertEqual(self.client_for(self.student).get('/api/'+path,{'q':f'S-{self.student.student.pk}'}).status_code,403)
        inactive=User.objects.create_user(email='inactive@example.test',name='Неактивный школьник',roles=['student'],is_active=False)
        profile=Student.objects.create(user=inactive)
        self.assertEqual(self.get(self.teacher,path,f'S-{profile.pk}'),[])

    def test_picker_adds_selected_student_without_confusing_user_pk(self):
        account=User.objects.create_user(email='new-id@example.test',name='Новый Ученик Ученикович',roles=['student'])
        student=Student.objects.create(user=account,graduation_year=2032)
        rows=self.get(self.teacher,f'circles/{self.circle.pk}/student-search',f'U-{account.pk}')
        result=self.client_for(self.teacher).post(f'/api/circles/{self.circle.pk}/members',{'student_id':rows[0]['id']},format='json')
        self.assertEqual(result.status_code,200,result.data)
        self.assertTrue(Enrollment.objects.filter(circle=self.circle,student=student,left_at=None).exists())
        self.assertEqual(student.assignments.count(),self.circle.issues.count())

    def test_admin_user_search_accepts_each_profile_type_and_regular_text(self):
        for text in [f'U-{self.student.pk}',f'S-{self.student.student.pk}',str(self.student.pk)]:
            self.assertEqual([row['id'] for row in self.get(self.admin,'users',text)],[self.student.pk])
        self.assertEqual(self.get(self.admin,'users',f'T-{self.teacher.teacher.pk}')[0]['id'],self.teacher.pk)
        self.assertEqual(self.client_for(self.teacher).get('/api/users',{'q':f'U-{self.student.pk}'}).status_code,403)
        self.assertIn(self.student.pk,[row['id'] for row in self.get(self.admin,'users',self.student.email)])

    def test_private_worksheet_id_does_not_bypass_scope(self):
        private=s.create_material(self.mentor,'worksheet',{'title':'Секретная подборка','topics':[str(self.problem.topics.first().pk)],'problems':[str(self.problem.pk)]})
        key=f'W-{private.document.number_id}'
        for user in [self.teacher,self.student]:
            self.assertEqual(self.get(user,'materials/worksheet',key),[])
            self.assertEqual(self.client_for(user).get(f'/api/worksheet-documents/{private.document_id}').status_code,404)
        self.assertEqual(self.get(self.mentor,'materials/worksheet',key)[0]['id'],str(private.pk))
        self.assertEqual(self.get(self.admin,'materials/worksheet',key)[0]['id'],str(private.pk))

    def test_edit_keeps_sheet_id_and_issued_snapshot_copy_gets_new_id(self):
        client=self.client_for(self.teacher)
        copied=client.post(f'/api/worksheets/{self.sheet.pk}/copy',{},format='json').data
        issue=s.issue_worksheet(self.teacher,self.circle,copied['id'],timezone.localdate())
        changed=client.patch('/api/worksheet-documents/'+copied['document_id'],{'version':1,'title':'Новая версия'},format='json')
        self.assertEqual(changed.status_code,200,changed.data)
        self.assertEqual(changed.data['public_id'],copied['public_id'])
        self.assertNotEqual(copied['public_id'],f'W-{self.sheet.document.number_id}')
        issue.refresh_from_db();self.assertEqual(str(issue.worksheet_id),copied['id'])
        for query in [copied['public_id'],copied['document_id']]:
            found=self.get(self.student,'my-materials/worksheet',query)
            self.assertEqual(found[0]['public_id'],copied['public_id']);self.assertEqual(found[0]['worksheet_id'],copied['id'])
        detail=self.client_for(self.student).get(f'/api/my-issues/{issue.pk}').data
        self.assertEqual(detail['public_id'],copied['public_id'])

    def test_id_search_does_not_reveal_unassigned_problems_or_solutions(self):
        hidden=Problem.objects.create(author=self.admin,statement='private statement',solution='private solution',published=True)
        self.assertEqual(self.get(self.student,'my-materials/problem',f'P-{hidden.number_id}'),[])
        rows=self.get(self.student,'my-materials/problem',f'P-{self.problem.number_id}')
        self.assertEqual(rows[0]['id'],str(self.problem.pk));self.assertNotIn('solution',rows[0])
        hidden_circle=Circle.objects.exclude(pk__in=s.circles_for(self.student)).first()
        self.assertIsNotNone(hidden_circle)
        self.assertEqual(self.get(self.student,'circles',f'C-{hidden_circle.number_id}'),[])

    def test_journal_and_export_share_id_filter(self):
        path=f'circles/{self.circle.pk}/journal'
        for query in [f'S-{self.student.student.pk}',f'U-{self.student.pk}',str(self.student.student.pk)]:
            journal=self.get(self.teacher,path,query)
            self.assertEqual([row['id'] for row in journal['people']],[self.student.student.pk])
            self.assertTrue(journal['blocks'][0]['worksheet']['public_id'].startswith('W-'))
            exported=self.client_for(self.teacher).get('/api/'+path+'/export',{'q':query,'file_format':'tsv'})
            self.assertEqual(exported.status_code,200)
            self.assertIn(self.student.name,exported.content.decode('utf-8-sig'))

    def test_number_allocation_on_bulk_create_and_save_is_unique_and_stable(self):
        for Model,kwargs in [(Circle,{'name':'a','created_by':self.admin}),(Topic,{'name':'a'}),(WorksheetDocument,{'author':self.admin})]:
            with self.subTest(Model=Model.__name__):
                first=Model.objects.create(**kwargs)
                rows=Model.objects.bulk_create([Model(**kwargs),Model(**kwargs)])
                self.assertEqual(len({first.number_id,*[obj.number_id for obj in rows]}),3)
                previous=first.number_id;first.save();first.refresh_from_db();self.assertEqual(first.number_id,previous)
                first.number_id=rows[0].number_id
                with self.assertRaises(ValidationError):first.save()

    def test_teacher_assignment_by_typed_id_is_still_admin_only(self):
        key=f'T-{self.mentor.teacher.pk}';path=f'/api/circles/{self.circle.pk}/teachers'
        self.assertEqual(self.client_for(self.teacher).post(path,{'email':key},format='json').status_code,403)
        result=self.client_for(self.admin).post(path,{'email':key},format='json')
        self.assertEqual(result.status_code,200,result.data)
        self.assertIn(key,[row['public_id'] for row in result.data['teachers']])

    def test_invitation_id_is_searchable_only_for_sender_or_admin(self):
        invitation=s.invite(self.admin,'inv-id@example.test','student',self.circle)
        key=f'INV-{invitation.number_id}'
        self.assertEqual(self.get(self.admin,'invitations',key)[0]['id'],str(invitation.pk))
        self.assertEqual(self.get(self.teacher,'invitations',key),[])

    def test_issue_search_by_issue_id_or_document_id_stays_scoped(self):
        issue=self.circle.issues.first()
        for query in [f'ISS-{issue.pk}',f'W-{issue.worksheet.document.number_id}']:
            result=self.get(self.teacher,f'circles/{self.circle.pk}/issues',query)
            self.assertEqual([row['id'] for row in result],[issue.pk])
            own=self.get(self.student,'my-materials/worksheet',query)
            self.assertIn(issue.pk,[row['id'] for row in own])
            if query.startswith('ISS-'):self.assertEqual([row['id'] for row in own],[issue.pk])
            else:self.assertTrue(all(row['public_id']==query for row in own))
        other=Circle.objects.exclude(pk__in=s.circles_for(self.student)).first()
        self.assertEqual(self.client_for(self.student).get(f'/api/circles/{other.pk}/issues',{'q':f'ISS-{issue.pk}'}).status_code,404)

    def test_analytics_rows_expose_corresponding_ids(self):
        result=self.client_for(self.teacher).get('/api/analytics').data
        for field,prefix in [('rows','P-'),('worksheet_rows','W-'),('student_rows','S-'),('circle_rows','C-'),('topic_rows','TOP-')]:
            self.assertTrue(result[field])
            self.assertTrue(all(row['public_id'].startswith(prefix) for row in result[field] if row.get('id','problem') is not None))

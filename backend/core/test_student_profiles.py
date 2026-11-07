from django.test import TestCase,override_settings
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient
from . import services as s
from .models import AnalystGrant,Assignment,Circle,CircleTeacher,Discussion,Enrollment,Problem,Solve,Tag,User,Worksheet,WorksheetDocument,WorksheetIssue,WorksheetItem


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class StudentProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        def account(name,roles):
            user=User.objects.create_user(name+'@example.test','test-password',name=name,roles=roles)
            s.profiles(user);return user
        cls.teacher=account('teacher',['teacher']);cls.analyst=account('analyst',['analyst'])
        cls.admin=account('admin',['admin']);cls.other=account('other',['teacher'])
        cls.pupil=account('pupil',['student']);cls.peer=account('peer',['student']);cls.foreign=account('foreign',['student'])
        cls.dual=account('dual',['teacher','student'])
        cls.circle=Circle.objects.create(name='Доступный',city='Москва',created_by=cls.admin)
        cls.secret=Circle.objects.create(name='Закрытый',city='Тула',created_by=cls.admin)
        for user,circle in [(cls.teacher,cls.circle),(cls.dual,cls.circle),(cls.other,cls.secret)]:
            CircleTeacher.objects.create(circle=circle,teacher=user.teacher)
        tag=Tag.objects.create(name='Доступ аналитика',kind='circle');cls.circle.tags.add(tag)
        AnalystGrant.objects.create(user=cls.analyst,tag=tag)
        for user,circles in [(cls.pupil,[cls.circle,cls.secret]),(cls.peer,[cls.circle]),(cls.foreign,[cls.secret]),(cls.dual,[cls.secret])]:
            for circle in circles:Enrollment.objects.create(circle=circle,student=user.student)
        cls.tasks=[Problem.objects.create(author=cls.teacher,title=f'Задача {i}',statement='Условие',solution='Ответ',published=True) for i in range(4)]
        def issue(circle,indexes,recipients):
            document=WorksheetDocument.objects.create(author=cls.teacher)
            sheet=Worksheet.objects.create(document=document,author=cls.teacher,title=circle.name,published=True)
            WorksheetItem.objects.bulk_create([WorksheetItem(worksheet=sheet,problem=cls.tasks[i],position=n+1,include_in_journal=i!=2) for n,i in enumerate(indexes)])
            document.current_revision=sheet;document.public_revision=sheet;document.save()
            issued=WorksheetIssue.objects.create(circle=circle,worksheet=sheet,document=document,issued_by=cls.teacher,issued_on=timezone.localdate(),number=1)
            Assignment.objects.bulk_create([Assignment(issue=issued,student=user.student) for user in recipients]);return issued
        cls.issue=issue(cls.circle,[0,1,2],[cls.pupil,cls.peer])
        cls.private_issue=issue(cls.secret,[0,3],[cls.pupil,cls.foreign,cls.dual])
        Solve.objects.create(student=cls.pupil.student,problem=cls.tasks[0],solved=True,changed_by=cls.teacher,source_circle=cls.secret)
        Solve.objects.create(student=cls.pupil.student,problem=cls.tasks[3],solved=True,changed_by=cls.other,source_circle=cls.secret)
        Solve.objects.create(student=cls.peer.student,problem=cls.tasks[1],solved=True,changed_by=cls.teacher,source_circle=cls.circle)
        Discussion.objects.create(circle=cls.circle,problem=cls.tasks[1],discussed=True,changed_by=cls.teacher)

    def get(self,user,path,params=None):
        client=APIClient();client.force_authenticate(user=user)
        return client.get(path,params or {})

    def path(self,suffix='',student=None,prefix='/api'):
        return f'{prefix}/students/{(student or self.pupil).student.pk}{suffix}'

    def test_adult_profiles_include_only_authorized_participation_without_contacts(self):
        for user,expected in [(self.teacher,{str(self.circle.pk)}),(self.analyst,{str(self.circle.pk)}),(self.admin,{str(self.circle.pk),str(self.secret.pk)})]:
            with self.subTest(user=user.name):
                result=self.get(user,self.path());self.assertEqual(result.status_code,200,result.data)
                self.assertEqual({row['id'] for row in result.data['circles']},expected)
                self.assertEqual(result.data['public_id'],f'S-{self.pupil.student.pk}')
                self.assertNotIn('email',result.data)
                self.assertTrue(all(row['issue_count']==1 for row in result.data['circles']))
        newcomer=User.objects.create_user('newcomer@example.test','test-password',name='Новый школьник',roles=['student'])
        s.profiles(newcomer)
        existing=next(row for row in self.get(self.admin,'/api/users').data if row['id']==newcomer.pk)
        profile=self.get(self.admin,self.path(student=newcomer)).data
        for key in ['name','graduation_year','current_grade','grade_label']:
            self.assertEqual(profile[key],existing[key])
        self.assertEqual(profile['user_public_id'],existing['public_id'])
        self.assertEqual(profile['public_id'],existing['student_public_id'])
        self.assertEqual(profile['circles'],[])
        self.assertEqual(self.get(self.admin,self.path('/analytics',newcomer)).data['assigned_pairs'],0)
        for user in [self.teacher,self.analyst]:self.assertEqual(self.get(user,self.path(student=newcomer)).status_code,404)

    def test_students_cannot_read_their_own_or_other_profiles_and_reports(self):
        for target in [self.pupil,self.peer]:
            for suffix in ['', '/analytics']:
                for prefix in ['/api','/api/v1']:
                    self.assertEqual(self.get(self.pupil,self.path(suffix,target,prefix)).status_code,403)
        self.assertEqual(self.get(None,self.path()).status_code,403)

    def test_unrelated_students_and_revoked_teacher_access_return_not_found(self):
        for suffix in ['', '/analytics']:
            self.assertEqual(self.get(self.teacher,self.path(suffix,self.foreign)).status_code,404)
            self.assertEqual(self.get(self.teacher,'/api/students/999999'+suffix).status_code,404)
        CircleTeacher.objects.filter(teacher=self.teacher.teacher,circle=self.circle).update(ended_at=timezone.now())
        self.assertEqual(self.get(self.teacher,self.path()).status_code,404)
        AnalystGrant.objects.filter(user=self.analyst).delete()
        self.assertEqual(self.get(self.analyst,self.path()).status_code,404)

    def test_report_filters_all_tables_to_the_student_and_keeps_global_solves(self):
        for user in [self.teacher,self.analyst]:
            result=self.get(user,self.path('/analytics'));self.assertEqual(result.status_code,200,result.data)
            data=result.data
            self.assertEqual((data['assigned_pairs'],data['solved_pairs'],data['student_count']),(2,1,1))
            self.assertEqual(data['subject_student_id'],self.pupil.student.pk)
            self.assertEqual({row['id'] for row in data['student_rows']},{self.pupil.student.pk})
            self.assertEqual({row['id'] for row in data['circle_rows']},{str(self.circle.pk)})
            self.assertEqual({row['problem_id'] for row in data['rows']},{str(task.pk) for task in self.tasks[:2]})
            self.assertEqual(data['counts']['full_worksheet_count'],0)
            excluded=self.get(user,self.path('/analytics'),{'include_discussed':'0'}).data
            self.assertEqual((excluded['assigned_pairs'],excluded['solved_pairs'],excluded['counts']['full_worksheet_count']),(1,1,1))
            self.assertEqual(self.get(user,self.path('/analytics'),{'city':'Тула'}).data['assigned_pairs'],0)
            self.assertEqual(self.get(user,self.path('/analytics'),{'circle':str(self.secret.pk)}).status_code,404)
            self.assertEqual(self.get(user,self.path('/analytics'),{'include_discussed':'bad'}).status_code,400)

    def test_regular_reports_do_not_name_an_individual_subject(self):
        for user,expected_count in [(self.teacher,2),(self.analyst,2),(self.pupil,1)]:
            with self.subTest(user=user.name):
                result=self.get(user,'/api/analytics',{'circle':str(self.circle.pk)})
                self.assertEqual(result.status_code,200,result.data)
                self.assertEqual(result.data['student_count'],expected_count)
                self.assertNotIn('subject_student_id',result.data)

    def test_combined_student_role_does_not_add_personal_circles_to_other_student_reports(self):
        data=self.get(self.dual,self.path()).data
        self.assertEqual({row['id'] for row in data['circles']},{str(self.circle.pk)})
        data=self.get(self.dual,self.path('/analytics')).data
        self.assertEqual((data['assigned_pairs'],data['solved_pairs']),(2,1))
        self.assertEqual(self.get(self.dual,self.path('/analytics'),{'circle':str(self.secret.pk)}).status_code,404)

    def test_former_members_and_archived_circles_keep_history_and_empty_reports(self):
        Enrollment.objects.filter(circle=self.circle,student=self.pupil.student).update(left_at=timezone.now())
        Circle.objects.filter(pk=self.circle.pk).update(archived=True)
        data=self.get(self.teacher,self.path()).data
        self.assertFalse(data['circles'][0]['active']);self.assertTrue(data['circles'][0]['archived'])
        self.assertIsNotNone(data['circles'][0]['periods'][0]['left_at'])
        Assignment.objects.filter(issue=self.issue,student=self.pupil.student).delete()
        result=self.get(self.teacher,self.path('/analytics'))
        self.assertEqual(result.status_code,200,result.data);self.assertEqual(result.data['assigned_pairs'],0)
        self.assertEqual(result.data['subject_student_id'],self.pupil.student.pk)
        self.assertIsNone(result.data['percent'])

    def test_read_only_adult_token_can_read_profile_and_report(self):
        from .authentication import create_token
        _,secret=create_token(self.teacher,{'read_only':True})
        client=APIClient();client.credentials(HTTP_AUTHORIZATION='Bearer '+secret)
        for suffix in ['', '/analytics']:
            response=client.get(self.path(suffix,prefix='/api/v1'))
            self.assertEqual(response.status_code,200,response.data)

    def test_journal_exposes_assignment_recipients_only_with_group_stats(self):
        Assignment.objects.filter(issue=self.issue,student=self.peer.student).delete()
        for user in [self.teacher,self.analyst]:
            path=f'/api/circles/{self.circle.pk}/journal'
            data=self.get(user,path).data
            self.assertEqual(data['blocks'][0]['recipient_ids'],[self.pupil.student.pk])
            filtered=self.get(user,path,{'q':f'S-{self.peer.student.pk}'}).data
            self.assertEqual(filtered['blocks'][0]['recipient_ids'],[])
        data=self.get(self.pupil,f'/api/circles/{self.circle.pk}/journal').data
        self.assertFalse(data['show_group_stats']);self.assertNotIn('recipient_ids',data['blocks'][0])

    def test_subject_assignment_scope_uses_two_queries_for_every_adult_role(self):
        from .analytics import scoped_assignments
        for user in [self.teacher,self.analyst,self.dual,self.admin]:
            with self.subTest(role=user.name):
                with CaptureQueriesContext(connection) as queries:
                    assignments,_,_=scoped_assignments(user,{},student=self.pupil.student)
                    rows=list(assignments.values_list('issue_id',flat=True))
                self.assertEqual(len(queries),2)
                self.assertEqual(set(rows),{self.issue.pk,self.private_issue.pk} if user==self.admin else {self.issue.pk})

    def test_long_participation_history_does_not_multiply_issue_counts_or_queries(self):
        from .student_profiles import profile
        Enrollment.objects.bulk_create([Enrollment(student=self.pupil.student,circle=self.circle,left_at=timezone.now()) for _ in range(1005)])
        with CaptureQueriesContext(connection) as queries:data=profile(self.teacher,self.pupil.student)
        self.assertEqual(len(queries),3)
        self.assertEqual(len(data['circles']),1)
        self.assertEqual(len(data['circles'][0]['periods']),1006)
        self.assertEqual(data['circles'][0]['issue_count'],1)
        self.assertTrue(data['circles'][0]['active'])

    def test_journal_people_do_not_load_account_secrets_or_deferred_fields_per_row(self):
        from .journal import snapshot,select_issues
        selected=select_issues(self.circle,for_export=True)
        with CaptureQueriesContext(connection) as queries:
            data=snapshot(self.teacher,self.circle,selected,lambda task,user:{'id':str(task.pk),'title':task.title})
        people=[query['sql'] for query in queries if 'FROM "core_enrollment"' in query['sql']]
        self.assertEqual(len(queries),5)
        self.assertEqual(len(people),1)
        for field in ['password','email','roles','first_name','last_name']:
            self.assertNotIn('"core_user"."'+field+'"',people[0])
        self.assertEqual(len(data['people']),2)

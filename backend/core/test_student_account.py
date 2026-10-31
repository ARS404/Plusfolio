from datetime import timedelta
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from . import services as s
from .authentication import create_token
from .models import ApiToken, Student, User


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class StudentAccountTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('student@example.test','TestPassword2026!',name='Иванов Иван Иванович',
                                          last_name='Иванов',first_name='Иван',roles=['student'])
        Student.objects.create(user=self.user,patronymic='Иванович',graduation_year=2031)
        self.client=APIClient();self.client.force_login(self.user)

    def test_student_cannot_get_or_manage_api_credentials_or_use_cookie_api(self):
        with self.assertRaises(PermissionDenied):create_token(self.user,{})
        anonymous=APIClient()
        result=anonymous.post('/api/v1/auth/token',{'login':self.user.email,'password':'TestPassword2026!'},format='json')
        self.assertEqual(result.status_code,403)
        for path in ['account','circles','openapi.json','documentation','auth/tokens']:
            self.assertEqual(self.client.get('/api/v1/'+path).status_code,403,path)
        self.assertEqual(self.client.post('/api/v1/auth/tokens',{'password':'TestPassword2026!'},format='json').status_code,403)
        self.assertFalse(ApiToken.objects.exists())
        self.assertEqual(self.client.get('/api/account').status_code,200)
        guide=self.client.get('/api/documentation',{'audience':'robot'}).data
        self.assertEqual(guide['audience'],'human')
        self.assertFalse(guide['can_use_api'])
        self.assertFalse(any(section['id'].startswith('api-') for section in guide['sections']))

    def test_existing_bearer_and_stale_creation_are_denied_after_role_change(self):
        self.user.roles=['teacher','student'];self.user.save();s.profiles(self.user)
        stale=User.objects.get(pk=self.user.pk)
        token,secret=create_token(self.user,{})
        self.user.roles=['student'];self.user.save()
        self.client.credentials(HTTP_AUTHORIZATION='Bearer '+secret)
        self.assertEqual(self.client.get('/api/v1/account').status_code,401)
        token.refresh_from_db();self.assertIsNone(token.last_used_at)
        with self.assertRaises(PermissionDenied):create_token(stale,{})

    def test_each_adult_role_allows_api_when_combined_with_student(self):
        for role in ['teacher','analyst','admin']:
            self.user.roles=['student',role];self.user.save();s.profiles(self.user)
            _,secret=create_token(self.user,{})
            self.client.credentials(HTTP_AUTHORIZATION='Bearer '+secret)
            response=self.client.get('/api/v1/account')
            self.assertEqual(response.status_code,200,role)
            self.assertTrue(response.data['user']['can_use_api'])

    def test_removing_the_last_adult_role_permanently_revokes_old_tokens(self):
        self.user.roles=['student','teacher'];self.user.save();s.profiles(self.user)
        token,secret=create_token(self.user,{})
        admin=User.objects.create_user('admin@example.test','TestPassword2026!',name='Админ',roles=['admin'])
        self.client.force_login(admin)
        self.assertEqual(self.client.patch('/api/users',{'id':self.user.pk,'roles':['student'],'tags':[]},format='json').status_code,200)
        token.refresh_from_db();self.assertIsNotNone(token.revoked_at)
        self.user.roles=['teacher'];self.user.save()
        self.client.credentials(HTTP_AUTHORIZATION='Bearer '+secret)
        self.assertEqual(self.client.get('/api/v1/account').status_code,401)

    def test_separate_name_fields_preserve_compound_names_and_require_each_part(self):
        data={'last_name':'де ла Круз','first_name':'Анна Мария','patronymic':'Ивановна','graduation_year':2032,'no_patronymic':False}
        for field in data:
            missing={key:value for key,value in data.items() if key!=field}
            self.assertEqual(self.client.patch('/api/account',missing,format='json').status_code,400,field)
        with CaptureQueriesContext(connection) as queries:
            response=self.client.patch('/api/account',data,format='json')
        self.assertEqual(sum('FROM "core_student"' in query['sql'] for query in queries),1)
        self.assertEqual(response.status_code,200,response.data)
        for field,value in data.items():self.assertEqual(response.data['user'][field],value)
        self.assertEqual(response.data['user']['name'],'де ла Круз Анна Мария Ивановна')
        self.assertTrue(response.data['user']['profile_complete'])
        self.assertEqual(self.client.patch('/api/account',{**data,'patronymic':''},format='json').status_code,400)
        self.assertEqual(self.client.patch('/api/account',{**data,'no_patronymic':True},format='json').status_code,400)
        self.assertEqual(self.client.patch('/api/account',{**data,'patronymic':'','no_patronymic':True},format='json').status_code,200)


class StudentIdentityMigrationTests(TransactionTestCase):
    def test_legacy_names_are_preserved_and_only_student_tokens_revoked(self):
        executor=MigrationExecutor(connection)
        latest=executor.loader.graph.leaf_nodes()
        previous=[('core','0014_material_order_indexes')]
        current=[('core','0015_student_name_parts')]
        try:
            executor.migrate(previous)
            apps=executor.loader.project_state(previous).apps
            users=apps.get_model('core','User').objects
            students=apps.get_model('core','Student').objects
            tokens=apps.get_model('core','ApiToken').objects
            pupil=users.create(email='legacy@example.test',name='Семёнов Алексей Петрович',roles=['student'],password='!')
            students.create(user=pupil,graduation_year=2031)
            ambiguous=users.create(email='ambiguous@example.test',name='де ла Круз Анна Мария',roles=['student'],password='!')
            students.create(user=ambiguous)
            structured=users.create(email='structured@example.test',name='Прежнее имя',roles=['student'],password='!',
                                    first_name='Анна Мария',last_name='де ла Круз')
            students.create(user=structured)
            mixed=users.create(email='mixed@example.test',name='Учитель',roles=['student','teacher'],password='!')
            for index,user in enumerate([pupil,mixed]):
                tokens.create(user=user,name='Legacy',prefix=str(index),digest=str(index)*64,password_stamp='stamp',expires_at=timezone.now()+timedelta(days=1))
            executor=MigrationExecutor(connection);executor.migrate(current)
            pupil=User.objects.get(pk=pupil.pk)
            self.assertEqual((pupil.name,pupil.last_name,pupil.first_name,pupil.student.patronymic),
                             ('Семёнов Алексей Петрович','Семёнов','Алексей','Петрович'))
            self.assertEqual(User.objects.get(pk=ambiguous.pk).name,'де ла Круз Анна Мария')
            self.assertEqual(User.objects.get(pk=ambiguous.pk).last_name,'')
            structured=User.objects.get(pk=structured.pk)
            self.assertEqual((structured.name,structured.first_name,structured.last_name),('Прежнее имя','Анна Мария','де ла Круз'))
            self.assertIsNotNone(ApiToken.objects.get(user=pupil).revoked_at)
            self.assertIsNone(ApiToken.objects.get(user_id=mixed.pk).revoked_at)
        finally:
            MigrationExecutor(connection).migrate(latest)

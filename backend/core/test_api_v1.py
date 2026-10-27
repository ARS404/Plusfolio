from datetime import timedelta
from types import SimpleNamespace
import hashlib
import json
import sqlite3

from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import resolve
from django.utils import timezone
from rest_framework.test import APIClient

from .authentication import create_token
from .api_contract import operations_for
from .api_reference import schema_for
from .api_renderers import versioned_urls
from .documentation import documentation_for
from .documentation_export import markdown_documentation
from .models import ApiToken, Circle, CircleTeacher, Discussion, User


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], AUTH_PASSWORD_VALIDATORS=[])
class ApiTokenTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('robot@plusfolio.example','TestPassword2026!',name='Проверка API',roles=['teacher'])
        self.other = User.objects.create_user('other-robot@plusfolio.example','OtherPassword2026!',name='Другой аккаунт',roles=['teacher'])
        self.client = APIClient(enforce_csrf_checks=True)

    def token(self, user=None, **options):
        return create_token(user or self.user, options)

    def authorize(self, secret):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer '+secret)

    def test_password_exchange_returns_secret_once_and_no_browser_session(self):
        result=self.client.post('/api/v1/auth/token',{'login':self.user.email.upper(),'password':'TestPassword2026!','name':'bot'},format='json')
        self.assertEqual(result.status_code,201,result.data)
        secret=result.data['access_token']; token=ApiToken.objects.get()
        self.assertEqual(token.digest,hashlib.sha256(secret.encode()).hexdigest())
        self.assertNotIn(secret,list(token.__dict__.values()))
        self.assertNotIn('sessionid',result.cookies)
        self.assertEqual(result['Cache-Control'],'no-store')
        self.authorize(secret)
        listed=self.client.get('/api/v1/auth/tokens')
        self.assertEqual(listed.status_code,200)
        self.assertNotIn(secret,json.dumps(listed.data))
        self.assertNotIn('digest',listed.data[0])
        self.assertEqual(self.client.get('/api/v1/account').data['user']['id'],self.user.pk)

    def test_failed_credentials_do_not_reveal_account_existence(self):
        existing=self.client.post('/api/v1/auth/token',{'login':self.user.email,'password':'bad'},format='json')
        missing=self.client.post('/api/v1/auth/token',{'login':'missing@example.ru','password':'bad'},format='json')
        self.assertEqual(existing.status_code,401)
        self.assertEqual(existing.data,missing.data)
        self.assertIn('Bearer',existing['WWW-Authenticate'])
        self.assertEqual(ApiToken.objects.count(),0)

    def test_inactive_account_cannot_issue_or_use_tokens(self):
        _,secret=self.token();self.user.is_active=False;self.user.save(update_fields=['is_active'])
        result=self.client.post('/api/v1/auth/token',{'login':self.user.email,'password':'TestPassword2026!'},format='json')
        self.assertEqual(result.status_code,401)
        self.authorize(secret)
        self.assertEqual(self.client.get('/api/v1/account').status_code,401)

    def test_token_expiration_and_revocation(self):
        token,secret=self.token();self.authorize(secret)
        ApiToken.objects.filter(pk=token.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.client.get('/api/v1/account').status_code,401)
        _,secret=self.token();self.authorize(secret)
        self.assertEqual(self.client.delete('/api/v1/auth/tokens/current').status_code,200)
        self.assertEqual(self.client.get('/api/v1/account').status_code,401)

    def test_password_change_invalidates_all_tokens_without_storing_password(self):
        _,first=self.token();_,second=self.token();self.authorize(first)
        changed=self.client.post('/api/v1/account/password',{'current_password':'TestPassword2026!','new_password':'ReplacementPassword2026!','confirm_password':'ReplacementPassword2026!'},format='json')
        self.assertEqual(changed.status_code,200,changed.data)
        for secret in [first,second]:
            self.authorize(secret)
            self.assertEqual(self.client.get('/api/v1/account').status_code,401)
        self.assertFalse(ApiToken.objects.filter(password_stamp='ReplacementPassword2026!').exists())

    def test_read_only_token_blocks_writes_but_can_revoke_itself(self):
        _,secret=self.token(read_only=True);self.authorize(secret)
        self.assertEqual(self.client.get('/api/v1/account').status_code,200)
        self.assertEqual(self.client.patch('/api/v1/account',{'name':'Нельзя'},format='json').status_code,403)
        self.user.refresh_from_db();self.assertEqual(self.user.name,'Проверка API')
        self.assertEqual(self.client.delete('/api/v1/auth/tokens/current').status_code,200)

    def test_token_management_is_owner_scoped_and_creation_requires_password(self):
        foreign,_=self.token(self.other)
        _,secret=self.token();self.authorize(secret)
        self.assertEqual(self.client.delete('/api/v1/auth/tokens/'+str(foreign.pk)).status_code,404)
        self.assertNotIn(str(foreign.pk),[item['id'] for item in self.client.get('/api/v1/auth/tokens').data])
        self.assertEqual(self.client.post('/api/v1/auth/tokens',{'name':'bad'},format='json').status_code,400)
        created=self.client.post('/api/v1/auth/tokens',{'password':'TestPassword2026!','read_only':True},format='json')
        self.assertEqual(created.status_code,201)
        self.assertEqual(ApiToken.objects.get(pk=created.data['token']['id']).user_id,self.user.pk)

    def test_bad_authorization_does_not_fall_back_to_a_valid_cookie(self):
        self.client.force_login(self.user)
        for value in ['Bearer invalid','Basic abc','Bearer','Bearer a b']:
            self.client.credentials(HTTP_AUTHORIZATION=value)
            self.assertEqual(self.client.get('/api/v1/account').status_code,401)

    def test_query_string_token_is_not_authentication(self):
        _,secret=self.token()
        self.assertEqual(self.client.get('/api/v1/account',{'access_token':secret}).status_code,401)

    def test_session_csrf_remains_enforced_and_legacy_api_does_not_accept_bearer(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.patch('/api/v1/account',{'name':'Нельзя без CSRF'},format='json').status_code,403)
        self.client.logout();_,secret=self.token();self.authorize(secret)
        self.assertEqual(self.client.get('/api/account').status_code,403)
        self.assertEqual(self.client.patch('/api/v1/account',{'name':'Можно по токену'},format='json').status_code,200)

    def test_token_does_not_freeze_old_roles(self):
        self.user.roles=['admin'];self.user.save(update_fields=['roles'])
        _,secret=self.token();self.authorize(secret)
        self.assertEqual(self.client.get('/api/v1/users').status_code,200)
        self.user.roles=['teacher'];self.user.save(update_fields=['roles'])
        self.assertEqual(self.client.get('/api/v1/users').status_code,403)

    def test_input_limits_and_password_attempt_throttling(self):
        for value in [0,91,True,'30']:
            result=self.client.post('/api/v1/auth/token',{'login':self.user.email,'password':'TestPassword2026!','expires_in_days':value},format='json')
            self.assertEqual(result.status_code,400)
        for _ in range(16):
            result=self.client.post('/api/v1/auth/token',{'login':self.user.email,'password':'bad'},format='json')
        self.assertEqual(result.status_code,429)
        self.assertIn('Retry-After',result)

    def test_active_token_limit(self):
        for _ in range(20):self.token()
        result=self.client.post('/api/v1/auth/token',{'login':self.user.email,'password':'TestPassword2026!'},format='json')
        self.assertEqual(result.status_code,400)
        self.assertEqual(ApiToken.objects.count(),20)

    def test_password_change_between_verification_and_issue_cannot_create_a_new_token(self):
        from rest_framework.exceptions import AuthenticationFailed
        stale=User.objects.get(pk=self.user.pk)
        self.user.set_password('ReplacementPassword2026!');self.user.save(update_fields=['password'])
        with self.assertRaises(AuthenticationFailed):create_token(stale,{})
        self.assertEqual(ApiToken.objects.count(),0)


class DocumentationRepresentationsTests(SimpleTestCase):
    def test_human_and_robot_guides_have_the_same_sections_and_shared_rules(self):
        for roles in [['student'],['teacher'],['analyst'],['admin'],['teacher','student']]:
            with self.subTest(roles=roles):
                user=SimpleNamespace(roles=roles)
                human=documentation_for(user,audience='human',demo=True)
                robot=documentation_for(user,audience='robot',demo=True)
                self.assertEqual({s['id'] for s in human['sections']},{s['id'] for s in robot['sections']})
                by_id={section['id']:section for section in human['sections']}
                self.assertEqual(robot['sections'][0]['id'],'robot-required-rules')
                for right in robot['sections']:
                    left=by_id[right['id']]
                    self.assertEqual(len(left['blocks']),len(right['blocks']))
                    for a,b in zip(left['blocks'],right['blocks']):
                        for field in ['paragraphs','bullets','formula','table','note']:
                            self.assertEqual(a.get(field),b.get(field))
                    self.assertEqual(right['links'],[])
                    self.assertTrue(right['operations'])

    def test_markdown_has_real_api_procedures_and_no_interface_links(self):
        catalogue=documentation_for(SimpleNamespace(roles=['teacher']),audience='robot',demo=True)
        text=markdown_documentation(catalogue)
        self.assertIn('PATCH /api/v1/worksheet-documents/{pk}',text)
        self.assertIn('Authorization: Bearer',text)
        self.assertIn('уникальные пары',text.lower())
        self.assertNotIn('](#/worksheets)',text)
        self.assertNotIn('Пользователи, роли и доступ аналитика',text)
        self.assertIn('версия 1',text)

    def test_schema_matches_routes_and_filters_admin_and_student_capabilities(self):
        for roles in [['student'],['teacher'],['analyst'],['admin']]:
            user=SimpleNamespace(roles=roles)
            schema=schema_for(user,demo=True)
            self.assertEqual(schema['openapi'],'3.1.0')
            ids=[]
            for path,methods in schema['paths'].items():
                route='/api/v1'+path
                for name in __import__('re').findall(r'\{([^}]+)\}',route):
                    route=route.replace('{'+name+'}', '1' if name in {'student_id','issue_id'} else '00000000-0000-0000-0000-000000000001' if name in {'pk','problem_id'} else 'problem' if name=='kind' else 'pdf' if name=='file_kind' else 'account' if name=='section_id' else 'example-invite')
                resolve(route)
                ids.extend(value['operationId'] for value in methods.values())
            self.assertEqual(len(ids),len(set(ids)))
            self.assertEqual('userList' in ids,'admin' in roles)
            self.assertEqual('myMaterials' in ids,'student' in roles)
            self.assertEqual('journalMark' in ids,bool(set(roles)&{'teacher','admin'}))

    def test_read_only_schema_excludes_writes_and_demo_mailbox_is_conditional(self):
        user=SimpleNamespace(roles=['admin'])
        operations=operations_for(user,demo=False,read_only=True)
        self.assertNotIn('demoMailbox',[op['id'] for op in operations])
        self.assertTrue(all(op['method']=='GET' or op['id'] in {'tokenIssue','tokenRevokeCurrent','problemSearchText'} for op in operations))

    def test_versioned_urls_preserve_types_and_already_versioned_paths(self):
        data={'pdf_url':'/api/materials/worksheet/id/pdf?solutions=1','url':'/api/v1','statement':'/api/task-text','list':[True,12,None,'/api/v1/account'],'external':'https://example.com/api/file'}
        result=versioned_urls(data)
        self.assertEqual(result['pdf_url'],'/api/v1/materials/worksheet/id/pdf?solutions=1')
        self.assertEqual(result['url'],'/api/v1')
        self.assertEqual(result['statement'],'/api/task-text')
        self.assertEqual(result['list'],data['list']);self.assertEqual(result['external'],data['external'])

    def test_restore_revokes_api_tokens_and_accepts_older_backups(self):
        from .backup import revoke_restored_api_tokens
        db=sqlite3.connect(':memory:')
        revoke_restored_api_tokens(db)
        db.execute('CREATE TABLE core_apitoken (id INTEGER PRIMARY KEY, revoked_at TEXT)')
        db.execute('INSERT INTO core_apitoken VALUES (1,NULL)')
        db.execute("INSERT INTO core_apitoken VALUES (2,'already-revoked')")
        revoke_restored_api_tokens(db)
        self.assertIsNotNone(db.execute('SELECT revoked_at FROM core_apitoken WHERE id=1').fetchone()[0])
        self.assertEqual(db.execute('SELECT revoked_at FROM core_apitoken WHERE id=2').fetchone()[0],'already-revoked')
        db.close()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ApiWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo',verbosity=0)
        cls.teacher=User.objects.get(email='teacher@plusfolio.example')
        cls.student=User.objects.get(email='student@plusfolio.example')
        cls.analyst=User.objects.get(email='analyst@plusfolio.example')
        cls.circle=Circle.objects.get(name='Математическая мастерская')
        cls.foreign=Circle.objects.get(name='Геометрия в деталях')
        cls.source=cls.circle.issues.first().worksheet

    def client_for(self,user,**options):
        client=APIClient(enforce_csrf_checks=True)
        _,secret=create_token(user,options)
        client.credentials(HTTP_AUTHORIZATION='Bearer '+secret)
        return client

    def test_copy_edit_issue_mark_export_workflow_uses_real_domain_rules(self):
        client=self.client_for(self.teacher)
        copied=client.post(f'/api/v1/worksheets/{self.source.pk}/copy',{},format='json')
        self.assertEqual(copied.status_code,201,copied.data)
        changed=client.patch('/api/v1/worksheet-documents/'+copied.data['document_id'],{'version':1,'title':'Листок из API'},format='json')
        self.assertEqual(changed.status_code,200,changed.data)
        self.assertEqual(changed.data['revision'],2)
        self.assertEqual(client.patch('/api/v1/worksheet-documents/'+copied.data['document_id'],{'version':1,'title':'Конфликт'},format='json').status_code,409)
        issued=client.post(f'/api/v1/circles/{self.circle.pk}/issues',{'worksheet_ids':[changed.data['id']],'issued_on':timezone.localdate().isoformat()},format='json')
        self.assertEqual(issued.status_code,200,issued.data)
        issue=next(item for item in issued.data if item['document_id']==copied.data['document_id'])
        self.assertTrue(json.loads(issued.content)[0]['pdf_url'].startswith('/api/v1/'))
        journal=client.get(f'/api/v1/circles/{self.circle.pk}/journal',{'issues':issue['id']}).data
        pid=journal['blocks'][0]['problems'][0]['id'];sid=journal['people'][0]['id']
        version=next((state['version'] for state in journal['solves'] if state['problem_id']==pid and state['student_id']==sid),0)
        marked=client.post(f'/api/v1/circles/{self.circle.pk}/problems/{pid}/solve',{'student_id':sid,'value':True,'version':version},format='json')
        self.assertEqual(marked.status_code,200,marked.data)
        exported=client.get(f'/api/v1/circles/{self.circle.pk}/journal/export',{'issues':issue['id'],'file_format':'tsv'})
        self.assertEqual(exported.status_code,200)
        self.assertIn('Листок из API',exported.content.decode())
        self.assertEqual(client.post(f'/api/v1/circles/{self.circle.pk}/issues',{'worksheet_ids':[changed.data['id']],'issued_on':timezone.localdate().isoformat()},format='json').status_code,400)

    def test_student_and_analyst_cannot_write_journal_or_browse_foreign_data(self):
        problem=self.source.items.first().problem
        for user in [self.student,self.analyst]:
            client=self.client_for(user)
            self.assertEqual(client.get(f'/api/v1/circles/{self.foreign.pk}').status_code,404)
            self.assertEqual(client.post(f'/api/v1/circles/{self.circle.pk}/problems/{problem.pk}/discussion',{'value':True,'version':0},format='json').status_code,403)

    def test_revoked_teaching_assignment_takes_effect_for_existing_token(self):
        client=self.client_for(self.teacher)
        CircleTeacher.objects.filter(circle=self.circle,teacher__user=self.teacher,ended_at=None).update(ended_at=timezone.now())
        self.assertEqual(client.get(f'/api/v1/circles/{self.circle.pk}').status_code,404)

    def test_robot_documentation_and_markdown_do_not_leak_admin_guides(self):
        client=self.client_for(self.student)
        result=client.get('/api/v1/documentation')
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.data['audience'],'robot')
        self.assertEqual(json.loads(client.get('/api/v1/openapi.json').content)['servers'][0]['url'],'/api/v1')
        self.assertNotIn('users-and-roles',[s['id'] for s in result.data['sections']])
        self.assertEqual(client.get('/api/v1/documentation/invitations').status_code,404)
        markdown=client.get('/api/v1/documentation',{'download':'markdown'})
        self.assertEqual(markdown.status_code,200)
        self.assertTrue(markdown['Content-Type'].startswith('text/markdown'))
        self.assertNotIn('PATCH /api/v1/users',markdown.content.decode())
        self.assertEqual(client.get('/api/v1/documentation',{'audience':'invalid'}).status_code,400)

    def test_student_solution_visibility_cannot_be_bypassed_through_api(self):
        problem=self.source.items.first().problem
        Discussion.objects.filter(problem=problem).update(discussed=False,solution_visible=False)
        client=self.client_for(self.student)
        hidden=client.get(f'/api/v1/my-problems/{problem.pk}')
        self.assertEqual(hidden.status_code,200)
        self.assertNotIn('solution',hidden.data)
        Discussion.objects.update_or_create(circle=self.circle,problem=problem,defaults={'discussed':True,'solution_visible':True,'changed_by':self.teacher})
        shown=client.get(f'/api/v1/my-problems/{problem.pk}')
        self.assertIn('solution',shown.data)

    def test_existing_recipient_accepts_invitation_with_own_bearer(self):
        from . import services as s
        invitation=s.invite(self.teacher,self.student.email,'student',self.circle)
        token=json.loads(s.cipher().decrypt(invitation.letters.get().encrypted_payload.encode()))['token']
        anonymous=APIClient(enforce_csrf_checks=True)
        self.assertEqual(anonymous.get('/api/v1/accept/'+token).status_code,200)
        self.assertEqual(anonymous.post('/api/v1/accept/'+token,{},format='json').status_code,403)
        accepted=self.client_for(self.student).post('/api/v1/accept/'+token,{},format='json')
        self.assertEqual(accepted.status_code,200,accepted.data)
        self.assertNotIn('sessionid',accepted.cookies)
        self.assertNotIn('access_token',accepted.data)
        self.assertEqual(self.client_for(self.student).post('/api/v1/accept/'+token,{},format='json').status_code,400)

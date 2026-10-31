from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from .documentation import documentation_for
from .models import User


class DocumentationContentTests(SimpleTestCase):
    def catalogue(self, *roles, demo=True):
        return documentation_for(SimpleNamespace(roles=list(roles)), demo=demo)['sections']

    def ids(self, *roles):
        return {section['id'] for section in self.catalogue(*roles)}

    def test_student_receives_only_reading_and_personal_workflows(self):
        ids = self.ids('student')
        self.assertTrue({'getting-started', 'account', 'my-materials',
                         'circle-journal', 'pdf-documents', 'analytics', 'journal-export'} <= ids)
        self.assertTrue(ids.isdisjoint({'invitations', 'journal-editing', 'circle-members',
                                      'problem-library', 'problem-creation', 'worksheet-creation',
                                      'worksheet-issue', 'worksheet-copies', 'tex-sources', 'api-authentication', 'api-tokens', 'users-and-roles',
                                      'circle-administration', 'worksheet-publication', 'tags-and-topics'}))

    def test_teacher_receives_writing_but_no_administration(self):
        ids = self.ids('teacher')
        self.assertTrue({'journal-editing', 'circle-members', 'problem-library',
                         'problem-creation', 'worksheet-creation', 'worksheet-issue',
                         'tex-sources', 'invitations'} <= ids)
        self.assertTrue(ids.isdisjoint({'my-materials', 'users-and-roles', 'circle-administration',
                                      'worksheet-publication', 'tags-and-topics'}))

    def test_analyst_cannot_receive_teaching_workflows(self):
        ids = self.ids('analyst')
        self.assertTrue({'problem-library', 'analytics', 'invitations', 'worksheet-copies'} <= ids)
        self.assertTrue(ids.isdisjoint({'my-materials', 'journal-editing', 'circle-members',
                                      'problem-creation', 'worksheet-creation', 'worksheet-issue',
                                      'tex-sources', 'users-and-roles'}))

    def test_admin_receives_administration_but_not_student_only_navigation(self):
        ids = self.ids('admin')
        self.assertTrue({'users-and-roles', 'circle-administration', 'worksheet-publication',
                         'tags-and-topics', 'journal-editing', 'tex-sources'} <= ids)
        self.assertNotIn('my-materials', ids)

    def test_multiple_roles_combine_guides(self):
        self.assertEqual(self.ids('teacher', 'student'), self.ids('teacher') | self.ids('student'))
        self.assertEqual(self.ids('teacher', 'analyst'), self.ids('teacher') | self.ids('analyst'))
        self.assertEqual(self.ids('admin', 'student'), self.ids('admin') | self.ids('student'))

    def test_invitation_instructions_follow_sender_roles_and_demo_mode(self):
        teacher = next(s for s in self.catalogue('teacher') if s['id'] == 'invitations')
        analyst = next(s for s in self.catalogue('analyst') if s['id'] == 'invitations')
        admin = next(s for s in self.catalogue('admin') if s['id'] == 'invitations')
        self.assertEqual(len(teacher['blocks'][0]['bullets']), 1)
        self.assertIn('Школьник —', teacher['blocks'][0]['bullets'][0])
        self.assertNotIn('или преподавателя', teacher['blocks'][1]['steps'][1])
        self.assertIn('преподаватель', analyst['blocks'][0]['bullets'][0])
        self.assertIn('Администратор', admin['blocks'][0]['bullets'][-1])
        self.assertTrue(any(b['title'] == 'Как проверить письмо в демо' for b in teacher['blocks']))
        production = next(s for s in self.catalogue('teacher', demo=False) if s['id'] == 'invitations')
        self.assertFalse(any(b['title'] == 'Как проверить письмо в демо' for b in production['blocks']))

    def test_all_guide_ids_are_unique_and_links_match_permissions(self):
        for roles in [('student',), ('teacher',), ('analyst',), ('admin',), ('teacher', 'student')]:
            with self.subTest(roles=roles):
                sections = self.catalogue(*roles)
                self.assertEqual(len(sections), len({s['id'] for s in sections}))
                for section in sections:
                    self.assertTrue(section['title'] and section['summary'] and section['blocks'])
                    for link in section['links']:
                        self.assertTrue(link['href'].startswith('/'))
                        if link['href'] in ['/users', '/tags']:
                            self.assertIn('admin', roles)
                        if link['href'] in ['/problems', '/topics']:
                            self.assertTrue(set(roles) & {'admin', 'teacher', 'analyst'})
                        if link['href'] == '/invitations':
                            self.assertTrue(set(roles) & {'admin', 'teacher', 'analyst'})

    def test_role_specific_text_does_not_leak_between_requests(self):
        documentation_for(SimpleNamespace(roles=['admin', 'student']), demo=True)
        sections = self.catalogue('analyst')
        account = next(s for s in sections if s['id'] == 'account')
        self.assertFalse(any(b['title'] == 'ФИО и текущий класс' for b in account['blocks']))


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DocumentationApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('docs@plusfolio.example', 'unused', name='Тест документации', roles=['student'])
        self.client = APIClient()

    def test_login_is_required(self):
        self.assertEqual(self.client.get('/api/documentation').status_code, 403)

    def test_api_filters_content_and_ignores_role_parameters(self):
        self.client.force_login(self.user)
        response = self.client.get('/api/documentation?role=admin&roles=admin')
        self.assertEqual(response.status_code, 200)
        ids = {section['id'] for section in response.data['sections']}
        self.assertIn('my-materials', ids)
        self.assertNotIn('users-and-roles', ids)
        self.assertNotIn('invitations', ids)
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_article_cannot_be_opened_outside_current_access(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/api/documentation/my-materials').status_code, 200)
        hidden = self.client.get('/api/documentation/users-and-roles')
        missing = self.client.get('/api/documentation/nonexistent')
        self.assertEqual(hidden.status_code, 404)
        self.assertEqual(hidden.data, missing.data)

    def test_role_change_is_applied_on_next_request(self):
        self.client.force_login(self.user)
        self.user.roles = ['admin']
        self.user.save(update_fields=['roles'])
        self.assertEqual(self.client.get('/api/documentation/users-and-roles').status_code, 200)
        self.user.roles = ['student']
        self.user.save(update_fields=['roles'])
        self.assertEqual(self.client.get('/api/documentation/users-and-roles').status_code, 404)

    def test_documentation_is_read_only(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post('/api/documentation', {}, format='json').status_code, 405)

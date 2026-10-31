from types import SimpleNamespace
from uuid import UUID
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient
from .documentation import documentation_for
from .documentation_export import markdown_documentation
from .api_reference import schema_for
from .robot_workflows import RULES_ID, UPLOAD_ID, POLICY_VERSION
from .test_api_reference import assert_contract
from .models import User, Topic, Tag


class MandatoryWorkflowTests(SimpleTestCase):
    def test_manifest_and_first_sections_follow_roles_and_token_mode(self):
        for roles in [['student'],['analyst'],['teacher'],['admin'],['student','teacher']]:
            for read_only in [False,True]:
                with self.subTest(roles=roles,read_only=read_only):
                    user=SimpleNamespace(roles=roles)
                    data=documentation_for(user,audience='robot',read_only=read_only)
                    if roles==['student']:
                        self.assertEqual(data['mandatory_instructions'],[])
                        self.assertEqual(data['audience'],'human')
                        continue
                    self.assertEqual(data['sections'][0]['id'],RULES_ID)
                    self.assertEqual(data['instruction_policy_version'],POLICY_VERSION)
                    required={item['section_id']:item for item in data['mandatory_instructions']}
                    writer=bool({'teacher','admin'}&set(roles))
                    self.assertEqual(UPLOAD_ID in required,writer)
                    if writer:
                        self.assertEqual(data['sections'][1]['id'],UPLOAD_ID)
                        self.assertEqual(required[UPLOAD_ID]['can_execute'],not read_only)
                    for item in required.values():
                        self.assertTrue(item['required'])
                        self.assertIn(item['section_id'],[s['id'] for s in data['sections']])

    def test_protocol_prescribes_questions_and_real_ids_without_unavailable_admin_calls(self):
        for role in ['teacher','admin']:
            data=documentation_for(SimpleNamespace(roles=[role]),audience='robot')
            section=next(s for s in data['sections'] if s['id']==UPLOAD_ID)
            titles=[block['title'].split('.')[0] for block in section['blocks']]
            for step in range(9):self.assertIn('S'+str(step),titles)
            protocol=' '.join(item for block in section['blocks'] for item in block.get('steps',[]))
            for value in ['дополнительный вопрос','public_id','document_id','HTTP 201','reuse','kind=worksheet']:
                self.assertIn(value,protocol)
            operations={item['id'] for item in section['operations']}
            self.assertEqual('topicCreate' in operations,role=='admin')
            self.assertEqual('tagCreate' in operations,role=='admin')
            self.assertIn('materialCreate',operations)
            self.assertIn('worksheetGet',operations)

    def test_mandatory_policy_is_exported_before_other_guides_and_in_openapi(self):
        user=SimpleNamespace(roles=['teacher'])
        data=documentation_for(user,audience='robot')
        text=markdown_documentation(data)
        self.assertLess(text.index('MUST: обязательные инструкции'),text.index('Как устроен Plusfolio'))
        self.assertIn('/api/v1/documentation/'+UPLOAD_ID+'?audience=robot',text)
        spec=schema_for(user,read_only=True)
        writable=schema_for(user)
        self.assertIn('/api/v1/documentation/'+UPLOAD_ID,writable['paths']['/materials/{kind}']['post']['description'])
        manifest=spec['x-plusfolio-mandatory-instructions']
        self.assertEqual(manifest['policy_version'],POLICY_VERSION)
        self.assertFalse(next(item for item in manifest['instructions'] if item['section_id']==UPLOAD_ID)['can_execute'])
        assert_contract({'$ref':'#/components/schemas/OpenAPI'},spec,spec['components']['schemas'])
        assert_contract({'$ref':'#/components/schemas/GuideCatalogue'},data,spec['components']['schemas'])


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class UploadIdentifierContractTests(TestCase):
    def test_both_create_responses_return_the_ids_required_by_the_workflow(self):
        teacher=User.objects.create_user('upload@plusfolio.example','unused',name='Проверка загрузки',roles=['teacher'])
        root=Topic.objects.create(name='Все темы')
        topic=Topic.objects.create(name='Алгебра',parent=root)
        problem_tag=Tag.objects.create(kind='problem',name='Проверочный тег задачи')
        worksheet_tag=Tag.objects.create(kind='worksheet',name='Проверочный тег листка')
        client=APIClient();client.force_authenticate(user=teacher)
        problem=client.post('/api/v1/materials/problem',{
            'statement':'Докажите, что сумма двух чётных чисел чётна.',
            'solution':'Числа равны 2a и 2b, сумма равна 2(a+b).',
            'topics':[str(topic.pk)],'tags':[problem_tag.pk]},format='json')
        self.assertEqual(problem.status_code,201)
        UUID(problem.data['id'])
        self.assertEqual(problem.data['public_id'],'P-'+str(problem.data['number']))
        worksheet=client.post('/api/v1/materials/worksheet',{
            'title':'Подтверждённый листок','description':'Подтверждённое описание',
            'topics':[str(topic.pk)],'tags':[worksheet_tag.pk],'problems':[problem.data['id']]},format='json')
        self.assertEqual(worksheet.status_code,201)
        for field in ['document_id','id']:UUID(worksheet.data[field])
        self.assertTrue(worksheet.data['public_id'].startswith('W-'))
        self.assertEqual(worksheet.data['revision'],1)
        self.assertFalse(worksheet.data['is_public'])
        check=client.get('/api/v1/worksheet-documents/'+worksheet.data['document_id'])
        self.assertEqual(check.status_code,200)
        self.assertEqual(check.data['problem_ids'],[problem.data['id']])

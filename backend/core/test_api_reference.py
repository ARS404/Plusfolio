"""Check published contracts against representative real API replies, without live data."""
import json
from types import SimpleNamespace
from uuid import UUID

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from .api_contract import operations_for
from .api_reference import schema_for

from .models import Circle, User


def assert_contract(schema, value, definitions, path='$'):
    if '$ref' in schema:
        schema={**definitions[schema['$ref'].rsplit('/',1)[-1]],**{key:item for key,item in schema.items() if key!='$ref'}}
    variants=schema.get('anyOf',schema.get('oneOf'))
    if variants:
        errors=[]
        for variant in variants:
            try:assert_contract(variant,value,definitions,path);return
            except AssertionError as error:errors.append(str(error))
        raise AssertionError(path+': не соответствует ни одному варианту: '+'; '.join(errors))
    kind=schema.get('type')
    if isinstance(kind,list):
        return assert_contract({'anyOf':[{**schema,'type':item} for item in kind]},value,definitions,path)
    if kind=='null':
        assert value is None,path+': ожидался null'
    elif kind=='object':
        assert isinstance(value,dict),path+': ожидался объект'
        properties=schema.get('properties',{})
        assert set(schema.get('required',[]))<=set(value),path+': отсутствуют обязательные поля'
        if properties and schema.get('additionalProperties') is not True:
            assert set(value)<=set(properties),path+': неописанные поля '+','.join(set(value)-set(properties))
        for name,item in value.items():
            if name in properties:assert_contract(properties[name],item,definitions,path+'.'+name)
    elif kind=='array':
        assert isinstance(value,list),path+': ожидался массив'
        for index,item in enumerate(value):assert_contract(schema.get('items',{}),item,definitions,path+f'[{index}]')
    elif kind=='integer':
        assert type(value) is int,path+': ожидалось целое число'
    elif kind=='number':
        assert type(value) in {int,float},path+': ожидалось число'
    elif kind=='boolean':
        assert type(value) is bool,path+': ожидалось логическое значение'
    elif kind=='string':
        assert isinstance(value,str),path+': ожидалась строка'
        if schema.get('format')=='uuid':
            try:UUID(value)
            except (ValueError,AttributeError):raise AssertionError(path+': ожидался UUID')
    if 'enum' in schema:assert value in schema['enum'],path+': значение вне enum'
    if 'const' in schema:assert value==schema['const'],path+': значение не совпадает с const'


class ReferenceSchemaTests(SimpleTestCase):
    def test_every_documented_success_has_a_nonempty_shape_and_all_references_resolve(self):
        for roles in [['student'],['teacher'],['analyst'],['admin']]:
            with self.subTest(roles=roles):
                schema=schema_for(SimpleNamespace(roles=roles),demo=True)
                definitions=schema['components']['schemas']
                def check(value):
                    if isinstance(value,dict):
                        if '$ref' in value:self.assertIn(value['$ref'].rsplit('/',1)[-1],definitions)
                        for item in value.values():check(item)
                    elif isinstance(value,list):
                        for item in value:check(item)
                check(schema)
                for methods in schema['paths'].values():
                    for operation in methods.values():
                        self.assertGreater(len(operation['description']),30)
                        successes=[response for status,response in operation['responses'].items() if status.startswith('2')]
                        self.assertTrue(successes)
                        for response in successes:
                            for media in response['content'].values():self.assertTrue(media['schema'])

    def test_response_shapes_are_filtered_with_operations_and_do_not_change_routes(self):
        user=SimpleNamespace(roles=['student'])
        schema=schema_for(user,demo=True)
        self.assertNotIn('/users',schema['paths'])
        self.assertNotIn('/invitations',schema['paths'])
        self.assertNotIn('UsersList',schema['components']['schemas'])
        declared={operation['id'] for operation in operations_for(user,demo=True)}
        self.assertEqual(declared,{operation['operationId'] for methods in schema['paths'].values() for operation in methods.values()})

    def test_request_fields_have_readable_descriptions_and_secret_markers(self):
        schema=schema_for(SimpleNamespace(roles=['admin']),demo=True)
        body=schema['paths']['/auth/token']['post']['requestBody']['content']['application/json']['schema']
        self.assertTrue(body['properties']['password']['writeOnly'])
        self.assertIn('Email',body['properties']['login']['description'])
        fields=schema['paths']['/worksheet-documents/{pk}']['patch']['requestBody']['content']['application/json']['schema']['properties']
        self.assertIn('дополнительное описание',fields['description']['description'])
        self.assertIn('UUID задач',fields['problems']['description'])
        self.assertNotEqual(fields['title']['description'],fields['description']['description'])
        parameter=schema['paths']['/worksheet-documents/{pk}']['patch']['parameters'][0]
        self.assertIn('document_id',parameter['description'])
        self.assertEqual(schema['externalDocs']['url'],'/#/documentation/api')


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ActualResponseContractsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo',verbosity=0)
        cls.teacher=User.objects.get(email='teacher@plusfolio.example')
        cls.student=User.objects.get(email='student@plusfolio.example')
        cls.admin=User.objects.get(email='admin@plusfolio.example')
        cls.circle=Circle.objects.get(name='Математическая мастерская')
        cls.issue=cls.circle.issues.first()
        cls.problem=cls.issue.worksheet.items.first().problem

    def client_for(self,user):
        client=APIClient();client.force_authenticate(user=user);return client

    def check_reply(self,user,path,method='get',body=None):
        client=self.client_for(user)
        spec=client.get('/api/v1/openapi.json').json()
        # Resolve the route's operation ID without depending on incidental UUID values.
        from django.urls import resolve
        matched=resolve(path.split('?')[0])
        from .api_contract import ROUTES
        registry=next(methods for pattern,view,methods in ROUTES if pattern==matched.route.split('api/v1/',1)[1])
        operation_id=registry[method.upper()]['id']
        op=next(operation for methods in spec['paths'].values() for operation in methods.values() if operation['operationId']==operation_id)
        result=getattr(client,method)(path,body,format='json') if body is not None else getattr(client,method)(path)
        self.assertIn(result.status_code,[200,201])
        shape=op['responses'][str(result.status_code)]['content']['application/json']['schema']
        assert_contract(shape,json.loads(result.content),spec['components']['schemas'])
        return result.json()

    def test_profiles_people_circles_and_topics_follow_published_shapes(self):
        for user in [self.teacher,self.student,self.admin]:
            for path in ['/api/v1/account','/api/v1/circles',f'/api/v1/circles/{self.circle.pk}',f'/api/v1/circles/{self.circle.pk}/members','/api/v1/topics','/api/v1/tags']:
                with self.subTest(user=user.roles,path=path):self.check_reply(user,path)
        self.check_reply(self.admin,'/api/v1/users')
        self.check_reply(self.admin,'/api/v1/users?meta=1')
        self.check_reply(self.teacher,f'/api/v1/circles/{self.circle.pk}/student-search?q=S-{self.student.student.pk}')

    def test_material_variants_and_fixed_issues_follow_published_shapes(self):
        for user in [self.teacher,self.student]:
            for path in [f'/api/v1/materials/problem/{self.problem.pk}',f'/api/v1/materials/worksheet/{self.issue.worksheet_id}',f'/api/v1/circles/{self.circle.pk}/issues',f'/api/v1/circles/{self.circle.pk}/issues/{self.issue.pk}']:
                with self.subTest(path=path):self.check_reply(user,path)
        for path in ['/api/v1/materials/problem','/api/v1/materials/problem?pagination=1','/api/v1/materials/worksheet',f'/api/v1/worksheet-documents/{self.issue.document_id}']:
            self.check_reply(self.teacher,path)
        for path in ['/api/v1/my-materials/problem','/api/v1/my-materials/worksheet',f'/api/v1/my-issues/{self.issue.pk}',f'/api/v1/my-problems/{self.problem.pk}']:
            self.check_reply(self.student,path)

    def test_journal_analytics_and_documentation_follow_published_shapes(self):
        for user in [self.teacher,self.student]:
            for path in [f'/api/v1/circles/{self.circle.pk}/journal',f'/api/v1/circles/{self.circle.pk}/journal/{self.issue.pk}','/api/v1/analytics','/api/v1/documentation','/api/v1/documentation/worksheet-copies']:
                with self.subTest(user=user.roles,path=path):self.check_reply(user,path)
        self.check_reply(self.teacher,f'/api/v1/circles/{self.circle.pk}/audit')
        self.check_reply(self.teacher,'/api/v1/openapi.json')

    def test_copy_and_edition_keep_declared_output_contracts(self):
        copied=self.check_reply(self.teacher,f'/api/v1/worksheets/{self.issue.worksheet_id}/copy','post',{})
        self.check_reply(self.teacher,'/api/v1/worksheet-documents/'+copied['document_id'],'patch',{'version':1,'title':'Проверка контракта'})

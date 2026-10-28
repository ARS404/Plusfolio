from unittest.mock import patch
import numpy as np
from django.core.cache import cache
from django.test import TestCase,override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from .models import User, Topic, Circle, CircleTeacher, Teacher, Enrollment, Student, Problem, Worksheet, WorksheetDocument, CatalogueSearchDocument
from . import catalogue_search as search
from .search import MODEL_ID,EmbeddingUnavailable


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CatalogueSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin=User.objects.create_user('admin@example.test','pass',name='Admin',roles=['admin'])
        cls.teacher=User.objects.create_user('teacher@example.test','pass',name='Teacher',roles=['teacher'])
        cls.other=User.objects.create_user('other@example.test','pass',name='Other',roles=['teacher'])
        cls.student=User.objects.create_user('student@example.test','pass',name='Student',roles=['student'])
        cls.root=Topic.objects.create(name='Все темы')
        cls.topic=Topic.objects.create(name='Принцип крайнего',parent=cls.root)
        cls.child=Topic.objects.create(name='Прочее',parent=cls.topic,is_other=True)
        cls.circle=Circle.objects.create(name='Кружок олимпиад',description='Решаем задачи на максимальные и минимальные элементы',city='Москва',region='Москва',created_by=cls.admin)
        cls.hidden_circle=Circle.objects.create(name='Секретный кружок',description='Секретное описание 98124',city='Казань',created_by=cls.admin)
        CircleTeacher.objects.create(circle=cls.circle,teacher=Teacher.objects.create(user=cls.teacher))
        Enrollment.objects.create(circle=cls.circle,student=Student.objects.create(user=cls.student,graduation_year=2030))
        cls.doc=WorksheetDocument.objects.create(author=cls.teacher)
        cls.sheet=Worksheet.objects.create(document=cls.doc,title='Принцип крайнего',description='Выбираем самый большой элемент',author=cls.teacher,published=True)
        cls.doc.current_revision=cls.sheet;cls.doc.public_revision=cls.sheet;cls.doc.save()
        private=WorksheetDocument.objects.create(author=cls.other)
        cls.hidden=Worksheet.objects.create(document=private,title='Личный секрет 27461',description='Скрытые материалы',author=cls.other,published=True)
        private.current_revision=cls.hidden;private.save()
        cls.problem=Problem.objects.create(author=cls.teacher,published=True,title='Крайние элементы',description='Максимум и минимум',statement='Проверьте число 1729',solution='Решение скрыто')

    def setUp(self):cache.clear()

    def query(self,user,kind,q,**params):
        client=APIClient();client.force_authenticate(user=user)
        return client.get('/api/v1/catalogue-search',{'kind':kind,'q':q,**params})

    def ids(self,response):
        self.assertEqual(response.status_code,200,response.data)
        return [hit['entity']['id'] for hit in response.data['results']]

    def test_idle_reconcile_does_not_load_complete_topic_paths(self):
        search.reconcile()
        with patch('core.catalogue_search.topic_paths', side_effect=AssertionError('No missing topics')):
            search.reconcile()
        Topic.objects.bulk_create([Topic(name='Missing topic',parent=self.root)])
        with patch('core.catalogue_search.topic_paths', wraps=search.topic_paths) as paths:
            search.reconcile()
        self.assertEqual(paths.call_count,1)
        self.assertTrue(CatalogueSearchDocument.objects.filter(kind='topic',text='Missing topic').exists())

    @patch('core.search.query_embedding')
    def test_semantic_metadata_and_scope_before_ranking(self,embedding):
        vector=np.zeros(384,dtype=np.float32);vector[0]=1;embedding.return_value=vector
        CatalogueSearchDocument.objects.all().update(embedding=vector,model=MODEL_ID)
        response=self.query(self.teacher,'circle','поиск вне лексических совпадений')
        self.assertEqual(self.ids(response),[str(self.circle.pk)])
        self.assertTrue(response.data['semantic'])
        self.assertEqual(response.data['pending'],0)
        self.assertNotIn('Секрет',str(response.data))
        response=self.query(self.teacher,'worksheet','поиск вне лексических совпадений',scope='public')
        self.assertEqual(self.ids(response),[str(self.sheet.pk)])
        self.assertNotIn(str(self.hidden.pk),self.ids(response))
        self.assertEqual(self.ids(self.query(self.teacher,'circle','поиск вне лексических совпадений',city='Казань')),[])

    def test_identifier_bypasses_model_and_accepts_document_uuid(self):
        with patch('core.search.query_embedding',side_effect=AssertionError('Model must not run')):
            response=self.query(self.teacher,'worksheet',f'W-{self.doc.number_id}')
            self.assertEqual(self.ids(response),[str(self.sheet.pk)])
            self.assertEqual(response.data['results'][0]['match'],'identifier')
            self.assertEqual(self.ids(self.query(self.teacher,'worksheet',str(self.doc.pk))),[str(self.sheet.pk)])
            self.assertEqual(self.ids(self.query(self.teacher,'worksheet',f'C-{self.circle.number_id}')),[])

    def test_private_revision_and_revocation_do_not_need_reindex(self):
        self.assertEqual(self.ids(self.query(self.teacher,'worksheet',self.hidden.title,mode='text')),[])
        self.assertIn(str(self.hidden.pk),self.ids(self.query(self.admin,'worksheet',self.hidden.title,scope='all',mode='text')))
        self.assertEqual(self.query(self.teacher,'worksheet','личный',scope='all').status_code,403)
        self.assertIn(str(self.circle.pk),self.ids(self.query(self.teacher,'circle',self.circle.name,mode='text')))
        CircleTeacher.objects.filter(circle=self.circle).update(ended_at=timezone.now())
        self.assertEqual(self.ids(self.query(self.teacher,'circle',self.circle.name,mode='text')),[])

    def test_revisions_parent_paths_and_changed_vectors(self):
        vector=np.ones(384,dtype=np.float32)/np.sqrt(384)
        document=CatalogueSearchDocument.objects.get(kind='circle',object_id=self.circle.pk)
        document.embedding=vector;document.model=MODEL_ID;document.save()
        self.circle.description='Новое описание';self.circle.save()
        document.refresh_from_db();self.assertIsNone(document.embedding)
        self.assertIn('Новое описание',document.text)
        self.topic.name='Экстремальный элемент';self.topic.save()
        descendant=CatalogueSearchDocument.objects.get(kind='topic',object_id=self.child.pk)
        self.assertEqual(descendant.text,'Экстремальный элемент / Прочее')
        self.assertIn(str(self.child.pk),self.ids(self.query(self.teacher,'topic','Экстремальный элемент',mode='text')))
        Topic.objects.filter(pk=self.topic.pk).update(name='Bulk rename')
        search.reconcile(rebuild=True)
        descendant.refresh_from_db();self.assertIn('Bulk rename',descendant.text)

    @patch('core.search.query_embedding',side_effect=EmbeddingUnavailable())
    def test_outage_text_and_scoped_pending(self,embedding):
        vector=np.ones(384,dtype=np.float32)/np.sqrt(384)
        CatalogueSearchDocument.objects.filter(kind='circle',object_id=self.circle.pk).update(embedding=vector,model=MODEL_ID)
        response=self.query(self.teacher,'circle','минимальные элементы')
        self.assertIn(str(self.circle.pk),self.ids(response))
        self.assertFalse(response.data['semantic']);self.assertIn('недоступен',response.data['notice'])
        self.assertEqual(response.data['pending'],0)

    @patch('core.search.embed')
    def test_index_job_does_not_overwrite_a_new_fingerprint(self,embed):
        doc=CatalogueSearchDocument.objects.order_by('pk').first()
        def changed(texts,mode):
            CatalogueSearchDocument.objects.filter(pk=doc.pk).update(fingerprint='newer')
            return np.ones((len(texts),384),dtype=np.float32)/np.sqrt(384)
        embed.side_effect=changed;search.index_batch(1);doc.refresh_from_db();self.assertIsNone(doc.embedding)

    def test_task_metadata_field_and_restricted_solution(self):
        client=APIClient();client.force_authenticate(user=self.teacher)
        response=client.get('/api/v1/problem-search',{'q':'Максимум и минимум','field':'metadata','mode':'text'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.data['results'][0]['fields'],['metadata'])
        response=client.get('/api/v1/problem-search',{'q':'Проверьте число','field':'metadata','mode':'text'})
        self.assertEqual(response.data['results'],[])
        client.force_authenticate(user=self.student)
        response=client.get('/api/v1/problem-search',{'q':'Решение скрыто','fields':['metadata','solution'],'mode':'text'})
        self.assertEqual(response.data['results'],[])

    def test_api_schema_read_only_and_validation(self):
        from .authentication import create_token
        from .api_reference import schema_for
        from .test_api_reference import assert_contract
        _,secret=create_token(self.teacher,{'read_only':True})
        client=APIClient();client.credentials(HTTP_AUTHORIZATION='Bearer '+secret)
        response=client.get('/api/v1/catalogue-search',{'kind':'worksheet','q':'крайнего','mode':'text'})
        self.ids(response)
        spec=schema_for(self.teacher,read_only=True)
        contract=spec['paths']['/catalogue-search']['get']['responses']['200']['content']['application/json']['schema']
        assert_contract(contract,response.data,spec['components']['schemas'])
        for params in [{'kind':'user'},{'q':'x'*161},{'limit':'bad'},{'limit':'101'},{'mode':'bad'}]:
            self.assertEqual(self.query(self.teacher,params.get('kind','circle'),params.get('q','test'),**{key:value for key,value in params.items() if key not in {'q','kind'}}).status_code,400)
        self.assertEqual(APIClient().get('/api/v1/catalogue-search',{'kind':'circle','q':'test'}).status_code,401)

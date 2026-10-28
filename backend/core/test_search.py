from unittest import skipUnless
from unittest.mock import patch
import numpy as np
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient
from .models import User, Problem, ProblemSearchDocument, Circle, Discussion
from . import services as s
from .search import MODEL_ID, normalized, reconcile_missing, allowed_documents, index_batch, EmbeddingUnavailable


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo', verbosity=0)
        cls.teacher=User.objects.get(email='teacher@plusfolio.example')
        cls.student=User.objects.get(email='student@plusfolio.example')
        cls.circle=Circle.objects.get(name='Математическая мастерская')
        cls.problem=cls.circle.issues.first().worksheet.items.first().problem
        reconcile_missing()

    def setUp(self):
        cache.clear()

    def client_for(self,user):
        client=APIClient();client.force_authenticate(user=user);return client

    def query(self,user,text,**params):
        return self.client_for(user).get('/api/problem-search',{'q':text,**params})

    def test_exact_copy_and_id_search(self):
        response=self.query(self.teacher,self.problem.statement,mode='text')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.data['results'][0]['problem']['id'],str(self.problem.pk))
        self.assertEqual(response.data['results'][0]['match'],'exact')
        response=self.query(self.teacher,f'P-{self.problem.number_id}')
        self.assertEqual(len(response.data['results']),1)
        self.assertEqual(response.data['results'][0]['match'],'identifier')

    def test_only_permitted_solution_documents_participate_in_ranking(self):
        for user in User.objects.all():
            problems=s.problems_for(user)
            docs=allowed_documents(user,problems,'solution')
            self.assertEqual(set(docs.values_list('problem_id',flat=True)),s.visible_solution_ids(user,list(problems.values_list('pk',flat=True))))

    def test_student_cannot_search_closed_solution_even_by_exact_text(self):
        response=self.query(self.student,self.problem.solution,field='solution',mode='text')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.data['results'],[])
        self.assertEqual(response.data['pending'],0)

    def test_permission_rechecked_after_reveal_and_revoke_without_reindex(self):
        discussion=Discussion.objects.get(circle=self.circle,problem=self.problem)
        discussion.discussed=True;discussion.solution_visible=True;discussion.save()
        response=self.query(self.student,self.problem.solution,field='solution',mode='text')
        self.assertTrue(any(hit['problem']['id']==str(self.problem.pk) for hit in response.data['results']))
        discussion.solution_visible=False;discussion.save()
        self.assertEqual(self.query(self.student,self.problem.solution,field='solution',mode='text').data['results'],[])

    @patch('core.search.query_embedding',side_effect=EmbeddingUnavailable())
    def test_model_outage_falls_back_to_text(self,model):
        vector=np.zeros(384,dtype=np.float32);vector[0]=1
        ProblemSearchDocument.objects.filter(problem=self.problem,kind='statement').update(embedding=vector,model=MODEL_ID)
        response=self.query(self.teacher,self.problem.statement)
        self.assertTrue(response.data['results'])
        self.assertFalse(response.data['semantic'])
        self.assertIn('недоступен',response.data['notice'])

    @patch('core.search.query_embedding')
    def test_semantic_rank_and_solution_visibility(self,embedding):
        vector=np.zeros(384,dtype=np.float32);vector[0]=1;embedding.return_value=vector
        ProblemSearchDocument.objects.filter(problem=self.problem,kind='statement').update(embedding=vector,model=MODEL_ID)
        response=self.query(self.teacher,'невстречающийся запрос для семантического сопоставления',field='statement')
        self.assertTrue(response.data['semantic'])
        self.assertEqual(response.data['results'][0]['match'],'semantic')
        self.assertEqual(response.data['results'][0]['problem']['id'],str(self.problem.pk))
        self.assertEqual(response.data['results'][0]['fields'],['statement'])

    @skipUnless(connection.vendor=='postgresql','PostgreSQL candidate projection')
    def test_postgres_fuzzy_candidates_leave_vectors_and_normalized_text_deferred(self):
        from .search import lexical_candidates
        docs=ProblemSearchDocument.objects.filter(problem=self.problem,kind='statement')
        vector=np.zeros(384,dtype=np.float32);vector[0]=1
        text='Synthetic projection condition'
        docs.update(text=text,normalized=normalized(text).casefold(),embedding=vector,model=MODEL_ID)
        # The typo prevents the exact-substring branch from hiding a fuzzy projection regression.
        with self.assertNumQueries(2):
            candidates=lexical_candidates(docs,'synthetic projection conditon')
        self.assertEqual(len(candidates),1)
        with self.assertNumQueries(0):
            for doc,score,kind in candidates:
                self.assertTrue({'embedding','normalized'}<=doc.get_deferred_fields())
                self.assertEqual((doc.problem_id,doc.kind,doc.text),(self.problem.pk,'statement',text))
                self.assertEqual(kind,'text');self.assertGreaterEqual(score,.08)

    @skipUnless(connection.vendor=='postgresql','PostgreSQL candidate projection')
    def test_postgres_vector_candidates_do_not_fetch_the_vector_or_normalized_text(self):
        from .search import vector_candidates
        docs=ProblemSearchDocument.objects.filter(problem=self.problem,kind='statement')
        vector=np.zeros(384,dtype=np.float32);vector[0]=1
        docs.update(embedding=vector,model=MODEL_ID)
        with CaptureQueriesContext(connection) as queries:
            candidates=vector_candidates(docs,vector,limit=1)
        self.assertEqual(sum(query['sql'].lstrip().upper().startswith('SELECT ') for query in queries),1)
        self.assertEqual(len(candidates),1)
        with self.assertNumQueries(0):
            doc,score=candidates[0]
            self.assertTrue({'embedding','normalized'}<=doc.get_deferred_fields())
            self.assertEqual((doc.problem_id,doc.kind),(self.problem.pk,'statement'))
            self.assertTrue(doc.text);self.assertAlmostEqual(score,1.)

    @patch('core.search.embed')
    def test_index_worker_reads_only_source_and_fingerprint_without_deferred_queries(self,embed):
        from .search import index_documents
        docs=ProblemSearchDocument.objects.filter(problem=self.problem,kind='statement')
        document=docs.get()
        vector=np.zeros(384,dtype=np.float32);vector[0]=1
        docs.update(embedding=vector,model='obsolete-test-model')
        embed.return_value=vector[None,:]
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(index_documents(docs,batch_size=1),1)
        reads=[query['sql'] for query in queries if query['sql'].lstrip().upper().startswith('SELECT ')]
        self.assertEqual(len(reads),1)
        self.assertEqual(len(queries),2)  # One source read and one guarded update.
        projection=reads[0].split(' FROM ',1)[0]
        for field in ['embedding','normalized']:
            self.assertNotIn('."'+field+'"',projection)
        embed.assert_called_once_with([document.text],'document')
        document.refresh_from_db()
        self.assertEqual(document.model,MODEL_ID)
        np.testing.assert_array_equal(np.asarray(document.embedding),vector)

    def test_bulk_recovery_and_idempotence(self):
        ProblemSearchDocument.objects.filter(problem=self.problem).delete()
        reconcile_missing();count=ProblemSearchDocument.objects.count();reconcile_missing()
        self.assertEqual(ProblemSearchDocument.objects.count(),count)
        self.assertEqual(self.problem.search_documents.count(),3)

    @patch('core.search.embed')
    def test_worker_does_not_overwrite_a_changed_document(self,embed):
        ProblemSearchDocument.objects.all().update(retry_at=None)
        document=ProblemSearchDocument.objects.order_by('pk').first()
        def changed(texts,mode):
            ProblemSearchDocument.objects.filter(pk=document.pk).update(fingerprint='changed')
            return np.ones((len(texts),384),dtype=np.float32)/np.sqrt(384)
        embed.side_effect=changed;index_batch(1);document.refresh_from_db()
        self.assertIsNone(document.embedding)

    def test_validation_and_long_text(self):
        for params in [{'field':'bad'},{'mode':'bad'},{'scope':'bad'},{'limit':1000}]:
            self.assertEqual(self.query(self.teacher,'проверка',**params).status_code,400)
        self.assertEqual(self.query(self.teacher,'x'*12001).status_code,400)
        self.assertEqual(self.query(self.teacher,'x'*1000,mode='text').status_code,200)
        self.assertEqual(APIClient().get('/api/problem-search',{'q':'test'}).status_code,403)

    def test_formulas_are_not_normalized_into_a_false_exact_copy(self):
        self.assertNotEqual(normalized('x < 2'),normalized('x ≤ 2'))
        self.assertNotEqual(normalized('X = 2'),normalized('x = 2'))
        self.assertEqual(normalized('x  =\n 2'),normalized('x = 2'))

    def test_versioned_contract_includes_search_for_read_only_clients(self):
        from .api_reference import schema_for
        from .test_api_reference import assert_contract
        response=self.client_for(self.teacher).get('/api/v1/problem-search',{'q':self.problem.statement,'mode':'text'})
        spec=schema_for(self.teacher,read_only=True)
        schema=spec['paths']['/problem-search']['get']['responses']['200']['content']['application/json']['schema']
        assert_contract(schema,response.data,spec['components']['schemas'])

    def test_read_only_token_can_post_search_but_not_create(self):
        from .authentication import create_token
        token,secret=create_token(self.teacher,{'read_only':True})
        client=APIClient();client.credentials(HTTP_AUTHORIZATION='Bearer '+secret)
        response=client.post('/api/v1/problem-search',{'q':self.problem.statement,'mode':'text'},format='json')
        self.assertEqual(response.status_code,200)
        self.assertEqual(client.post('/api/v1/materials/problem',{},format='json').status_code,403)

    def test_filters_and_foreign_materials_remain_scoped(self):
        other=Problem.objects.create(author=self.teacher,published=True,statement='Скрытая от школьника задача другого кружка 987654321',solution='Закрытое решение')
        response=self.query(self.student,other.statement,mode='text')
        self.assertNotIn(str(other.pk),[row['problem']['id'] for row in response.data['results']])
        tag=self.problem.tags.first()
        if tag:
            response=self.query(self.teacher,self.problem.statement,tag=tag.pk,mode='text')
            self.assertTrue(all(tag.pk in [item['id'] for item in hit['problem']['tags']] for hit in response.data['results']))

    def test_solution_only_search_does_not_search_title_or_interpret_answer_as_id(self):
        problem=Problem.objects.create(author=self.teacher,published=True,title='unique-title-7942435',statement='Другое условие',solution='12345')
        response=self.query(self.teacher,'unique-title-7942435',field='solution',mode='text')
        self.assertEqual(response.data['results'],[])
        response=self.query(self.teacher,'12345',field='solution',mode='text')
        self.assertEqual(response.data['results'][0]['problem']['id'],str(problem.pk))
        self.assertEqual(response.data['results'][0]['match'],'exact')

    @patch('core.search._embed_request')
    def test_large_document_covers_all_input_without_silent_truncation(self,remote):
        from .search import embed
        remote.side_effect=lambda texts,mode:np.ones((len(texts),384),dtype=np.float32)/np.sqrt(384)
        vector=embed(['x'*25001],'document')
        chunks=remote.call_args[0][0]
        self.assertEqual(''.join(chunks),'x'*25001)
        self.assertLessEqual(max(map(len,chunks)),10000)
        self.assertEqual(vector.shape,(1,384))

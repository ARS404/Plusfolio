import copy,hashlib,json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase,SimpleTestCase,override_settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient
from . import services as s
from .models import User,Problem,ProblemNumber,Topic,TopicCatalogVersion,Circle,Solve
from .problem_import import import_sample,problem_uuid,topic_uuid
from .problems_ru import parse_catalog,plain,Unsupported,balanced


def source_row(identifier='900001',topic='189'):
    statement='Найдите число способов.';solution='Ответ:\n8 способов.'
    return {'source_id':identifier,'source_url':'https://problems.ru/view_problem_details_new.php?id='+identifier,
        'title':'','statement':statement,'solution':solution,'topics':[{'id':topic,'name':'Исходная тема'}],
        'catalog_subjects':['188'],'has_detailed_solution':False,
        'content_sha256':hashlib.sha256((statement+'\n\n'+solution).encode()).hexdigest()}


class SourceParserTests(SimpleTestCase):
    def page(self,body):
        return '<title>Каталог по темам</title><a name="problem_42"></a><table class="problemsmallcaptiontable"><tr><td><table><tr><td><a href="/view_by_subject_new.php?parent=189">Тема</a></td></tr></table></td></tr></table>'+body+'<table class="problemfootertable"><tr><td><img src="basket.gif"/></td></tr></table>'

    def test_answer_superscripts_and_nested_caption_survive_without_footer(self):
        rows,skipped,count=parse_catalog(self.page('<p>Условие: x<sub>1</sub>.</p><h3>Ответ</h3><p>2<sup>3</sup> = 8.</p>'),'188')
        self.assertEqual((count,len(rows),skipped),(1,1,[]))
        self.assertEqual(rows[0]['statement'],'Условие: x${}_{1}$.')
        self.assertIn('2${}^{3}$ = 8',rows[0]['solution']);self.assertFalse(rows[0]['has_detailed_solution'])
        self.assertEqual(rows[0]['topics'],[{'id':'189','name':'Тема'}])

    def test_incomplete_illustrated_and_executable_content_is_rejected_whole(self):
        for content in ['<p>Условие<img src="essential.gif"/></p><h3>Ответ</h3>8','<p>Условие</p><h3>Решение</h3><table><tr><td>1</td></tr></table>','<p>Условие<script>secret()</script></p><h3>Ответ</h3>8','<p>Условие без ответа</p>']:
            rows,skipped,_=parse_catalog(self.page(content),'188')
            self.assertEqual(rows,[]);self.assertEqual(len(skipped),1)
        with self.assertRaises(Unsupported):plain('<a href="javascript:alert(1)">ссылка</a>')

    def test_references_keep_their_urls_and_detailed_solutions_are_marked(self):
        rows,_,_=parse_catalog(self.page('<p>Условие</p><h3>Решение 1</h3><p>См. <a href="/view_problem_details_new.php?id=10">задачу 10</a>.</p><h3>Ответ</h3>8'),'188')
        self.assertTrue(rows[0]['has_detailed_solution']);self.assertIn('https://problems.ru/view_problem_details_new.php?id=10',rows[0]['solution'])

    def test_balanced_selection_deduplicates_by_source_id(self):
        first=source_row();second=source_row('900002');third=source_row('900003')
        result=balanced({'188':[first,second],'88':[first,third]},3)
        self.assertEqual({row['source_id'] for row in result},{'900001','900002','900003'})

    def test_display_and_inline_math_share_scope_with_html_superscripts(self):
        self.assertEqual(plain('<p>$$S = x<sup>2</sup>\n + y<sub>1</sub>$$</p>'),'$S = x^{2} + y_{1}$')
        self.assertEqual(plain('$x<sup>$2$</sup>$'),'$x^{2}$')
        with self.assertRaises(Unsupported):plain('Незакрытая формула $x+1')
        with self.assertRaises(Unsupported):plain('Некорректный показатель <sup>P(x}</sup>')


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class OptionalTitleAndImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo',verbosity=0)
        cls.admin=User.objects.get(email='admin@plusfolio.example');cls.teacher=User.objects.get(email='teacher@plusfolio.example');cls.student=User.objects.get(email='student@plusfolio.example')
        cls.catalog=json.loads((settings.BASE_DIR/'data/problems_topics.json').read_text())
        cls.circle=Circle.objects.get(name='Математическая мастерская')
        cls.topic=Topic.objects.filter(source_id='189').first()

    def client_for(self,user):
        client=APIClient();client.force_authenticate(user=user);return client

    def sample(self,*rows):return {'schema_version':1,'source':'problems.ru','problems':list(rows or [source_row()]),'fetched_at':'2026-10-22T00:00:00Z','copyright_url':'https://problems.ru/about_system.php'}

    def test_optional_and_duplicate_titles_keep_unique_uuids_and_stable_numbers(self):
        problems=[]
        for title in ['',None,'Одинаковое название','Одинаковое название']:
            response=self.client_for(self.teacher).post('/api/materials/problem',{'title':title,'statement':'Условие','solution':'Ответ','topics':[str(self.topic.pk)]},format='json')
            self.assertEqual(response.status_code,201,response.data)
            problems.append(Problem.objects.get(pk=response.data['id']))
            self.assertEqual(response.data['custom_title'],title or '')
            self.assertEqual(response.data['number'],problems[-1].number_id)
            if not title:self.assertEqual(response.data['title'],f'Задача №{problems[-1].number_id}')
        self.assertEqual(len({row.pk for row in problems}),4);self.assertEqual(len({row.number_id for row in problems}),4)
        sheet=s.create_material(self.teacher,'worksheet',{'title':'Листок','topics':[str(self.topic.pk)],'problems':[str(row.pk) for row in problems]})
        s.issue_worksheet(self.teacher,self.circle,sheet.pk,timezone.localdate())
        s.mark(self.teacher,self.circle,problems[2].pk,{'student_id':self.student.student.pk,'value':True,'version':0})
        self.assertTrue(Solve.objects.get(student=self.student.student,problem=problems[2]).solved)
        self.assertFalse(Solve.objects.filter(student=self.student.student,problem=problems[3],solved=True).exists())

    def test_unnamed_problem_bulk_creation_also_allocates_unique_numbers(self):
        rows=Problem.objects.bulk_create([Problem(author=self.admin,statement='x',solution='y') for _ in range(3)])
        self.assertEqual(len({row.number_id for row in rows}),3);self.assertTrue(all(row.number_id for row in rows))

    def test_import_is_idempotent_preserves_source_ids_and_admin_topic_edits(self):
        self.topic.name='Название, выбранное администратором';self.topic.save()
        sample=self.sample();first=import_sample(self.admin,sample,self.catalog)
        self.assertEqual(first['created'],1)
        problem=Problem.objects.get(source='problems.ru',source_id='900001');number=problem.number_id
        self.assertEqual(problem.pk,problem_uuid('900001'));self.assertEqual(problem.title,'')
        self.assertEqual(problem.display_title,'Задача №900001 · problems.ru')
        second=import_sample(self.admin,sample,self.catalog)
        self.assertEqual((second['created'],second['skipped']),(0,1));problem.refresh_from_db();self.assertEqual(problem.number_id,number)
        self.topic.refresh_from_db();self.assertEqual(self.topic.name,'Название, выбранное администратором')

    def test_missing_topics_are_created_by_source_id_with_their_other_child(self):
        catalog=copy.deepcopy(self.catalog);identifier='900000001'
        catalog['normalized_nodes'] += [
            {'id':'problems:'+identifier,'source_id':identifier,'name':'Новая тема источника','parent_id':'problems:1302','is_other':False,'sort_order':100},
            {'id':'other:problems:'+identifier,'source_id':None,'name':'Прочее','parent_id':'problems:'+identifier,'is_other':True,'sort_order':999}]
        versions=TopicCatalogVersion.objects.count()
        result=import_sample(self.admin,self.sample(source_row(topic=identifier)),catalog)
        self.assertEqual(result['topics_created'],2)
        topic=Topic.objects.get(pk=topic_uuid('problems:'+identifier))
        self.assertEqual(topic.source_id,identifier);self.assertEqual(topic.children.filter(is_other=True).count(),1)
        self.assertEqual(TopicCatalogVersion.objects.count(),versions+1)

    def test_dry_run_permissions_and_invalid_batch_leave_database_unchanged(self):
        before=(Problem.objects.count(),ProblemNumber.objects.count(),Topic.objects.count())
        self.assertEqual(import_sample(self.admin,self.sample(),self.catalog,dry_run=True)['created'],1)
        with self.assertRaises(PermissionDenied):import_sample(self.teacher,self.sample(),self.catalog)
        with self.assertRaises(ValidationError):import_sample(self.admin,self.sample(source_row(),source_row()),self.catalog)
        wrong=source_row();wrong['solution']='Подмена без обновления контрольной суммы'
        with self.assertRaises(ValidationError):import_sample(self.admin,self.sample(wrong),self.catalog)
        self.assertEqual((Problem.objects.count(),ProblemNumber.objects.count(),Topic.objects.count()),before)

    def test_changed_source_never_overwrites_published_content(self):
        import_sample(self.admin,self.sample(),self.catalog);changed=source_row();changed['solution']='Другой ответ'
        changed['content_sha256']=hashlib.sha256((changed['statement']+'\n\n'+changed['solution']).encode()).hexdigest()
        with self.assertRaises(ValidationError):import_sample(self.admin,self.sample(changed),self.catalog)
        self.assertEqual(Problem.objects.get(source_id='900001').solution,source_row()['solution'])

    def test_number_uuid_and_source_search_and_pagination_keep_scoped_permissions(self):
        import_sample(self.admin,self.sample(*[source_row(str(900001+i)) for i in range(5)]),self.catalog)
        problem=Problem.objects.get(source_id='900001');client=self.client_for(self.teacher)
        for query in ['900001','№900001',str(problem.number_id),str(problem.pk)]:
            self.assertIn(str(problem.pk),[row['id'] for row in client.get('/api/materials/problem',{'q':query}).data])
        first=client.get('/api/materials/problem',{'pagination':'1','page_size':'3','page':'1'}).data
        second=client.get('/api/materials/problem',{'pagination':'1','page_size':'3','page':'2'}).data
        self.assertEqual(first['count'],Problem.objects.filter(published=True).count())
        self.assertFalse({row['id'] for row in first['results']}&{row['id'] for row in second['results']})
        student=self.client_for(self.student)
        self.assertEqual(student.get('/api/materials/problem',{'q':'900001'}).data,[])
        self.assertEqual(student.get('/api/materials/problem/'+str(problem.pk)).status_code,404)
        for params in [{'pagination':'1','page':'0'},{'pagination':'1','page_size':'1000'}]:self.assertEqual(client.get('/api/materials/problem',params).status_code,400)

    def test_source_attribution_is_preserved_in_tex_without_hidden_solutions(self):
        from .documents import project_for,escape_text
        from types import SimpleNamespace
        import_sample(self.admin,self.sample(),self.catalog);problem=Problem.objects.get(source_id='900001')
        files=project_for(SimpleNamespace(title='Листок',description=''),[problem],[],True)
        task=next(text for name,text in files.items() if name.startswith('tasks/'))
        self.assertIn(escape_text(problem.source_url),task);self.assertIn('900001',task)
        self.assertFalse(any(name.startswith('solutions/') for name in files))

    def test_editable_copy_keeps_attribution_and_gets_a_separate_identity(self):
        from .documents import project_for,escape_text
        from types import SimpleNamespace
        import_sample(self.admin,self.sample(),self.catalog);original=Problem.objects.get(source_id='900001')
        response=self.client_for(self.teacher).post('/api/materials/problem',{'copy_of':str(original.pk),'statement':original.statement+' Моя правка.','solution':original.solution,'topics':[str(self.topic.pk)]},format='json')
        self.assertEqual(response.status_code,201,response.data)
        duplicate=Problem.objects.get(pk=response.data['id'])
        self.assertNotEqual(duplicate.pk,original.pk);self.assertNotEqual(duplicate.number_id,original.number_id)
        self.assertEqual(duplicate.source_id,'');self.assertEqual(duplicate.attribution,original.attribution)
        files=project_for(SimpleNamespace(title='Копия',description=''),[duplicate])
        self.assertIn(escape_text(original.source_url),next(text for name,text in files.items() if name.startswith('tasks/')))

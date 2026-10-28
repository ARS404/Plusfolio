"""Read budgets and large-history writes must stay bounded as demo datasets grow."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import patch
from django.core.management import call_command
from django.db import connection
from django.test import TestCase,TransactionTestCase,override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient
from . import services as s
from .models import User, Circle, CircleTeacher, Enrollment, Problem, Worksheet, WorksheetItem, WorksheetIssue, WorksheetDocument, Assignment, Topic, Tag, Solve, Discussion


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class QueryBudgetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo',verbosity=0)
        cls.teacher=User.objects.get(email='teacher@plusfolio.example')
        cls.admin=User.objects.get(email='admin@plusfolio.example')
        cls.student=User.objects.get(email='student@plusfolio.example')
        cls.circles=[Circle(name=f'Бюджет запросов {index:02}',city='Москва',region='Тест',created_by=cls.admin) for index in range(24)]
        Circle.objects.bulk_create(cls.circles)
        CircleTeacher.objects.bulk_create([CircleTeacher(circle=circle,teacher=cls.teacher.teacher) for circle in cls.circles])
        Enrollment.objects.bulk_create([Enrollment(circle=circle,student=cls.student.student) for circle in cls.circles])
        tag=Tag.objects.filter(kind='problem').first();topic=Topic.objects.filter(parent__isnull=False,is_other=False).first()
        problems=[Problem(title=f'Бюджет задача {index:03}',statement='Условие',solution='Решение',author=cls.teacher,published=True) for index in range(80)]
        Problem.objects.bulk_create(problems)
        Problem.tags.through.objects.bulk_create([Problem.tags.through(problem=problem,tag=tag) for problem in problems])
        Problem.topics.through.objects.bulk_create([Problem.topics.through(problem=problem,topic=topic) for problem in problems])
        documents=[WorksheetDocument(author=cls.teacher) for _ in range(40)]
        WorksheetDocument.objects.bulk_create(documents)
        sheets=[Worksheet(document=document,title=f'Бюджет листок {index:02}',author=cls.teacher,published=True) for index,document in enumerate(documents)]
        Worksheet.objects.bulk_create(sheets)
        for document,sheet in zip(documents,sheets):document.current_revision=sheet
        WorksheetDocument.objects.bulk_update(documents,['current_revision'])
        WorksheetItem.objects.bulk_create([WorksheetItem(worksheet=sheet,problem=problem,position=index+1) for sheet in sheets for index,problem in enumerate(problems)])
        issues=[WorksheetIssue(circle=cls.circles[0],worksheet=sheet,document_id=sheet.document_id,issued_by=cls.teacher,issued_on='2026-10-20',number=index+1) for index,sheet in enumerate(sheets)]
        WorksheetIssue.objects.bulk_create(issues)
        Assignment.objects.bulk_create([Assignment(issue=issue,student=cls.student.student) for issue in issues])

    def request(self,user,path,budget):
        client=APIClient();client.force_authenticate(user=User.objects.get(pk=user.pk))
        with CaptureQueriesContext(connection) as queries:
            response=client.get(path)
        self.assertEqual(response.status_code,200)
        self.assertLessEqual(len(queries),budget,[(query['sql'][:100]) for query in queries])
        return response.data

    def test_circles_load_permissions_counts_tags_and_teachers_in_constant_queries(self):
        for user in [self.admin,self.teacher,self.student]:
            rows=self.request(user,'/api/circles',4)
            self.assertGreaterEqual(len(rows),24)
            circle=next(row for row in rows if row['id']==str(self.circles[0].pk))
            self.assertEqual(circle['student_count'],1);self.assertEqual(circle['worksheet_count'],40)
            self.assertEqual(circle['can_write'],user.pk!=self.student.pk)
            self.assertEqual(circle['teachers'][0]['email'],None if user.pk==self.student.pk else self.teacher.email)

    def test_material_and_issuance_reads_do_not_query_per_row(self):
        self.assertGreaterEqual(len(self.request(self.teacher,'/api/materials/problem',4)),80)
        self.assertGreaterEqual(len(self.request(self.student,'/api/my-materials/problem',6)),80)
        self.assertGreaterEqual(len(self.request(self.teacher,'/api/materials/worksheet',5)),40)
        self.assertGreaterEqual(len(self.request(self.student,'/api/my-materials/worksheet',3)),40)
        self.assertEqual(len(self.request(self.teacher,f'/api/circles/{self.circles[0].pk}/issues',4)),40)

    def test_repeated_journal_tasks_keep_query_budget_and_closed_solutions(self):
        result=self.request(self.student,f'/api/circles/{self.circles[0].pk}/journal',12)
        self.assertEqual(len(result['blocks']),40)
        self.assertTrue(all(len(block['problems'])==80 for block in result['blocks']))
        self.assertTrue(all('solution' not in problem for block in result['blocks'] for problem in block['problems']))

    def test_large_report_cohorts_preserve_global_counts_and_full_sheet_completion(self):
        circle=self.circles[0]
        peer=User.objects.create_user('report-peer@example.test','unused',name='Тестовый Второй Ученик',roles=['student'])
        s.profiles(peer)
        issues=list(circle.issues.order_by('pk'))
        Assignment.objects.bulk_create([Assignment(issue=issue,student=peer.student) for issue in issues[:20]])
        problem=Problem.objects.filter(items__worksheet__issues__circle=circle).distinct().order_by('pk').first()
        Solve.objects.create(student=self.student.student,problem=problem,solved=True,changed_by=self.teacher,source_circle=circle)
        Discussion.objects.create(circle=circle,problem=problem,discussed=True,solution_visible=True,changed_by=self.teacher)
        result=self.request(self.teacher,f'/api/analytics?circle={circle.pk}',20)
        self.assertEqual((result['assigned_pairs'],result['solved_pairs']),(160,1))
        self.assertEqual(result['counts']['worksheet_recipient_count'],60)
        self.assertEqual(sum(row['assigned'] for row in result['worksheet_rows']),4800)
        self.assertEqual(result['counts']['full_worksheet_count'],0)
        self.assertEqual(result['attention']['discussed_pending_problem_count'],1)
        self.assertEqual((result['circle_rows'][0]['recipients'],result['circle_rows'][0]['assigned']),(2,160))
        tag=Tag.objects.create(kind='problem',name='Only solved first task')
        Problem.tags.through.objects.bulk_create([Problem.tags.through(problem=problem,tag=tag)])
        filtered=self.request(self.teacher,f'/api/analytics?circle={circle.pk}&problem_tag={tag.pk}',21)
        self.assertEqual((filtered['assigned_pairs'],filtered['solved_pairs']),(2,1))
        self.assertEqual(filtered['counts']['full_worksheet_count'],0)
        self.assertTrue(all(row['total_problem_count']==80 for row in filtered['worksheet_rows']))

    def test_account_counters_have_a_constant_budget_for_independent_role_scopes(self):
        from .account import overview
        for user,budget in [(self.admin,6),(self.teacher,8),(self.student,5)]:
            with CaptureQueriesContext(connection) as queries:result=overview(user)
            self.assertLessEqual(len(queries),budget)
            self.assertEqual(result['circle_count'],s.circles_for(user).count())
            self.assertEqual(result['active_circle_count'],s.circles_for(user).filter(archived=False).count())
            self.assertEqual(result['teacher'] is not None,'teacher' in user.roles)
            self.assertEqual(result['student'] is not None,'student' in user.roles)
        self.admin.roles=['admin','teacher','student','analyst'];self.admin.save();s.profiles(self.admin)
        with CaptureQueriesContext(connection) as queries:result=overview(self.admin)
        self.assertLessEqual(len(queries),13)
        self.assertTrue(all(result[role] is not None for role in self.admin.roles))

    def test_enrollment_assigns_large_history_in_bulk_and_preserves_existing_dates(self):
        pupil=User.objects.create_user('budget-new@plusfolio.example','unused',name='Тестовый Ученик',roles=['student']);s.profiles(pupil)
        with CaptureQueriesContext(connection) as queries:s.enroll(self.teacher,self.circles[0],pupil.email)
        self.assertLessEqual(len(queries),20)
        before=dict(Assignment.objects.filter(student=pupil.student).values_list('pk','assigned_at'))
        self.assertEqual(len(before),40)
        s.enroll(self.teacher,self.circles[0],pupil.email)
        self.assertEqual(dict(Assignment.objects.filter(student=pupil.student).values_list('pk','assigned_at')),before)


@skipUnless(connection.vendor=='sqlite','Local demo backup format requires SQLite')
class StreamingBackupTests(TransactionTestCase):
    def test_full_bundle_streams_large_files_and_excludes_dependency_trees(self):
        from .backup import create_bundle,restore_bundle
        with TemporaryDirectory() as directory:
            root=Path(directory)/'source';local=root/'.local';local.mkdir(parents=True)
            binary=local/'tools/tectonic';binary.parent.mkdir();binary.write_bytes(b'compiler'*600000)
            source=root/'large.bin';source.write_bytes(b'content'*600000)
            for name in ['frontend/node_modules/deep/file.txt','.venv/deep/file.txt','nested/.git/config','nested/.local/private','old.pfb']:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('excluded')
            original=Path.read_bytes
            def read(path):
                if path in [binary,source]:raise AssertionError('Large files must be streamed')
                return original(path)
            with override_settings(BASE_DIR=root,LOCAL_DIR=local),patch.object(Path,'read_bytes',read):
                bundle=Path(directory)/'archive.pfb';manifest=create_bundle(bundle)
                self.assertEqual(set(manifest['files']),{'.local/demo.sqlite3','.local/app.key','.local/tools/tectonic','large.bin'})
                restore_bundle(bundle,local/'backup.key',Path(directory)/'restored')
            self.assertEqual((Path(directory)/'restored/large.bin').read_bytes(),source.read_bytes())


class SearchSynchronizationBudgetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user=User.objects.create_user('index-budget@example.test','unused',name='Index budget',roles=['admin'])
        cls.root=Topic.objects.create(name='Root')
        cls.parent=Topic.objects.create(name='Algebra',parent=cls.root)
        cls.topics=[Topic(name=f'Topic {n:03}',parent=cls.parent) for n in range(500)]
        Topic.objects.bulk_create(cls.topics)

    def test_large_topic_refresh_is_batched_and_preserves_unchanged_vectors(self):
        import numpy as np
        from .catalogue_search import sync_topics
        from .models import CatalogueSearchDocument
        from .search import MODEL_ID
        sync_topics()
        vector=np.zeros(384,dtype=np.float32);vector[0]=1
        CatalogueSearchDocument.objects.filter(kind='topic',object_id=self.topics[0].pk).update(embedding=vector,model=MODEL_ID)
        with CaptureQueriesContext(connection) as queries:sync_topics()
        self.assertLessEqual(len(queries),25)
        doc=CatalogueSearchDocument.objects.get(kind='topic',object_id=self.topics[0].pk)
        self.assertEqual(doc.model,MODEL_ID);self.assertEqual(np.asarray(doc.embedding).tolist(),vector.tolist())
        Topic.objects.filter(pk=self.parent.pk).update(name='Renamed algebra')
        with CaptureQueriesContext(connection) as queries:sync_topics()
        self.assertLessEqual(len(queries),40)
        doc.refresh_from_db();self.assertIsNone(doc.embedding);self.assertEqual(doc.model,'')
        self.assertEqual(doc.text,'Renamed algebra / Topic 000')

    def test_bulk_problem_import_is_reconciled_with_bounded_queries(self):
        from .models import ProblemSearchDocument
        from .search import reconcile_missing
        problems=[Problem(author=self.user,published=True,statement=f'Condition {n}',solution='Solution') for n in range(150)]
        Problem.objects.bulk_create(problems)
        with CaptureQueriesContext(connection) as queries:reconcile_missing()
        self.assertLessEqual(len(queries),40)
        self.assertEqual(ProblemSearchDocument.objects.filter(problem__in=problems).count(),450)
        reconcile_missing()
        self.assertEqual(ProblemSearchDocument.objects.filter(problem__in=problems).count(),450)

    def test_recent_material_indexes_match_the_stable_pagination_order(self):
        from django.db import models
        for model,name in [(Problem,'problem_published_order'),(Worksheet,'worksheet_published_order')]:
            index=next(index for index in model._meta.indexes if index.name==name)
            self.assertEqual(index.fields,['-created_at','-id'])
            self.assertEqual(index.condition,models.Q(published=True))
            if connection.vendor=='sqlite':
                plan=model.objects.filter(published=True).order_by('-created_at','-pk').values('pk').explain()
                self.assertIn(name,plan);self.assertNotIn('TEMP B-TREE',plan)

"""A filtered view must not duplicate already serialized task payloads."""
import tracemalloc
from django.db import connection
from django.test import SimpleTestCase,TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from .journal import apply_view,select_issues,snapshot
from .models import Circle,Problem,User,Worksheet,WorksheetDocument,WorksheetIssue,WorksheetItem


class JournalViewMemoryTests(SimpleTestCase):
    def test_large_view_preserves_numbers_with_a_bounded_temporary_allocation(self):
        payload={key:'' for key in ['title','description','author','custom_title','public_id','source','source_id','source_url',
            'statement','pdf_url','tex_url','project_url','source_format','statement_tex','solution','solution_tex','solution_kind']}
        payload.update(topics=[],tags=[],archived=False,attribution={},statement_images=[],solution_images=[],number=1)
        blocks=[{'issue_id':sheet,'issued_on':'2026-11-01','problems':[
            {**payload,'id':f'problem-{index}','worksheet_position':index} for index in range(100)]} for sheet in range(20)]
        data={'blocks':blocks,'solves':[],'discussions':[]}
        apply_view(data)
        tracemalloc.start()
        try:
            view=apply_view(data,order='oldest')
            _,peak=tracemalloc.get_traced_memory()
        finally:tracemalloc.stop()
        self.assertLess(peak,250_000)
        self.assertEqual(len(view['blocks']),20)
        self.assertEqual(view['blocks'][0]['problems'][0]['worksheet_position'],0)
        self.assertEqual([block['issue_id'] for block in data['blocks']],list(range(20)))


class JournalLoadingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner=User.objects.create(email='journal-load@example.test',name='Чтение',roles=['admin'])
        cls.circle=Circle.objects.create(name='Кружок чтения',created_by=cls.owner)
        body='x'*(256*1024)
        cls.problems=[Problem(author=cls.owner,title=str(index),statement='Условие' if index==1 else body,
            solution='Решение' if index==1 else body,published=True) for index in range(3)]
        Problem.objects.bulk_create(cls.problems)
        document=WorksheetDocument.objects.create(author=cls.owner)
        sheet=Worksheet.objects.create(document=document,author=cls.owner,title='Нумерация',numbering_start=0)
        WorksheetItem.objects.bulk_create([WorksheetItem(worksheet=sheet,problem=problem,position=position,include_in_journal=index==1)
            for index,(problem,position) in enumerate(zip(cls.problems,[3,8,12]))])
        sheet.published=True;sheet.save()
        WorksheetIssue.objects.create(circle=cls.circle,worksheet=sheet,document=document,issued_by=cls.owner,
            number=1,issued_on=timezone.localdate())

    def test_excluded_bodies_are_not_fetched_but_all_numbering_positions_remain(self):
        for for_export in [False,True]:
            with self.subTest(for_export=for_export):
                with CaptureQueriesContext(connection) as queries:selected=select_issues(self.circle,for_export=for_export)
                problem_reads=[query['sql'] for query in queries if 'FROM "core_problem"' in query['sql']]
                self.assertEqual(len(problem_reads),1)
                for problem in [self.problems[0],self.problems[2]]:
                    self.assertNotIn(problem.pk.hex,problem_reads[0]);self.assertNotIn(str(problem.pk),problem_reads[0])
                self.assertEqual([item.position for item in selected[0].worksheet.items.all()],[3,8,12])
                data=snapshot(self.owner,self.circle,selected,lambda problem,user:{'id':str(problem.pk),'title':problem.display_title})
                self.assertEqual([(p['id'],p['worksheet_position']) for p in data['blocks'][0]['problems']],[(str(self.problems[1].pk),1)])

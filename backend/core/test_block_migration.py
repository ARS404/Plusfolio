from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class WorksheetBlockMigrationTests(TransactionTestCase):
    def test_existing_issued_order_and_template_are_preserved(self):
        executor=MigrationExecutor(connection)
        try:
            executor.migrate([('core','0016_mail_budget')])
            old=executor.loader.project_state([('core','0016_mail_budget')]).apps
            User=old.get_model('core','User');Problem=old.get_model('core','Problem')
            owner=User.objects.create(email='migration@example.test',name='Миграция',roles=['teacher'])
            number=old.get_model('core','WorksheetNumber').objects.create()
            document=old.get_model('core','WorksheetDocument').objects.create(number=number,author=owner)
            sheet=old.get_model('core','Worksheet').objects.create(document=document,author=owner,title='Старый листок',published=True)
            tasks=[]
            for position in [3,8]:
                number=old.get_model('core','ProblemNumber').objects.create()
                problem=Problem.objects.create(number=number,author=owner,statement='Условие',solution='Решение',published=True)
                old.get_model('core','WorksheetItem').objects.create(worksheet=sheet,problem=problem,position=position)
                tasks.append(problem.pk)
            executor=MigrationExecutor(connection);executor.migrate([('core','0018_worksheet_journal_options')])
            from .models import Worksheet,WorksheetBlock,WorksheetItem
            self.assertEqual(Worksheet.objects.get(pk=sheet.pk).template_version,'math-a4-v1')
            self.assertEqual(Worksheet.objects.get(pk=sheet.pk).numbering_start,1)
            self.assertTrue(all(WorksheetBlock.objects.filter(worksheet_id=sheet.pk).values_list('include_in_journal',flat=True)))
            self.assertTrue(all(WorksheetItem.objects.filter(worksheet_id=sheet.pk).values_list('include_in_journal',flat=True)))
            self.assertEqual(list(WorksheetBlock.objects.filter(worksheet_id=sheet.pk).values_list('position',flat=True)),[3,8])
            self.assertEqual(list(WorksheetBlock.objects.filter(worksheet_id=sheet.pk).values_list('problem_id',flat=True)),tasks)
            self.assertEqual(list(WorksheetItem.objects.filter(worksheet_id=sheet.pk).values_list('problem_id',flat=True)),tasks)
        finally:
            MigrationExecutor(connection).migrate([('core','0018_worksheet_journal_options')])

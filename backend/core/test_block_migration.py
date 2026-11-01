from datetime import date
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class WorksheetBlockMigrationTests(TransactionTestCase):
    def test_existing_issued_order_and_template_are_preserved(self):
        executor=MigrationExecutor(connection)
        target=[('core','0018_worksheet_journal_options')]
        try:
            executor.migrate([('core','0016_mail_budget')])
            old=executor.loader.project_state([('core','0016_mail_budget')]).apps
            model=lambda name:old.get_model('core',name)
            owner=model('User').objects.create(email='migration@example.test',name='Миграция',roles=['teacher'])
            reader=model('User').objects.create(email='migration-student@example.test',name='Школьник',roles=['student'])
            student=model('Student').objects.create(user=reader,graduation_year=2031)
            teacher=model('Teacher').objects.create(user=owner)
            circles=[]
            for name in ['Первый кружок','Второй кружок']:
                circle=model('Circle').objects.create(number=model('CircleNumber').objects.create(),created_by=owner,name=name,city='Москва',region='Москва')
                model('CircleTeacher').objects.create(circle=circle,teacher=teacher)
                model('Enrollment').objects.create(circle=circle,student=student)
                circles.append(circle)
            document=model('WorksheetDocument').objects.create(number=model('WorksheetNumber').objects.create(),author=owner)
            tasks=[]
            for position in [3,8]:
                problem=model('Problem').objects.create(number=model('ProblemNumber').objects.create(),author=owner,statement=f'Условие {position}: $2+2$.',solution='Ответ: $4$.',published=True)
                tasks.append(problem)
            sheets=[]
            for revision in [1,2]:
                sheet=model('Worksheet').objects.create(document=document,author=owner,title=f'Старый листок {revision}',published=revision==1,revision=revision)
                for position,problem in zip([3,8],tasks):
                    model('WorksheetItem').objects.create(worksheet=sheet,problem=problem,position=position)
                issue=model('WorksheetIssue').objects.create(circle=circles[revision-1],worksheet=sheet,document=document,issued_on=date(2026,10,31),issued_by=owner,number=revision)
                model('Assignment').objects.create(issue=issue,student=student)
                sheets.append(sheet)
            document.current_revision=sheets[1];document.public_revision=sheets[0];document.save()
            copied=model('WorksheetDocument').objects.create(number=model('WorksheetNumber').objects.create(),author=owner,copied_from=sheets[0])
            clone=model('Worksheet').objects.create(document=copied,author=owner,title='Личная копия')
            copied.current_revision=clone;copied.save()
            model('WorksheetItem').objects.create(worksheet=clone,problem=tasks[0],position=1)
            model('Solve').objects.create(student=student,problem=tasks[0],solved=True,version=7,changed_by=owner,source_circle=circles[0])
            model('Solve').objects.create(student=student,problem=tasks[1],solved=False,version=3,changed_by=owner,source_circle=circles[1])
            model('Discussion').objects.create(circle=circles[0],problem=tasks[0],discussed=True,solution_visible=True,version=4,changed_by=owner)
            model('Discussion').objects.create(circle=circles[1],problem=tasks[0],discussed=True,solution_visible=False,version=2,changed_by=owner)
            # Compare every original scalar field, including stable UUIDs, versions and dates.
            names=['User','Student','Teacher','Circle','CircleTeacher','Enrollment','Problem','WorksheetDocument','Worksheet','WorksheetItem','WorksheetIssue','Assignment','Solve','Discussion']
            fields={name:[field.attname for field in model(name)._meta.concrete_fields] for name in names}
            before={name:list(model(name).objects.order_by('pk').values_list(*fields[name])) for name in names}
            from .documents import project_for
            pdf_projects=[project_for(sheet,tasks,[task.pk for task in tasks],True) for sheet in sheets]
            executor=MigrationExecutor(connection);executor.migrate(target)
            after=executor.loader.project_state(target).apps
            for name in names:
                with self.subTest(model=name):
                    self.assertEqual(list(after.get_model('core',name).objects.order_by('pk').values_list(*fields[name])),before[name])
            from .models import Worksheet,WorksheetBlock,WorksheetItem
            for index,sheet in enumerate(sheets):
                current=Worksheet.objects.get(pk=sheet.pk)
                self.assertEqual(current.template_version,'math-a4-v1')
                self.assertEqual(current.numbering_start,1)
                self.assertEqual(list(current.blocks.values_list('position','problem_id','include_in_journal')),[(3,tasks[0].pk,True),(8,tasks[1].pk,True)])
                current_tasks=[item.problem for item in current.items.select_related('problem')]
                self.assertEqual(project_for(current,current_tasks,[task.pk for task in tasks],True),pdf_projects[index])
            self.assertFalse(WorksheetBlock.objects.filter(include_in_journal=False).exists())
            self.assertFalse(WorksheetItem.objects.filter(include_in_journal=False).exists())
            blocks=list(WorksheetBlock.objects.order_by('pk').values_list('pk','worksheet_id','problem_id','position','include_in_journal'))
            self.assertEqual(len(blocks),5)
            MigrationExecutor(connection).migrate(target)
            self.assertEqual(list(WorksheetBlock.objects.order_by('pk').values_list('pk','worksheet_id','problem_id','position','include_in_journal')),blocks)
        finally:
            MigrationExecutor(connection).migrate(target)

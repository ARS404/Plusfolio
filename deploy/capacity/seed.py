"""Disposable pilot dataset. Run inside the test stack, never a live database."""
import json
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.contrib.auth.hashers import make_password
from django.contrib.auth import login
from django.contrib.sessions.backends.db import SessionStore
from django.http import HttpRequest
from django.middleware.csrf import get_token
from django.db import transaction
from django.utils import timezone
from core import services as s
from core.authentication import create_token
from core.models import (
    AnalystGrant, Assignment, Circle, CircleTeacher, Discussion, Enrollment,
    Problem, Solve, Student, Tag, User, Worksheet, WorksheetDocument, WorksheetItem,
    WorksheetIssue,
)

DOMAIN = '@capacity.example.test'


@transaction.atomic
def seed():
    if User.objects.exclude(email__endswith=DOMAIN).exists() or Circle.objects.exists() or Problem.objects.exists():
        raise RuntimeError('Requires a fresh capacity test database; existing data will not be changed')
    admin = User.objects.get(email='admin'+DOMAIN)
    password = make_password('Synthetic-capacity-password-2040!')
    accounts = []
    for role, count in [('teacher', 3), ('analyst', 1), ('student', 95)]:
        for index in range(count):
            user = User.objects.create(email=f'{role}{index}'+DOMAIN, name=f'Тестовый {role} {index:03}',
                                       roles=[role], password=password)
            s.profiles(user)
            accounts.append(user)
    teachers = [u for u in accounts if 'teacher' in u.roles]
    students = [u.student for u in accounts if 'student' in u.roles]
    Student.objects.update(graduation_year=2032, no_patronymic=True)
    tag = Tag.objects.create(kind='circle', name='Нагрузочный пилот')
    AnalystGrant.objects.create(user=next(u for u in accounts if 'analyst' in u.roles), tag=tag)
    circles = []
    memberships = []
    for index in range(6):
        circle = Circle.objects.create(name=f'Пилотный кружок {index+1}', city=['Москва','Казань','Томск'][index%3],
            region='Тестовый регион', description='Математический кружок: геометрия, комбинаторика и теория чисел.',
            created_by=admin, launched_at=timezone.now())
        circle.tags.add(tag)
        for teacher in teachers[index%3:index%3+1] + teachers[(index+1)%3:(index+1)%3+1]:
            CircleTeacher.objects.create(circle=circle, teacher=teacher.teacher)
        group = students[index*16:(index+1)*16]
        if len(group)<16:group += students[:16-len(group)]
        memberships.append(group)
        Enrollment.objects.bulk_create([Enrollment(circle=circle, student=pupil) for pupil in group])
        circles.append(circle)
    call_command('import_problems_ru', 'data/problems_ru_sample.json', author=admin.email, verbosity=0)
    problems = list(Problem.objects.order_by('number_id'))
    sheets = []
    topic = problems[0].topics.first()
    for index in range(50):
        document = WorksheetDocument.objects.create(author=teachers[index%3])
        sheet = Worksheet.objects.create(document=document, author=document.author,
            title=f'Пилотный листок {index+1}', description='Десять задач из разных разделов математики.')
        sheet.topics.add(topic)
        WorksheetItem.objects.bulk_create([WorksheetItem(worksheet=sheet, problem=problem, position=position+1)
                                          for position, problem in enumerate(problems[index*10:(index+1)*10])])
        Worksheet.objects.filter(pk=sheet.pk).update(published=True)
        document.current_revision=sheet;document.public_revision=sheet
        document.save(update_fields=['current_revision','public_revision'])
        sheets.append(sheet)
    for circle, group in zip(circles, memberships):
        for index, sheet in enumerate(sheets):
            issue = WorksheetIssue.objects.create(circle=circle, worksheet=sheet, document=sheet.document,
                issued_by=admin, issued_on=timezone.localdate()-timedelta(days=50-index), number=index+1)
            Assignment.objects.bulk_create([Assignment(issue=issue, student=pupil) for pupil in group])
    Solve.objects.bulk_create([Solve(student=pupil, problem=problem, solved=(pupil.pk+index)%3!=0,
        changed_by=teachers[0], source_circle=circles[position//16])
        for position,pupil in enumerate(students) for index,problem in enumerate(problems) if (position+index)%2==0], batch_size=1000)
    Discussion.objects.bulk_create([Discussion(circle=circle, problem=problem, discussed=True,
        solution_visible=True, changed_by=teachers[0]) for circle in circles for problem in problems[:100]], batch_size=1000)
    sessions = []
    selected = [admin, teachers[0], next(u for u in accounts if 'analyst' in u.roles), teachers[1]]
    selected += [pupil.user for pupil in students[:6]]
    for user in selected:
        circle = s.circles_for(user).first()
        issue = circle.issues.order_by('number').first()
        if user.roles==['student']:
            request=HttpRequest();request.session=SessionStore()
            login(request,user,backend='django.contrib.auth.backends.ModelBackend')
            request.session.save();csrf=get_token(request)
            auth={'headers':{'Cookie':f'{settings.SESSION_COOKIE_NAME}={request.session.session_key}; {settings.CSRF_COOKIE_NAME}={request.META["CSRF_COOKIE"]}',
                             'X-CSRFToken':csrf,'Origin':settings.PUBLIC_URL}}
        else:
            _,token=create_token(user,{'name':'Isolated capacity check','expires_in_days':1})
            auth={'token':token}
        sessions.append({'role':user.roles[0],**auth,'circle':str(circle.pk),
                         'issue':issue.pk,'worksheet':str(issue.worksheet_id)})
    return {'sessions':sessions, 'circle':str(circles[0].pk),
            'worksheets':[str(sheet.pk) for sheet in sheets],
            'counts':{'users':User.objects.count(),'circles':len(circles),'worksheets':len(sheets),
                      'problems':len(problems),'issues':WorksheetIssue.objects.count(),
                      'assignments':Assignment.objects.count(),'solves':Solve.objects.count()}}

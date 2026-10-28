#!/usr/bin/env python3
"""Compare reporting reads against a Git revision using disposable synthetic data.

.venv/bin/python scripts/benchmark_reports.py --baseline-ref 6b1fb51 --output result.json
No live database is opened. Timings use three warm calls; tracemalloc measures
Python allocations separately, not total process RSS or production capacity.
"""
import argparse
from datetime import datetime, timezone
import gc
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import tracemalloc
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def baseline_module(ref, name, directory):
    path = Path(directory)/(name+'.py')
    path.write_bytes(subprocess.check_output(['git','show',f'{ref}:backend/core/{name}.py'],cwd=ROOT))
    spec = importlib.util.spec_from_file_location('core.benchmark_baseline_'+name,path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture():
    from core import services as s
    from core.models import (User,Student,Circle,Enrollment,CircleTeacher,AnalystGrant,
        Problem,WorksheetDocument,Worksheet,WorksheetItem,WorksheetIssue,Assignment,Solve,Discussion,Topic,Tag)
    actors = {}
    for name,roles in [('admin',['admin']),('teacher',['teacher']),('analyst',['analyst']),
                       ('multi',['teacher','analyst','student']),('all_roles',['admin','teacher','analyst','student'])]:
        user=User.objects.create(name=name,email=name+'@reports.example.test',roles=roles)
        s.profiles(user);actors[name]=user
    users=[User(name=f'Pupil {n:03}',email=f'pupil-{n}@reports.example.test',roles=['student']) for n in range(80)]
    User.objects.bulk_create(users)
    students=[Student(user=user,graduation_year=2035) for user in users];Student.objects.bulk_create(students)
    actors['student']=users[0]
    circles=[Circle(name=f'Circle {n:03}',city='Москва' if n%2==0 else 'Казань',archived=n%10==0,created_by=actors['admin']) for n in range(60)]
    Circle.objects.bulk_create(circles)
    CircleTeacher.objects.bulk_create([CircleTeacher(circle=circle,teacher=actors['teacher'].teacher) for circle in circles[:40]]+
                                     [CircleTeacher(circle=circle,teacher=actors['multi'].teacher) for circle in circles[20:50]])
    Enrollment.objects.bulk_create([Enrollment(circle=circle,student=student) for circle in circles for student in students],batch_size=500)
    circle_tag=Tag.objects.create(name='Analyst scope',kind='circle')
    Circle.tags.through.objects.bulk_create([Circle.tags.through(circle=circle,tag=circle_tag) for circle in circles[:20]])
    AnalystGrant.objects.bulk_create([AnalystGrant(user=actors[role],tag=circle_tag) for role in ['analyst','multi','all_roles']])
    root=Topic(name='Root');leaf=Topic(name='Shared topic',parent=root);Topic.objects.bulk_create([root,leaf])
    problems=[Problem(title=f'Problem {n:03}',statement='Synthetic condition',solution='Synthetic solution',author=actors['teacher'],published=True) for n in range(80)]
    Problem.objects.bulk_create(problems)
    Problem.topics.through.objects.bulk_create([Problem.topics.through(problem=problem,topic=leaf) for problem in problems])
    problem_tag=Tag.objects.create(name='Even problems',kind='problem')
    Problem.tags.through.objects.bulk_create([Problem.tags.through(problem=problem,tag=problem_tag) for problem in problems[::2]])
    documents=[WorksheetDocument(author=actors['teacher']) for _ in range(25)]
    WorksheetDocument.objects.bulk_create(documents)
    sheets=[Worksheet(document=document,title=f'Sheet {n:03}',author=actors['teacher'],published=True) for n,document in enumerate(documents)]
    Worksheet.objects.bulk_create(sheets)
    for document,sheet in zip(documents,sheets):document.current_revision=sheet;document.public_revision=sheet
    WorksheetDocument.objects.bulk_update(documents,['current_revision','public_revision'])
    WorksheetItem.objects.bulk_create([WorksheetItem(worksheet=sheet,problem=problem,position=n+1) for sheet in sheets for n,problem in enumerate(problems)])
    worksheet_tag=Tag.objects.create(name='Selected sheets',kind='worksheet')
    Worksheet.tags.through.objects.bulk_create([Worksheet.tags.through(worksheet=sheet,tag=worksheet_tag) for sheet in sheets[:12]])
    empty_tag=Tag.objects.create(name='Unused sheets',kind='worksheet')
    issues=[WorksheetIssue(circle=circle,worksheet=sheet,document=sheet.document,number=n+1,issued_on='2026-10-20',issued_by=actors['teacher']) for circle in circles for n,sheet in enumerate(sheets)]
    WorksheetIssue.objects.bulk_create(issues)
    Assignment.objects.bulk_create((Assignment(issue=issue,student=student) for issue in issues for student in students),batch_size=500)
    Solve.objects.bulk_create([Solve(student=student,problem=problem,solved=True,changed_by=actors['teacher'],source_circle=circles[0]) for student in students for problem in problems[:40]])
    Discussion.objects.bulk_create([Discussion(circle=circle,problem=problem,discussed=True,solution_visible=True,changed_by=actors['teacher']) for circle in circles for problem in problems[:20]])
    return actors,circles,problem_tag,worksheet_tag,empty_tag,root


def measure(function):
    from django.db import connection, reset_queries
    from django.test.utils import CaptureQueriesContext
    with CaptureQueriesContext(connection) as queries:result=function()
    query_count=len(queries);times=[]
    for _ in range(3):
        gc.collect();reset_queries();start=time.perf_counter();result=function()
        times.append((time.perf_counter()-start)*1000)
    gc.collect();reset_queries();tracemalloc.start()
    result=function();_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    return result,{'median_ms':round(statistics.median(times),2),'queries':query_count,'python_peak_mib':round(peak/1048576,2)}


def run(ref, directory):
    import django
    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.db import connection
    from django.http import QueryDict
    from django.test.utils import CaptureQueriesContext
    from core import analytics,account
    settings.DEBUG=False
    call_command('migrate',verbosity=0,interactive=False)
    actors,circles,problem_tag,worksheet_tag,empty_tag,root=fixture()
    old_analytics=baseline_module(ref,'analytics',directory);old_account=baseline_module(ref,'account',directory)
    result={'baseline_ref':ref,'fixture':{'circles':60,'pupils':80,'sheets':25,'problems':80,'assignments':120000},'analytics':{},'accounts':{},'equivalent_reports':0}
    fixed=datetime(2026,10,28,12,tzinfo=timezone.utc)
    with patch('django.utils.timezone.now',return_value=fixed):
        previous,stats=measure(lambda:old_analytics.report(actors['admin'],QueryDict()))
        current,new_stats=measure(lambda:analytics.report(actors['admin'],QueryDict()))
        assert previous==current,'Dense analytics changed'
        result['analytics']={'before':stats,'after':new_stats};result['equivalent_reports']+=1
        scenarios=[('teacher',{'circle':[str(c.pk) for c in circles[1:3]]}),('student',{}),
                   ('analyst',{'city':'Москва'}),('multi',{'worksheet_tag':worksheet_tag.pk,'problem_tag':problem_tag.pk,'topic':str(root.pk)}),
                   ('admin',{'worksheet_tag':empty_tag.pk}),('all_roles',{'city':['Казань','Москва'],'problem_tag':problem_tag.pk})]
        for role,params in scenarios:
            query=QueryDict('',mutable=True)
            for key,value in params.items():query.setlist(key,[str(item) for item in (value if isinstance(value,list) else [value])])
            expected=old_analytics.report(actors[role],query);actual=analytics.report(actors[role],query)
            assert expected==actual,'Analytics scope changed: '+role
            result['equivalent_reports']+=1
        for role,user in actors.items():
            with CaptureQueriesContext(connection) as queries:expected=old_account.overview(user)
            old_queries=len(queries)
            with CaptureQueriesContext(connection) as queries:actual=account.overview(user)
            assert expected==actual,'Account changed: '+role
            result['accounts'][role]={'queries_before':old_queries,'queries_after':len(queries)}
            result['equivalent_reports']+=1
    connection.close()
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref',required=True)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    sys.path.insert(0,str(ROOT/'backend'))
    with TemporaryDirectory(prefix='plusfolio-report-benchmark-') as directory:
        os.environ.update(PLUSFOLIO_LOCAL_DIR=directory,PLUSFOLIO_DEMO='1',POSTGRES_HOST='',REDIS_URL='',DJANGO_SETTINGS_MODULE='config.settings')
        result=run(args.baseline_ref,directory)
    encoded=json.dumps(result,indent=2,ensure_ascii=False)+'\n'
    if args.output:args.output.write_text(encoded)
    print(encoded,end='')


if __name__=='__main__':main()

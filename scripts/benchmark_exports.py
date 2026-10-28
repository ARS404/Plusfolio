#!/usr/bin/env python3
"""Compare journal exports using a disposable synthetic database.

Run with .venv/bin/python scripts/benchmark_exports.py --baseline-ref 950262e.
Outputs are compared as uncompressed OOXML parts; only creation/modification
timestamps are excluded. Timing is the median of three calls, separate from
tracemalloc's Python allocation peak (not process RSS or a hosting SLA).
"""
import argparse
from datetime import datetime, timezone
import gc
import importlib.util
import io
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
from xml.etree import ElementTree
from zipfile import ZipFile


def fixture(pupils=150, sheets=16, tasks=20, group=True):
    problems = [{'id':f'problem-{i}', 'title':f'Задача {i}'} for i in range(tasks)]
    blocks = [{'issue_id':i+1, 'issued_on':'2026-10-28',
               'worksheet':{'title':f'Листок {i+1}'}, 'problems':problems} for i in range(sheets)]
    people = [{'id':i+1, 'name':f'Школьник {i+1:03}'} for i in range(pupils)]
    return {'circle':{'id':'synthetic-circle', 'name':'Тестовый кружок'}, 'blocks':blocks,
            'people':people, 'solves':[{'student_id':p['id'], 'problem_id':task['id'], 'solved':(p['id']+j)%3==0}
                for p in people for j,task in enumerate(problems)],
            'discussions':[{'problem_id':task['id'], 'discussed':j%2==0} for j,task in enumerate(problems)],
            'show_group_stats':group}


def workbook_parts(content):
    with ZipFile(io.BytesIO(content)) as archive:
        parts = {name:archive.read(name) for name in archive.namelist()}
    # Workbook metadata varies on each save; all cells, styles, layout, print
    # settings, dimensions, literal-text markers and relationships stay checked.
    core = ElementTree.fromstring(parts['docProps/core.xml'])
    for child in list(core):
        if child.tag.rsplit('}',1)[-1] in {'created','modified'}:core.remove(child)
    parts['docProps/core.xml'] = ElementTree.tostring(core)
    return parts


def measure(function):
    function()  # Warm module/style paths before measuring.
    samples = []
    for _ in range(3):
        gc.collect();start = time.perf_counter();function()
        samples.append((time.perf_counter()-start)*1000)
    gc.collect();tracemalloc.start()
    content = function();_,peak = tracemalloc.get_traced_memory();tracemalloc.stop()
    stats = {'median_ms':round(statistics.median(samples),2), 'python_peak_mib':round(peak/1048576,2)}
    if isinstance(content, bytes):stats['xlsx_bytes'] = len(content)
    return content, stats


def journal_reads(root, ref, temporary):
    from django.core.management import call_command
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from core import journal, services
    from core.models import (User, Student, Circle, CircleTeacher, Enrollment, Problem,
                             WorksheetDocument, Worksheet, WorksheetItem, WorksheetIssue)
    call_command('migrate', verbosity=0, interactive=False)
    teacher = User.objects.create(name='Synthetic teacher', email='teacher@export.example.test', roles=['teacher'])
    services.profiles(teacher)
    circle = Circle.objects.create(name='Synthetic circle', created_by=teacher)
    CircleTeacher.objects.create(circle=circle, teacher=teacher.teacher)
    users = [User(name=f'Pupil {i:03}', email=f'pupil-{i}@export.example.test', roles=['student']) for i in range(150)]
    User.objects.bulk_create(users)
    pupils = [Student(user=user, graduation_year=2035) for user in users]
    Student.objects.bulk_create(pupils)
    Enrollment.objects.bulk_create([Enrollment(circle=circle, student=pupil) for pupil in pupils])
    problems = [Problem(author=teacher, published=True, title='', statement='Условие '*2000,
                        solution='Решение '*2000, statement_tex='x + y '*2000, solution_tex='x = y '*2000)
                for _ in range(320)]
    problems[0].source='problems.ru';problems[0].source_id='123456'
    Problem.objects.bulk_create(problems)
    documents = [WorksheetDocument(author=teacher) for _ in range(16)]
    WorksheetDocument.objects.bulk_create(documents)
    sheets = [Worksheet(document=document, author=teacher, published=True, title=f'Sheet {i:02}')
              for i, document in enumerate(documents)]
    Worksheet.objects.bulk_create(sheets)
    WorksheetItem.objects.bulk_create([WorksheetItem(worksheet=sheet, problem=problem, position=j+1)
        for i, sheet in enumerate(sheets) for j, problem in enumerate(problems[i*20:(i+1)*20])])
    WorksheetIssue.objects.bulk_create([WorksheetIssue(circle=circle, document=sheet.document, worksheet=sheet,
        issued_by=teacher, number=i+1, issued_on='2026-10-28') for i, sheet in enumerate(sheets)])
    path=Path(temporary)/'baseline_journal.py'
    path.write_bytes(subprocess.check_output(['git','show',f'{ref}:backend/core/journal.py'],cwd=root))
    spec=importlib.util.spec_from_file_location('core.benchmark_baseline_journal',path)
    baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
    def snapshot(module, optimized=False):
        selected=module.select_issues(circle, **({'for_export':True} if optimized else {}))
        return module.snapshot(teacher,circle,selected,lambda problem,user:{'id':str(problem.pk),'title':problem.display_title})
    previous,before=measure(lambda:snapshot(baseline))
    latest,after=measure(lambda:snapshot(journal,True))
    assert previous==latest,'Export snapshot changed'
    for module,optimized,stats in [(baseline,False,before),(journal,True,after)]:
        with CaptureQueriesContext(connection) as queries:snapshot(module,optimized)
        stats['queries']=len(queries)
    connection.close()
    return {'fixture':{'pupils':150,'sheets':16,'unique_problems':320,'source_characters_per_problem':56000},
            'before':before,'after':after,'equivalent_snapshots':1}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref',required=True)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path)
    args = parser.parse_args();root=args.root.resolve()
    sys.path.insert(0,str(root/'backend'))
    with TemporaryDirectory(prefix='plusfolio-export-benchmark-') as temporary:
        os.environ.update(PLUSFOLIO_LOCAL_DIR=temporary, PLUSFOLIO_DEMO='1', POSTGRES_HOST='',
                          REDIS_URL='', DJANGO_SETTINGS_MODULE='config.settings')
        import django
        django.setup()
        from django.conf import settings
        settings.DEBUG=False
        from core import journal_export as current
        path=Path(temporary)/'baseline.py'
        path.write_bytes(subprocess.check_output(['git','show',f'{args.baseline_ref}:backend/core/journal_export.py'],cwd=root))
        spec=importlib.util.spec_from_file_location('baseline_journal_export',path)
        baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
        dense=fixture()
        def export(module,data):return module.xlsx(data,module.columns(data))
        fixed=datetime(2026,10,28,12,tzinfo=timezone.utc)
        with patch('django.utils.timezone.now',return_value=fixed):
            previous,before=measure(lambda:export(baseline,dense))
            latest,after=measure(lambda:export(current,dense))
            assert workbook_parts(previous)==workbook_parts(latest),'Dense workbook changed'
            cases=[fixture(4,3,5,False),fixture(0,0,0),fixture(0,2,3),fixture(2,0,0)]
            hostile=fixture(3,2,3)
            hostile['people'][0]['name']='=HYPERLINK("https://example.test")'
            hostile['people'][1]['name']='\x00Имя\tс\nпереносом'
            hostile['blocks'][0]['worksheet']['title']='+Листок & <текст>'
            hostile['blocks'][0]['problems'][0]['title']='Длинное название '*3000
            cases.append(hostile)
            for i,data in enumerate(cases):
                assert workbook_parts(export(baseline,data))==workbook_parts(export(current,data)),f'Workbook changed: case {i}'
                assert baseline.export(data,'tsv').content==current.export(data,'tsv').content,f'TSV changed: case {i}'
            result={'baseline_ref':args.baseline_ref,'fixture':{'pupils':150,'sheets':16,'tasks_per_sheet':20,'columns':337},
                    'before':before,'after':after,'equivalent_xlsx_cases':1+len(cases),'equivalent_tsv_cases':len(cases)}
            result['snapshot_reads']=journal_reads(root,args.baseline_ref,temporary)
    encoded=json.dumps(result,indent=2,ensure_ascii=False)+'\n'
    if args.output:args.output.write_text(encoded)
    print(encoded,end='')


if __name__=='__main__':main()

#!/usr/bin/env python3
"""Measure list/catalogue reads in a disposable SQLite database.

Run with .venv/bin/python scripts/benchmark_reads.py [--output result.json].
The live database is never opened; temporary synthetic data is removed on exit.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[1]


def measure():
    import django
    django.setup()
    from django.core.management import call_command
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from core.models import (
        User, Student, Circle, Enrollment, WorksheetDocument, Worksheet,
        WorksheetIssue, Topic,
    )
    from core.queries import circle_rows
    from core.catalogue_search import sync_topics

    call_command('migrate', verbosity=0, interactive=False)
    admin = User.objects.create(name='Synthetic administrator', email='perf@example.test', roles=['admin'])
    users = [User(name='Synthetic pupil', email=f'pupil-{n}@example.test', roles=['student']) for n in range(150)]
    User.objects.bulk_create(users)
    students = [Student(user=user, graduation_year=2035) for user in users]
    Student.objects.bulk_create(students)
    circles = [Circle(name=f'Circle {n:03}', created_by=admin) for n in range(100)]
    Circle.objects.bulk_create(circles)
    Enrollment.objects.bulk_create([
        Enrollment(circle=circle, student=student) for circle in circles for student in students
    ], batch_size=500)
    documents = [WorksheetDocument(author=admin) for _ in range(60)]
    WorksheetDocument.objects.bulk_create(documents)
    sheets = [Worksheet(document=document, title=f'Sheet {n}', author=admin, published=True)
              for n, document in enumerate(documents)]
    Worksheet.objects.bulk_create(sheets)
    WorksheetIssue.objects.bulk_create([
        WorksheetIssue(circle=circle, document=sheet.document, worksheet=sheet, issued_by=admin,
                       issued_on='2026-10-20', number=n+1)
        for circle in circles for n, sheet in enumerate(sheets)
    ], batch_size=500)
    timings = []
    for _ in range(5):
        start = time.perf_counter()
        rows = list(circle_rows(Circle.objects.all(), admin))
        timings.append((time.perf_counter()-start)*1000)
    assert all(row._student_count == 150 and row._worksheet_count == 60 for row in rows)

    root = Topic.objects.create(name='Root')
    parent = Topic.objects.create(name='Algebra', parent=root)
    Topic.objects.bulk_create([Topic(name=f'Topic {n}', parent=parent) for n in range(500)])
    sync_topics()
    with CaptureQueriesContext(connection) as queries:
        start = time.perf_counter()
        sync_topics()
        unchanged = {'queries': len(queries), 'ms': round((time.perf_counter()-start)*1000, 2)}
    Topic.objects.filter(pk=parent.pk).update(name='Renamed algebra')
    with CaptureQueriesContext(connection) as queries:
        start = time.perf_counter()
        sync_topics()
        renamed = {'queries': len(queries), 'ms': round((time.perf_counter()-start)*1000, 2)}
    connection.close()
    return {
        'fixture': {'circles': 100, 'students_per_circle': 150, 'sheets_per_circle': 60, 'topics': 502},
        'circles_median_ms': round(statistics.median(timings), 2),
        'catalogue_unchanged': unchanged,
        'catalogue_renamed': renamed,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Also write measured results to JSON')
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT/'backend'))
    with TemporaryDirectory(prefix='plusfolio-read-benchmark-') as temporary:
        os.environ.update(PLUSFOLIO_LOCAL_DIR=temporary, PLUSFOLIO_DEMO='1', POSTGRES_HOST='',
                          REDIS_URL='', DJANGO_SETTINGS_MODULE='config.settings')
        result = measure()
    encoded = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.write_text(encoded)
    print(encoded, end='')


if __name__ == '__main__':
    main()

"""Permission-scoped learning reports built from assignments and current yes/no states."""
from collections import Counter, defaultdict
from itertools import groupby
from statistics import median
from django.db.models import Q,Exists,OuterRef
from django.utils import timezone
from . import filters as f, services as s
from .models import (Assignment, Circle, CircleTeacher, Discussion, Problem, Solve,
                     Student, Topic, TopicCatalogVersion, Worksheet, WorksheetItem, WorksheetIssue)


def percent(numerator, denominator):
    return round(100 * numerator / denominator, 1) if denominator else None


def scoped_assignments(user, params):
    circles = s.circles_for(user)
    selected_circles = f.uuid_ids(f.query_values(params, 'circle'))
    if selected_circles is not None:
        if set(str(pk) for pk in circles.filter(pk__in=selected_circles).values_list('pk', flat=True)) != selected_circles:
            raise s.NotFound('Кружок недоступен.')
        circles = circles.filter(pk__in=selected_circles)
    cities = f.query_values(params, 'city')
    circles = f.by_city(circles, cities)
    readable = set(circles.values_list('pk', flat=True))
    if s.admin(user):
        group_ids = readable
    else:
        group_ids = set()
        if 'teacher' in user.roles:
            group_ids.update(CircleTeacher.objects.filter(circle_id__in=readable, teacher__user=user, ended_at=None).values_list('circle_id', flat=True))
        group_ids.update(s.analyst_circles_for(user).filter(pk__in=readable).values_list('pk', flat=True))
    allowed = Q(issue__circle_id__in=group_ids)
    if 'student' in user.roles:
        personal = Q(student__user=user)
        if selected_circles is not None:
            personal &= Q(issue__circle_id__in=readable)
        allowed |= personal
    assignments = f.by_city(Assignment.objects.filter(allowed), cities, 'issue__circle__city')
    assignments = f.by_tags(assignments, f.query_values(params, 'worksheet_tag'), 'worksheet', 'issue__worksheet__tags')
    problems = f.by_tags(Problem.objects.all(), f.query_values(params, 'problem_tag'), 'problem')
    topic_ids = s.topic_ids_in_branch(f.query_values(params, 'topic'))
    if topic_ids is not None:
        problems = problems.filter(topics__pk__in=topic_ids)
    assignments = assignments.filter(Exists(WorksheetItem.objects.filter(worksheet_id=OuterRef('issue__worksheet_id'),problem__in=problems))).distinct()
    return assignments, problems, group_ids


def _merge_recipients(target, problem_ids, recipients, unions):
    # Equal recipient groups can serve many problems. Immutable sets let them
    # share one allocation; a union is memoized only for the current issue.
    for pid in problem_ids:
        previous = target.get(pid)
        if previous is None:
            target[pid] = recipients
        elif previous is not recipients:
            merged = unions.get(previous)
            if merged is None:
                merged = previous if recipients <= previous else previous | recipients
                unions[previous] = merged
            target[pid] = merged


def report(user, params):
    assignments, selected_problems, group_ids = scoped_assignments(user, params)
    # Read issue metadata once, rather than repeating two UUIDs for every pupil.
    issues = {iid:(wid,cid) for iid,wid,cid in WorksheetIssue.objects.filter(
        pk__in=assignments.values('issue_id')).values_list('pk','worksheet_id','circle_id')}
    worksheet_ids = {wid for wid,_ in issues.values()}
    worksheet_problems = defaultdict(set)
    for wid, pid in WorksheetItem.objects.filter(worksheet_id__in=worksheet_ids).values_list('worksheet_id', 'problem_id'):
        worksheet_problems[wid].add(pid)
    selected_ids = set(selected_problems.filter(items__worksheet_id__in=worksheet_ids).values_list('pk', flat=True).distinct())
    selected_by_worksheet = {wid: pids & selected_ids for wid, pids in worksheet_problems.items()}
    issue_ids, circle_ids = set(), set()
    circle_sheets, circle_students = defaultdict(set), defaultdict(set)
    worksheet_students, worksheet_circles, worksheet_issues = defaultdict(set), defaultdict(set), defaultdict(set)
    problem_students = {}
    circle_problem_students = defaultdict(dict)
    # Coalesce a whole issue's recipients before expanding its selected problems.
    # The existing unique (issue, student) index also supports this stream order.
    facts = assignments.order_by('issue_id','student_id').values_list('issue_id','student_id').iterator(chunk_size=2000)
    for iid, students in groupby(facts, key=lambda row:row[0]):
        if iid not in issues:continue
        recipients = frozenset(sid for _,sid in students)
        wid,cid = issues[iid]
        issue_ids.add(iid); circle_ids.add(cid); circle_sheets[cid].add(wid)
        worksheet_students[wid].update(recipients); worksheet_circles[wid].add(cid); worksheet_issues[wid].add(iid)
        pids = selected_by_worksheet[wid]
        unions = {}
        _merge_recipients(problem_students,pids,recipients,unions)
        if cid in group_ids:
            if pids:circle_students[cid].update(recipients)
            _merge_recipients(circle_problem_students[cid],pids,recipients,unions)
    student_ids = set().union(*problem_students.values()) if problem_students else set()
    all_problem_ids = set().union(*worksheet_problems.values()) if worksheet_problems else set()
    solved_by_problem, solved_by_student = defaultdict(set), defaultdict(set)
    for sid,pid in Solve.objects.filter(solved=True, student_id__in=student_ids, problem_id__in=all_problem_ids).values_list('student_id', 'problem_id').iterator(chunk_size=2000):
        solved_by_problem[pid].add(sid); solved_by_student[sid].add(pid)
    problem_solved = {pid:recipients & solved_by_problem[pid] for pid,recipients in problem_students.items()}
    assigned_count = sum(map(len,problem_students.values()))
    solved_count = sum(map(len,problem_solved.values()))
    student_assigned, student_solved = Counter(), Counter()
    for pid,recipients in problem_students.items():
        student_assigned.update(recipients); student_solved.update(problem_solved[pid])
    problems = {p.pk: p for p in Problem.objects.filter(pk__in=selected_ids).only('pk','title','number','source','source_id')}
    problem_circles, problem_worksheets = defaultdict(set), defaultdict(set)
    circle_problem_ids={cid:set().union(*(selected_by_worksheet[wid] for wid in sheets)) for cid,sheets in circle_sheets.items()}
    for cid,pids in circle_problem_ids.items():
        for pid in pids:problem_circles[pid].add(cid)
    for wid, pids in selected_by_worksheet.items():
        for pid in pids: problem_worksheets[pid].add(wid)
    rows = []
    for pid, recipients in problem_students.items():
        count = len(problem_solved[pid])
        rows.append({'problem_id': str(pid), 'public_id': f'P-{problems[pid].number_id}', 'title': problems[pid].display_title, 'recipients': len(recipients),
                     'solved': count, 'remaining': len(recipients)-count, 'percent': percent(count, len(recipients)),
                     'circle_count': len(problem_circles[pid]), 'worksheet_count': len(problem_worksheets[pid])})
    rows.sort(key=lambda row: (row['percent'], -row['recipients'], row['title']))

    worksheet_rows = []
    for worksheet in Worksheet.objects.filter(pk__in=worksheet_ids).select_related('document').only('id','title','document__number').order_by('title'):
        wid = worksheet.pk; recipients = worksheet_students[wid]; pids = selected_by_worksheet[wid]
        assigned = len(recipients)*len(pids)
        sheet_solved = sum(len(recipients & solved_by_problem[pid]) for pid in pids)
        # A filtered subset never turns an unfinished worksheet into a completed one.
        complete = sum(worksheet_problems[wid] <= solved_by_student[sid] for sid in recipients)
        worksheet_rows.append({'id': str(wid), 'public_id': f'W-{worksheet.document.number_id}', 'title': worksheet.title, 'pdf_url':'/api/materials/worksheet/'+str(wid)+'/pdf', 'recipients': len(recipients),
                               'problem_count': len(pids), 'total_problem_count': len(worksheet_problems[wid]),
                               'assigned': assigned, 'solved': sheet_solved, 'percent': percent(sheet_solved, assigned),
                               'completed_recipients': complete, 'full_percent': percent(complete, len(recipients)),
                               'circle_count': len(worksheet_circles[wid]), 'issue_count': len(worksheet_issues[wid])})

    student_rows = []
    percentages = []
    distribution = [{'label': label, 'count': 0} for label in ['0%', '<25%', '25–<50%', '50–<75%', '75–<100%', '100%']]
    students_completed = students_with_solves = 0
    for student in Student.objects.filter(pk__in=student_ids).select_related('user').only('id','graduation_year','user__id','user__name').order_by('user__name'):
        assigned = student_assigned[student.pk]; count = student_solved[student.pk]
        raw = 100*count/assigned
        percentages.append(raw); students_with_solves += bool(count); students_completed += count == assigned
        bucket = 0 if not count else 5 if count == assigned else 1 if raw < 25 else 2 if raw < 50 else 3 if raw < 75 else 4
        distribution[bucket]['count'] += 1
        if group_ids:
            student_rows.append({'id': student.pk, 'public_id':f'S-{student.pk}', 'user_public_id':f'U-{student.user_id}', 'name': student.user.name, **student.education_info(),
                                 'assigned': assigned, 'solved': count, 'remaining': assigned-count, 'percent': round(raw, 1)})

    # Ancestors roll up each unique student/task pair once, even with overlapping topics.
    nodes = {node['id']: node for node in Topic.objects.values('id', 'number_id', 'name', 'parent_id')}
    ancestor_cache = {}
    def ancestors(tid):
        if tid not in ancestor_cache:
            result, seen, current = [], set(), tid
            while current in nodes and current not in seen:
                seen.add(current); result.append(current); current = nodes[current]['parent_id']
            ancestor_cache[tid] = result
        return ancestor_cache[tid]
    problem_topics = {}
    direct_topics=defaultdict(set)
    for pid,tid in Problem.topics.through.objects.filter(problem_id__in=selected_ids).values_list('problem_id','topic_id'):direct_topics[pid].add(tid)
    for pid in problems:
        problem_topics[pid] = {tid for node in direct_topics[pid] for tid in ancestors(node) if nodes[tid]['parent_id'] is not None}
        if not problem_topics[pid]: problem_topics[pid] = {None}
    topic_totals = {}
    for pid,recipients in problem_students.items():
        for tid in problem_topics[pid]:
            total = topic_totals.setdefault(tid, {'assigned': 0, 'solved': 0, 'students': set(), 'problems': set()})
            total['assigned'] += len(recipients); total['solved'] += len(problem_solved[pid])
            total['students'].update(recipients); total['problems'].add(pid)
    topic_rows = []
    for tid, total in topic_totals.items():
        chain = [nodes[node]['name'] for node in reversed(ancestors(tid)) if nodes[node]['parent_id'] is not None] if tid else ['Без темы']
        topic_rows.append({'id': str(tid) if tid else None, 'public_id':f'TOP-{nodes[tid]["number_id"]}' if tid else None, 'name': chain[-1], 'path': ' / '.join(chain), 'depth': len(chain),
                           'assigned': total['assigned'], 'solved': total['solved'], 'recipients': len(total['students']),
                           'problem_count': len(total['problems']), 'percent': percent(total['solved'], total['assigned'])})
    topic_rows.sort(key=lambda row: row['path'])

    circle_rows = []
    discussion = None
    pending_discussed = set()
    if group_ids:
        discussion_states = { (state.circle_id, state.problem_id): state for state in Discussion.objects.filter(circle_id__in=group_ids, problem_id__in=selected_ids) }
        denominator = discussed = visible = 0
        for circle in Circle.objects.filter(pk__in=group_ids & circle_ids).only('id','number','name','city','archived').order_by('name'):
            recipients_by_problem = circle_problem_students[circle.pk]; pids = circle_problem_ids[circle.pk]
            assigned = sum(map(len,recipients_by_problem.values()))
            done = sum(len(recipients & solved_by_problem[pid]) for pid,recipients in recipients_by_problem.items())
            covered = sum(bool(discussion_states.get((circle.pk, pid)) and discussion_states[circle.pk, pid].discussed) for pid in pids)
            shown = sum(bool(discussion_states.get((circle.pk, pid)) and discussion_states[circle.pk, pid].solution_visible) for pid in pids)
            for pid,recipients in recipients_by_problem.items():
                state = discussion_states.get((circle.pk, pid))
                if state and state.discussed and not recipients <= solved_by_problem[pid]: pending_discussed.add(pid)
            denominator += len(pids); discussed += covered; visible += shown
            circle_rows.append({'id': str(circle.pk), 'public_id':f'C-{circle.number_id}', 'name': circle.name, 'city': circle.city, 'archived': circle.archived,
                                'recipients': len(circle_students[circle.pk]), 'worksheet_count': len(circle_sheets[circle.pk]),
                                'problem_count': len(pids), 'assigned': assigned, 'solved': done, 'percent': percent(done, assigned),
                                'discussed': covered, 'discussion_percent': percent(covered, len(pids))})
        discussion = {'total': denominator, 'discussed': discussed, 'remaining': denominator-discussed,
                      'visible': visible, 'percent': percent(discussed, denominator)}

    return {
        'personal_only': not bool(group_ids), 'assigned_pairs': assigned_count, 'solved_pairs': solved_count,
        'percent': percent(solved_count, assigned_count), 'student_count': len(student_ids), 'problem_count': len(problems), 'rows': rows,
        'counts': {'remaining_pairs': assigned_count-solved_count, 'worksheet_count': len(worksheet_rows), 'issue_count': len(issue_ids),
                   'circle_count': len(circle_ids), 'full_worksheet_count': sum(row['completed_recipients'] for row in worksheet_rows),
                   'worksheet_recipient_count': sum(row['recipients'] for row in worksheet_rows),
                   'students_with_solves': students_with_solves, 'students_without_solves': len(student_ids)-students_with_solves,
                   'students_completed': students_completed, 'median_percent': round(median(percentages), 1) if percentages else None},
        'discussion': discussion, 'distribution': distribution if group_ids else [],
        'worksheet_rows': worksheet_rows, 'student_rows': student_rows, 'topic_rows': topic_rows, 'circle_rows': circle_rows,
        'attention': {'unsolved_problem_count': sum(row['solved'] == 0 for row in rows),
                      'lowest_closure': rows[:5], 'discussed_pending_problem_count': len(pending_discussed) if group_ids else None},
        'definition': 'Текущее состояние · уникальные пары школьник × задача',
        'computed_at': timezone.now().isoformat(),
        'topic_catalog_version': TopicCatalogVersion.objects.order_by('-pk').values_list('pk', flat=True).first(),
    }

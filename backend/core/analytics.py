"""Permission-scoped learning reports built from assignments and current yes/no states."""
from collections import Counter, defaultdict
from itertools import groupby
from statistics import median
from django.db.models import Q,Exists,OuterRef
from django.core.exceptions import ValidationError
from django.utils import timezone
from . import filters as f, services as s
from .student_profiles import profile_scope
from .models import (Assignment, Circle, Discussion, Problem, Solve,
                     Student, Topic, TopicCatalogVersion, Worksheet, WorksheetItem, WorksheetIssue)


def percent(numerator, denominator):
    return round(100 * numerator / denominator, 1) if denominator else None


def scoped_assignments(user, params, *, student=None):
    group_circles = s.group_circles_for(user)
    selected_circles = f.uuid_ids(f.query_values(params, 'circle'))
    if selected_circles is not None:
        readable = group_circles if student is not None else s.circles_for(user)
        found = readable.filter(pk__in=selected_circles).order_by().values_list('pk', flat=True)
        if {str(pk) for pk in found} != selected_circles:
            raise s.NotFound('Кружок недоступен.')
        group_circles = group_circles.filter(pk__in=selected_circles)
    cities = f.query_values(params, 'city')
    state = params.get('state', 'all')
    group_circles = f.by_circle_state(f.by_city(group_circles, cities), state)
    group_ids = set(group_circles.order_by().values_list('pk', flat=True))
    allowed = Q(issue__circle_id__in=group_ids)
    include_personal = student is None and 'student' in user.roles and not s.admin(user)
    if include_personal:
        personal = Q(student__user=user)
        if selected_circles is not None:
            personal &= Q(issue__circle_id__in=selected_circles)
        allowed |= personal
    assignments = Assignment.objects.filter(allowed, issue__visible_to_students=True)
    if include_personal:
        assignments = f.by_city(f.by_circle_state(assignments, state, 'issue__circle__archived'), cities, 'issue__circle__city')
    if student is not None:assignments=assignments.filter(student=student)
    assignments = f.by_tags(assignments, f.query_values(params, 'worksheet_tag'), 'worksheet', 'issue__worksheet__tags')
    problem_tags = f.query_values(params, 'problem_tag')
    problems = f.by_tags(Problem.objects.all(), problem_tags, 'problem')
    topic_ids = s.topic_ids_in_branch(f.query_values(params, 'topic'))
    if topic_ids is not None:
        problems = problems.filter(topics__pk__in=topic_ids)
    elif not problem_tags:
        problems = None
    items = WorksheetItem.objects.filter(worksheet_id=OuterRef('issue__worksheet_id'),include_in_journal=True)
    if problems is not None:items=items.filter(problem__in=problems)
    assignments = assignments.filter(Exists(items))
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


def _completed_recipients(recipients,requirements,solved):
    """Intersect a worksheet's recipients without a second student × task index."""
    complete=set(recipients)
    for pid,required in requirements:
        if not complete:break
        if required is recipients:complete.intersection_update(solved.get(pid,()))
        else:complete.difference_update(required-solved.get(pid,frozenset()))
    return len(complete)


def report(user, params, *, student=None):
    include=params.get('include_discussed','1')
    if include not in {'0','1'}:raise ValidationError('include_discussed: 0 или 1.')
    include_discussed=include=='1'
    assignments, selected_problems, group_ids = scoped_assignments(user, params, student=student)
    # Read issue metadata once, rather than repeating two UUIDs for every pupil.
    issues = {iid:(wid,cid) for iid,wid,cid in WorksheetIssue.objects.filter(
        pk__in=assignments.values('issue_id')).values_list('pk','worksheet_id','circle_id')}
    worksheet_ids = {wid for wid,_ in issues.values()}
    worksheet_problems = defaultdict(set)
    for wid, pid in WorksheetItem.objects.filter(worksheet_id__in=worksheet_ids,include_in_journal=True).order_by().values_list('worksheet_id', 'problem_id'):
        worksheet_problems[wid].add(pid)
    all_problem_ids = set().union(*worksheet_problems.values())
    selected_by_worksheet = worksheet_problems
    if selected_problems is not None:
        selected_ids = set(selected_problems.filter(pk__in=all_problem_ids).order_by().values_list('pk', flat=True).distinct())
        selected_by_worksheet = {wid: pids & selected_ids for wid, pids in worksheet_problems.items()}
    discussion_states={(cid,pid):(True,shown) for cid,pid,shown in Discussion.objects.filter(
        circle_id__in={cid for _,cid in issues.values()},problem_id__in=all_problem_ids,discussed=True
    ).values_list('circle_id','problem_id','solution_visible')}
    discussed_by_circle=defaultdict(set)
    for cid,pid in discussion_states:discussed_by_circle[cid].add(pid)
    issue_ids, circle_ids = set(), set()
    circle_sheets, circle_students = defaultdict(set), defaultdict(set)
    worksheet_students, worksheet_circles, worksheet_issues = defaultdict(set), defaultdict(set), defaultdict(set)
    problem_students = {};available_problem_students={}
    eligible_worksheet_students=defaultdict(dict);full_worksheet_students=defaultdict(dict)
    circle_problem_ids=defaultdict(set)
    circle_problem_students = defaultdict(dict)
    # Coalesce a whole issue's recipients before expanding its selected problems.
    # The existing unique (issue, student) index also supports this stream order.
    facts = assignments.order_by('issue_id','student_id').values_list('issue_id','student_id').iterator(chunk_size=2000)
    for iid, students in groupby(facts, key=lambda row:row[0]):
        if iid not in issues:continue
        recipients = frozenset(sid for _,sid in students)
        wid,cid = issues[iid]
        original=selected_by_worksheet[wid];available=original-discussed_by_circle[cid]
        unions={}
        if not include_discussed:
            _merge_recipients(full_worksheet_students[wid],worksheet_problems[wid]-discussed_by_circle[cid],recipients,unions)
        pids=original if include_discussed else available
        if not pids:continue
        issue_ids.add(iid); circle_ids.add(cid)
        circle_problem_ids[cid].update(pids)
        if not include_discussed:_merge_recipients(eligible_worksheet_students[wid],pids,recipients,unions)
        worksheet_students[wid].update(recipients); worksheet_circles[wid].add(cid); worksheet_issues[wid].add(iid)
        _merge_recipients(problem_students,pids,recipients,unions)
        if include_discussed:_merge_recipients(available_problem_students,available,recipients,unions)
        if cid in group_ids:
            circle_sheets[cid].add(wid);circle_students[cid].update(recipients)
            _merge_recipients(circle_problem_students[cid],pids,recipients,unions)
    selected_ids=set(problem_students)
    student_ids = set().union(*set(problem_students.values()))
    solved_by_problem = defaultdict(set)
    for sid,pid in Solve.objects.filter(solved=True, student_id__in=student_ids, problem_id__in=all_problem_ids).values_list('student_id', 'problem_id').iterator(chunk_size=2000):
        solved_by_problem[pid].add(sid)
    problem_solved_counts = {}
    assigned_count = solved_count = 0
    student_assigned, student_solved = Counter(), Counter()
    student_available,student_blocked=Counter(),Counter()
    available_count=blocked_count=0
    for pid,recipients in problem_students.items():
        solved = recipients & solved_by_problem[pid]
        problem_solved_counts[pid] = len(solved)
        assigned_count += len(recipients); solved_count += len(solved)
        student_assigned.update(recipients); student_solved.update(solved)
        unsolved=recipients-solved
        if include_discussed:
            available=unsolved & available_problem_students.get(pid,frozenset())
            blocked=unsolved-available
            if group_ids:student_blocked.update(blocked)
            blocked_count+=len(blocked)
        else:available=unsolved
        if group_ids:student_available.update(available)
        available_count+=len(available)
    problems = {p.pk: p for p in Problem.objects.filter(pk__in=selected_ids).only('pk','title','number','source','source_id')}
    problem_circles, problem_worksheets = defaultdict(set), defaultdict(set)
    if not include_discussed:selected_by_worksheet={wid:set(rows) for wid,rows in eligible_worksheet_students.items()}
    for cid,pids in circle_problem_ids.items():
        for pid in pids:problem_circles[pid].add(cid)
    for wid, pids in selected_by_worksheet.items():
        for pid in pids: problem_worksheets[pid].add(wid)
    rows = []
    for pid, recipients in problem_students.items():
        count = problem_solved_counts[pid]
        rows.append({'problem_id': str(pid), 'public_id': f'P-{problems[pid].number_id}', 'title': problems[pid].display_title, 'recipients': len(recipients),
                     'solved': count, 'remaining': len(recipients)-count, 'percent': percent(count, len(recipients)),
                     'circle_count': len(problem_circles[pid]), 'worksheet_count': len(problem_worksheets[pid])})
    rows.sort(key=lambda row: (row['percent'], -row['recipients'], row['title']))

    worksheet_rows = []
    for worksheet in Worksheet.objects.filter(pk__in=worksheet_students).select_related('document').only('id','title','document__number').order_by('title'):
        wid = worksheet.pk; recipients = worksheet_students[wid]; pids = selected_by_worksheet[wid]
        if include_discussed:
            assigned=len(recipients)*len(pids)
            sheet_solved=sum(len(recipients & solved_by_problem[pid]) for pid in pids)
            required=((pid,recipients) for pid in worksheet_problems[wid])
        else:
            eligible=eligible_worksheet_students[wid]
            assigned=sum(map(len,eligible.values()))
            sheet_solved=sum(len(group & solved_by_problem[pid]) for pid,group in eligible.items())
            required=full_worksheet_students[wid].items()
        # Full composition still applies, independently of the selected topic/tag subset.
        complete=_completed_recipients(recipients,required,solved_by_problem)
        worksheet_rows.append({'id': str(wid), 'public_id': f'W-{worksheet.document.number_id}', 'title': worksheet.title, 'pdf_url':'/api/materials/worksheet/'+str(wid)+'/pdf', 'recipients': len(recipients),
                               'problem_count': len(pids), 'total_problem_count': len(worksheet_problems[wid]) if include_discussed else len(full_worksheet_students[wid]),
                               'assigned': assigned, 'solved': sheet_solved, 'percent': percent(sheet_solved, assigned),
                               'completed_recipients': complete, 'full_percent': percent(complete, len(recipients)),
                               'circle_count': len(worksheet_circles[wid]), 'issue_count': len(worksheet_issues[wid])})

    student_rows = []
    percentages = []
    distribution = [{'label': label, 'count': 0} for label in ['0%', '<25%', '25–<50%', '50–<75%', '75–<100%', '100%']]
    students_completed = students_with_solves = 0
    for sid, assigned in student_assigned.items():
        count = student_solved[sid]
        raw = 100*count/assigned
        percentages.append(raw); students_with_solves += bool(count); students_completed += count == assigned
        if group_ids:
            bucket = 0 if not count else 5 if count == assigned else 1 if raw < 25 else 2 if raw < 50 else 3 if raw < 75 else 4
            distribution[bucket]['count'] += 1
    if group_ids:
        if student is not None:
            pupils = [student] if student.pk in student_assigned else []
        else:
            pupils = Student.objects.filter(pk__in=student_ids).select_related('user').only('id','graduation_year','user__id','user__name').order_by('user__name')
            # Mixed roles can add personal results outside the adult profile scope.
            if 'student' in user.roles and not s.admin(user):
                pupils = pupils.annotate(can_view_profile=Exists(profile_scope(user).filter(pk=OuterRef('pk'))))
        on_date = timezone.localdate()
        for pupil in pupils:
            sid = pupil.pk; assigned = student_assigned[sid]; count = student_solved[sid]
            student_rows.append({'id': sid, 'public_id':f'S-{sid}', 'user_public_id':f'U-{pupil.user_id}', 'name': pupil.user.name, **pupil.education_info(on_date),
                                 'can_view_profile': getattr(pupil, 'can_view_profile', True),
                                 'assigned': assigned, 'solved': count, 'remaining': assigned-count, 'available':student_available[sid], 'discussed_unsolved':student_blocked[sid], 'percent': percent(count, assigned)})

    # Ancestors roll up each unique student/task pair once, even with overlapping topics.
    nodes = {node['id']: node for node in Topic.objects.order_by().values('id', 'number_id', 'name', 'parent_id')} if selected_ids else {}
    ancestor_cache = {}
    def ancestors(tid):
        if tid not in ancestor_cache:
            result, seen, current = [], set(), tid
            while current in nodes and current not in seen:
                seen.add(current); result.append(current); current = nodes[current]['parent_id']
            ancestor_cache[tid] = result
        return ancestor_cache[tid]
    direct_topics=defaultdict(set)
    for pid,tid in Problem.topics.through.objects.filter(problem_id__in=selected_ids).values_list('problem_id','topic_id'):direct_topics[pid].add(tid)
    topic_totals = {}
    for pid,recipients in problem_students.items():
        topics = {tid for node in direct_topics[pid] for tid in ancestors(node) if nodes[tid]['parent_id'] is not None} or {None}
        for tid in topics:
            total = topic_totals.setdefault(tid, {'assigned': 0, 'solved': 0, 'students': set(), 'problems': set()})
            total['assigned'] += len(recipients); total['solved'] += problem_solved_counts[pid]
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
        denominator = discussed = visible = 0
        for circle in Circle.objects.filter(pk__in=group_ids & circle_ids).only('id','number','name','city','archived').order_by('name'):
            recipients_by_problem = circle_problem_students[circle.pk]; pids = circle_problem_ids[circle.pk]
            assigned = sum(map(len,recipients_by_problem.values()))
            done = sum(len(recipients & solved_by_problem[pid]) for pid,recipients in recipients_by_problem.items())
            covered = sum(discussion_states.get((circle.pk, pid),(False,False))[0] for pid in pids)
            shown = sum(discussion_states.get((circle.pk, pid),(False,False))[1] for pid in pids)
            for pid,recipients in recipients_by_problem.items():
                state = discussion_states.get((circle.pk, pid))
                if state and state[0] and not recipients <= solved_by_problem[pid]: pending_discussed.add(pid)
            denominator += len(pids); discussed += covered; visible += shown
            circle_rows.append({'id': str(circle.pk), 'public_id':f'C-{circle.number_id}', 'name': circle.name, 'city': circle.city, 'archived': circle.archived,
                                'recipients': len(circle_students[circle.pk]), 'worksheet_count': len(circle_sheets[circle.pk]),
                                'problem_count': len(pids), 'assigned': assigned, 'solved': done, 'percent': percent(done, assigned),
                                'discussed': covered, 'discussion_percent': percent(covered, len(pids))})
        discussion = {'total': denominator, 'discussed': discussed, 'remaining': denominator-discussed,
                      'visible': visible, 'percent': percent(discussed, denominator)}

    personal_only = student is None and 'student' in user.roles and not s.admin(user) and not group_ids
    return {
        **({'subject_student_id':student.pk} if student is not None else {}),
        'include_discussed':include_discussed,'personal_only':personal_only, 'assigned_pairs': assigned_count, 'solved_pairs': solved_count,
        'percent': percent(solved_count, assigned_count), 'student_count': len(student_ids), 'problem_count': len(problems), 'rows': rows,
        'counts': {'remaining_pairs': assigned_count-solved_count,'available_pairs':available_count,'discussed_unsolved_pairs':blocked_count, 'worksheet_count': len(worksheet_rows), 'issue_count': len(issue_ids),
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

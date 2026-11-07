"""Shared, permission-scoped journal snapshot for screen and file exports."""
from django.core.exceptions import ValidationError
from django.db.models import Prefetch,prefetch_related_objects
from .models import Assignment,Problem,Solve,Discussion
from . import services as s


def view_options(params):
    hide=params.get('hide_discussed','0');order=params.get('order','newest')
    if hide not in {'0','1'} or order not in {'newest','oldest'}:
        raise ValidationError('hide_discussed: 0 или 1; order: newest или oldest.')
    return {'hide_discussed':hide=='1','order':order}


def apply_view(data, *, hide_discussed=False, order='newest'):
    """Keep original task numbers while selecting the same columns for UI and exports."""
    if order not in {'newest','oldest'}:raise ValidationError('Неизвестный порядок листков.')
    discussed={state['problem_id'] for state in data['discussions'] if state['discussed']}
    blocks=[]
    for block in data['blocks']:
        problems=[problem if 'worksheet_position' in problem else {**problem,'worksheet_position':position}
                  for position,problem in enumerate(block['problems'],1)
                  if not hide_discussed or problem['id'] not in discussed]
        # Keep genuinely theoretical worksheets, but drop task blocks emptied by the filter.
        if block['problems'] and not problems:continue
        blocks.append({**block,'problems':problems})
    blocks.sort(key=lambda block:(block['issued_on'],block['issue_id']),reverse=order=='newest')
    visible={problem['id'] for block in blocks for problem in block['problems']}
    return {**data,'blocks':blocks,
            'solves':[state for state in data['solves'] if state['problem_id'] in visible],
            'discussions':[state for state in data['discussions'] if state['problem_id'] in visible]}


def select_issues(circle, raw='all', *, for_export=False):
    if for_export:
        # Downloads only expose titles and result cells. Avoid fetching source
        # bodies, author accounts and taxonomy relations for every issued task.
        problems = Problem.objects.only('id', 'title', 'number', 'source', 'source_id')
    else:
        problems = Problem.objects.select_related('author').prefetch_related('topics', 'tags')
    queryset = circle.issues.select_related('worksheet__document').prefetch_related(
        'worksheet__items'
    ).order_by('-issued_on', '-pk')
    ids=None
    if raw != 'all':
        try:
            ids = {int(value) for value in raw.split(',')}
        except (AttributeError, TypeError, ValueError):
            raise ValidationError('Выберите один или несколько выданных листков.')
        if not ids or any(value <= 0 for value in ids):
            raise ValidationError('Некорректный набор листков.')
        queryset = queryset.filter(pk__in=ids)
    result=list(queryset)
    if ids is not None and {issue.pk for issue in result} != ids:
        raise s.NotFound('Один из листков не выдавался этому кружку.')
    # Every item keeps its place in the printed numbering. Excluded items do
    # not need their potentially large problem bodies in a journal response.
    included=[item for issue in result for item in issue.worksheet.items.all() if item.include_in_journal]
    prefetch_related_objects(included,Prefetch('problem',queryset=problems))
    return result


def snapshot(user, circle, selected, serialize_problem, search=''):
    from .people import search_people
    from .school import education_info
    people = list(search_people(circle.enrollments.filter(left_at=None),search,'student__user__',email=False).order_by('student__user__name').values_list(
        'student_id','student__user_id','student__user__name','student__graduation_year'))
    student_ids=[person[0] for person in people]
    can_write=s.can_write(user,circle)
    group_stats=can_write or s.can_analyse_group(user,circle)
    recipients={issue.pk:[] for issue in selected}
    if group_stats:
        for iid,sid in Assignment.objects.filter(issue_id__in=recipients,student_id__in=student_ids).values_list('issue_id','student_id').iterator():
            recipients[iid].append(sid)
    blocks = []
    problem_ids = set()
    serialized = {}
    from .documents import issue_references
    for issue in selected:
        problems=[]
        for number,item in enumerate(issue.worksheet.items.all(),issue.worksheet.numbering_start):
            if not item.include_in_journal:continue
            problem=item.problem
            if problem.pk not in serialized:serialized[problem.pk]=serialize_problem(problem,user)
            problem_ids.add(problem.pk)
            problems.append({**serialized[problem.pk],'worksheet_position':number})
        blocks.append({
            **({'recipient_ids':recipients[issue.pk]} if group_stats else {}),
            'issue_id': issue.pk, 'issued_on': issue.issued_on.isoformat(), 'number':issue.number,
            'worksheet': {'id': str(issue.worksheet_id), 'public_id':f'W-{issue.worksheet.document.number_id}', 'title': issue.worksheet.title, 'description': issue.worksheet.description,**issue_references(issue)},
            'problems': problems,
        })
    states = Solve.objects.filter(student_id__in=student_ids, problem_id__in=problem_ids).values_list('student_id', 'problem_id', 'solved', 'version').iterator()
    discussions = Discussion.objects.filter(circle=circle, problem_id__in=problem_ids).values_list('problem_id', 'discussed', 'solution_visible', 'version').iterator()
    return {
        'circle': {'id': str(circle.pk), 'public_id':f'C-{circle.number_id}', 'name': circle.name}, 'blocks': blocks,
        'people': [{'id': sid, 'public_id':f'S-{sid}', 'user_public_id':f'U-{uid}', 'name': name, **education_info(year), 'self': uid == user.pk} for sid,uid,name,year in people],
        'solves': [{'student_id': student_id, 'problem_id': str(problem_id), 'solved': solved, 'version': version} for student_id, problem_id, solved, version in states],
        'discussions': [{'problem_id': str(problem_id), 'discussed': discussed, 'solution_visible': solution_visible, 'version': version} for problem_id, discussed, solution_visible, version in discussions],
        'can_write': can_write, 'show_group_stats': group_stats,
    }

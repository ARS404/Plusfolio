"""Shared, permission-scoped journal snapshot for screen and file exports."""
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from .models import WorksheetItem, Problem, Solve, Discussion
from . import services as s


def select_issues(circle, raw='all', *, for_export=False):
    if for_export:
        # Downloads only expose titles and result cells. Avoid fetching source
        # bodies, author accounts and taxonomy relations for every issued task.
        problems = Problem.objects.only('id', 'title', 'number', 'source', 'source_id')
    else:
        problems = Problem.objects.select_related('author').prefetch_related('topics', 'tags')
    items = WorksheetItem.objects.prefetch_related(Prefetch('problem', queryset=problems))
    queryset = circle.issues.select_related('worksheet__document').prefetch_related(
        Prefetch('worksheet__items', queryset=items)
    ).order_by('-issued_on', '-pk')
    if raw != 'all':
        try:
            ids = {int(value) for value in raw.split(',')}
        except (AttributeError, TypeError, ValueError):
            raise ValidationError('Выберите один или несколько выданных листков.')
        if not ids or any(value <= 0 for value in ids):
            raise ValidationError('Некорректный набор листков.')
        queryset = queryset.filter(pk__in=ids)
        result = list(queryset)
        if {issue.pk for issue in result} != ids:
            raise s.NotFound('Один из листков не выдавался этому кружку.')
        return result
    return list(queryset)


def snapshot(user, circle, selected, serialize_problem, search=''):
    from .people import search_people
    people = list(search_people(circle.enrollments.filter(left_at=None),search,'student__user__',email=False).select_related('student__user').order_by('student__user__name'))
    blocks = []
    problem_ids = set()
    serialized = {}
    from .documents import issue_references
    for issue in selected:
        problems = [item.problem for item in issue.worksheet.items.all()]
        for problem in problems:
            if problem.pk not in serialized:serialized[problem.pk]=serialize_problem(problem,user)
        problem_ids.update(problem.pk for problem in problems)
        blocks.append({
            'issue_id': issue.pk, 'issued_on': issue.issued_on.isoformat(), 'number':issue.number,
            'worksheet': {'id': str(issue.worksheet_id), 'public_id':f'W-{issue.worksheet.document.number_id}', 'title': issue.worksheet.title, 'description': issue.worksheet.description,**issue_references(issue)},
            'problems': [serialized[problem.pk] for problem in problems],
        })
    states = Solve.objects.filter(student_id__in=[person.student_id for person in people], problem_id__in=problem_ids)
    discussions = Discussion.objects.filter(circle=circle, problem_id__in=problem_ids)
    return {
        'circle': {'id': str(circle.pk), 'public_id':f'C-{circle.number_id}', 'name': circle.name}, 'blocks': blocks,
        'people': [{'id': person.student_id, 'public_id':f'S-{person.student_id}', 'user_public_id':f'U-{person.student.user_id}', 'name': person.student.user.name, **person.student.education_info(), 'self': person.student.user_id == user.pk} for person in people],
        'solves': [{'student_id': state.student_id, 'problem_id': str(state.problem_id), 'solved': state.solved, 'version': state.version} for state in states],
        'discussions': [{'problem_id': str(state.problem_id), 'discussed': state.discussed, 'solution_visible': state.solution_visible, 'version': state.version} for state in discussions],
        'can_write': s.can_write(user, circle), 'show_group_stats': s.can_analyse_group(user, circle),
    }

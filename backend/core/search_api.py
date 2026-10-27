from django.core.cache import cache
from django.core.exceptions import ValidationError
from rest_framework.decorators import api_view
from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from . import services as s, filters as f, queries as read
from .api import material_data
from .identifiers import typed_id
from .search import retrieve


@api_view(['GET', 'POST'])
def problem_search(request):
    params = request.query_params if request.method == 'GET' else request.data
    if not isinstance(params, dict) and not hasattr(params, 'getlist'):
        raise ValidationError('Передайте JSON-объект.')
    text = params.get('q', '')
    if not isinstance(text, str):raise ValidationError('q должен быть строкой.')
    text = text.strip()
    field = params.get('field', 'all')
    if not isinstance(field,str):raise ValidationError('field должен быть строкой.')
    fields = f.query_values(params,'fields')
    if fields is not None and not isinstance(fields,list):raise ValidationError('fields должен быть массивом строк.')
    if fields:
        if any(not isinstance(value,str) for value in fields):raise ValidationError('fields должен быть массивом строк.')
        if not set(fields)<={'statement','solution','metadata'}:raise ValidationError('fields: statement/solution/metadata.')
        field=fields
    scope = params.get('scope', 'library')
    mode = params.get('mode', 'hybrid')
    limit = int(params.get('limit', '20'))
    if not 1 <= len(text) <= 12000 or (not isinstance(field,list) and field not in {'all','statement','solution','metadata'}) or scope not in {'library', 'my'} or mode not in {'hybrid', 'text'} or not 1 <= limit <= 50:
        raise ValidationError('Укажите текст до 12 000 символов, field: all/statement/solution/metadata, mode: hybrid/text и limit: 1–50.')
    key = f'problem-search:{request.user.pk}'
    if cache.add(key, 1, 60):
        count = 1
    else:
        try:count = cache.incr(key)
        except ValueError:cache.set(key, 1, 60);count = 1
    if count > 60:
        raise Throttled(wait=60, detail='Слишком много поисков. Повторите через минуту.')
    mine = scope == 'my' or not set(request.user.roles) & {'admin', 'teacher', 'analyst'}
    problems = s.my_problems_for(request.user) if mine else s.problems_for(request.user)
    problems = f.by_tags(problems, f.query_values(params, 'tag'), 'problem')
    topics = s.topic_ids_in_branch(f.query_values(params, 'topic'))
    if topics is not None:
        problems = problems.filter(topics__pk__in=topics).distinct()
    from uuid import UUID
    try:UUID(text);is_uuid=True
    except ValueError:is_uuid=False
    if is_uuid or typed_id(text) or ((set(field) if isinstance(field,list) else {field}) != {'solution'} and text.isdigit() and len(text) <= 18):
        rows = list(read.material_rows(s.search_problems(problems, text), 'problem')[:limit])
        metadata = {'semantic': False, 'pending': 0, 'notice': ''}
        matches = {row.pk: {'kind': 'identifier', 'fields': set(), 'excerpt': ''} for row in rows}
    else:
        ranked, metadata = retrieve(request.user, problems, text, field, limit, mode == 'hybrid')
        matches = dict(ranked)
        indexed = {row.pk: row for row in read.material_rows(problems.filter(pk__in=matches), 'problem')}
        rows = [indexed[pk] for pk, _ in ranked if pk in indexed]
    visible = s.visible_solution_ids(request.user, [row.pk for row in rows])
    return Response({'results': [{'problem': material_data(row, request.user, allowed_solutions=visible),
        'match': matches[row.pk]['kind'], 'fields': sorted(matches[row.pk]['fields']),
        'excerpt': matches[row.pk]['excerpt']} for row in rows], **metadata})

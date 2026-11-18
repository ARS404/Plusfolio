"""Shared, permission-scoped journal snapshot for screen and file exports."""
from django.core.exceptions import ValidationError
from django.db.models import Count,Exists,F,OuterRef,Prefetch,Q,prefetch_related_objects
from .models import Assignment,Problem,Solve,Discussion,WorksheetItem
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


def select_issues(issues, raw='all', *, for_export=False, hide_discussed=False):
    queryset=issues.select_related('worksheet__document').order_by('-issued_on','-pk')
    ids=None
    if raw!='all':
        try:ids={int(value) for value in raw.split(',')}
        except (AttributeError,TypeError,ValueError):raise ValidationError('Выберите один или несколько выданных листков.')
        if not ids or any(value<=0 for value in ids):raise ValidationError('Некорректный набор листков.')
        queryset=queryset.filter(pk__in=ids)
        if set(queryset.values_list('pk',flat=True))!=ids:raise s.NotFound('Один из листков не выдавался этому кружку.')
    if for_export:
        from .journal_export import check_size
        tracked=Q(worksheet__items__include_in_journal=True)
        counts=queryset.order_by().values('pk').annotate(tracked_count=Count('worksheet__items',filter=tracked))
        if hide_discussed:
            discussed=Discussion.objects.filter(circle_id=OuterRef('circle_id'),problem_id=OuterRef('worksheet__items__problem_id'),discussed=True)
            counts=counts.annotate(visible_count=Count('worksheet__items',filter=tracked&~Q(Exists(discussed))))
        retained=[];width=1
        for row in counts.iterator():
            count=row['visible_count'] if hide_discussed else row['tracked_count']
            if hide_discussed and row['tracked_count'] and not count:continue
            retained.append(row['pk']);width+=count
            check_size(max(width,1+len(retained)),0)
        result=list(queryset.filter(pk__in=retained).defer('worksheet__description'))
        selected={issue.pk:issue for issue in result}
        included=[]
        for issue in result:issue.worksheet.journal_items=[]
        items=WorksheetItem.objects.filter(worksheet__issues__pk__in=selected).annotate(journal_issue_id=F('worksheet__issues__pk'))
        if hide_discussed:
            discussed=Discussion.objects.filter(circle_id=OuterRef('worksheet__issues__circle_id'),problem_id=OuterRef('problem_id'),discussed=True)
            items=items.annotate(journal_discussed=Exists(discussed))
        current=None;position=0
        # Stream excluded items too, preserving numbering from legacy worksheets
        # whose stored positions may contain gaps.
        for item in items.order_by('journal_issue_id','position').iterator():
            if item.journal_issue_id!=current:current=item.journal_issue_id;position=0
            worksheet=selected[current].worksheet
            item.journal_position=worksheet.numbering_start+position;position+=1
            if item.include_in_journal and not (hide_discussed and item.journal_discussed):
                worksheet.journal_items.append(item);included.append(item)
                check_size(1+len(included),0)
        problems=Problem.objects.only('id','title','number','source','source_id')
    else:
        result=list(queryset.prefetch_related('worksheet__items'))
        included=[item for issue in result for item in issue.worksheet.items.all() if item.include_in_journal]
        problems=Problem.objects.select_related('author').prefetch_related('topics','tags')
    prefetch_related_objects(included,Prefetch('problem',queryset=problems))
    return result


def snapshot(user, circle, selected, serialize_problem, search='', *, export_options=None):
    from .people import search_people
    from .school import education_info
    people = list(search_people(circle.enrollments.filter(left_at=None),search,'student__user__',email=False).order_by('student__user__name').values_list(
        'student_id','student__user_id','student__user__name','student__graduation_year'))
    student_ids=[person[0] for person in people]
    can_write=s.can_write(user,circle)
    group_stats=can_write or s.can_analyse_group(user,circle)
    include_recipients=group_stats and export_options is None
    recipients={issue.pk:[] for issue in selected if issue.visible_to_students} if include_recipients else {}
    if recipients:
        for iid,sid in Assignment.objects.filter(issue_id__in=recipients,student_id__in=student_ids).values_list('issue_id','student_id').iterator():
            recipients[iid].append(sid)
    blocks = []
    problem_ids = set()
    serialized = {}
    from .documents import issue_references
    for issue in selected:
        problems=[]
        items=issue.worksheet.journal_items if hasattr(issue.worksheet,'journal_items') else issue.worksheet.items.all()
        for number,item in enumerate(items,issue.worksheet.numbering_start):
            if not item.include_in_journal:continue
            problem=item.problem
            if problem.pk not in serialized:serialized[problem.pk]=serialize_problem(problem,user)
            problem_ids.add(problem.pk)
            problems.append({**serialized[problem.pk],'worksheet_position':getattr(item,'journal_position',number)})
        blocks.append({
            **({'recipient_ids':recipients.get(issue.pk,[])} if include_recipients else {}),
            'issue_id': issue.pk, 'issued_on': issue.issued_on.isoformat(), 'number':issue.number,
            'visible_to_students':issue.visible_to_students,
            'worksheet': {'id': str(issue.worksheet_id), 'public_id':f'W-{issue.worksheet.document.number_id}', 'title': issue.worksheet.title, **({'description':issue.worksheet.description} if export_options is None else {}),**issue_references(issue)},
            'problems': problems,
        })
    discussions = Discussion.objects.filter(circle=circle, problem_id__in=problem_ids).values_list('problem_id', 'discussed', 'solution_visible', 'version').iterator()
    data = {
        'circle': {'id': str(circle.pk), 'public_id':f'C-{circle.number_id}', 'name': circle.name}, 'blocks': blocks,
        'people': [{'id': sid, 'public_id':f'S-{sid}', 'user_public_id':f'U-{uid}', 'name': name, **education_info(year), 'self': uid == user.pk} for sid,uid,name,year in people],
        'solves': [],
        'discussions': [{'problem_id': str(problem_id), 'discussed': discussed, 'solution_visible': solution_visible, 'version': version} for problem_id, discussed, solution_visible, version in discussions],
        'can_write': can_write, 'show_group_stats': group_stats,
    }

    if export_options is not None:
        from .journal_export import check_size
        data=apply_view(data,**export_options)
        width=1+sum(len(block['problems'])+int(group_stats) for block in data['blocks'])
        check_size(width,len(people))
        problem_ids={problem['id'] for block in data['blocks'] if block['visible_to_students'] for problem in block['problems']}
    states=Solve.objects.filter(student_id__in=student_ids,problem_id__in=problem_ids)
    if export_options is not None:states=states.filter(solved=True)
    values=({'student_id':sid,'problem_id':serialized[pid]['id'],'solved':solved,'version':version}
            for sid,pid,solved,version in states.values_list('student_id','problem_id','solved','version').iterator())
    data['solves']=list(values) if export_options is None else values
    return data

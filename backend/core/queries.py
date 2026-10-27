"""Batch loading for read serializers; permission decisions never persist across requests."""
from django.db.models import Count,Exists,OuterRef,Prefetch,Q,Value,BooleanField
from .models import AnalystGrant,Circle,CircleTeacher,WorksheetItem


def circle_rows(queryset,user):
    teaches=Exists(CircleTeacher.objects.filter(circle_id=OuterRef('pk'),teacher__user=user,ended_at=None)) if 'teacher' in user.roles else Value(False,output_field=BooleanField())
    analyses=Exists(Circle.tags.through.objects.filter(circle_id=OuterRef('pk'),tag_id__in=AnalystGrant.objects.filter(user=user).values('tag_id'))) if 'analyst' in user.roles else Value(False,output_field=BooleanField())
    return queryset.annotate(
        _teaches=teaches,_analyses=analyses,
        _student_count=Count('enrollments',filter=Q(enrollments__left_at=None),distinct=True),
        _worksheet_count=Count('issues',distinct=True),
    ).order_by('name').prefetch_related('tags',Prefetch('teaching',queryset=CircleTeacher.objects.filter(ended_at=None).select_related('teacher__user'),to_attr='_current_teachers'))


def material_rows(queryset,kind):
    return queryset.select_related('author',*(['document'] if kind=='worksheet' else [])).prefetch_related('topics','tags')


def load_worksheet_items(worksheets):
    # Lists only need task IDs; avoid retaining full item model instances for every sheet.
    by_id={worksheet.pk:worksheet for worksheet in worksheets}
    for worksheet in worksheets:worksheet._problem_ids=[]
    for worksheet_id,problem_id in WorksheetItem.objects.filter(worksheet_id__in=by_id).values_list('worksheet_id','problem_id'):
        by_id[worksheet_id]._problem_ids.append(problem_id)


def issue_rows(queryset):
    return queryset.select_related('worksheet__document','circle').annotate(_problem_count=Count('worksheet__items',distinct=True)).prefetch_related('worksheet__tags')

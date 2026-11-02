"""Student pages expose only the adult reader's reporting circles and assignments."""
from collections import defaultdict
from django.db.models import Count,Exists,OuterRef,Q
from . import services as s
from .models import Assignment,Enrollment,Student


def subject(user,student_id):
    s.require(s.can_analyse_group(user))
    students=Student.objects.filter(pk=student_id)
    if not s.admin(user):
        circles=s.group_circles_for(user)
        students=students.filter(
            Q(Exists(Enrollment.objects.filter(student_id=OuterRef('pk'),circle__in=circles)))|
            Q(Exists(Assignment.objects.filter(student_id=OuterRef('pk'),issue__circle__in=circles))))
    student=students.select_related('user').only('id','user_id','graduation_year','user__id','user__name').first()
    if student is None:raise s.NotFound('Школьник недоступен.')
    return student


def profile(user,student):
    circles=s.group_circles_for(user).filter(
        Q(Exists(Enrollment.objects.filter(circle_id=OuterRef('pk'),student=student)))|
        Q(Exists(Assignment.objects.filter(issue__circle_id=OuterRef('pk'),student=student)))
    ).order_by('name','pk').values('id','number_id','name','city','archived')
    circles=list(circles);ids=[circle['id'] for circle in circles]
    periods=defaultdict(list)
    for cid,joined,left in Enrollment.objects.filter(student=student,circle_id__in=ids).order_by('joined_at','pk').values_list('circle_id','joined_at','left_at').iterator(chunk_size=1000):
        periods[cid].append({'joined_at':joined.isoformat(),'left_at':left.isoformat() if left else None})
    # The unique (issue, student) constraint already prevents duplicate issues here.
    counts=dict(Assignment.objects.filter(student=student,issue__circle_id__in=ids).values('issue__circle_id').annotate(total=Count('issue_id')).values_list('issue__circle_id','total'))
    return {'id':student.pk,'public_id':f'S-{student.pk}','user_public_id':f'U-{student.user_id}',
            'name':student.user.name,**student.education_info(),
            'circles':[{'id':str(circle['id']),'public_id':f"C-{circle['number_id']}",'name':circle['name'],'city':circle['city'],
                        'archived':circle['archived'],'active':any(period['left_at'] is None for period in periods[circle['id']]),
                        'periods':periods[circle['id']],'issue_count':counts.get(circle['id'],0)} for circle in circles]}

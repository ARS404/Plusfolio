"""The authenticated user's own account and role-scoped overview."""
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from . import services as s
from .models import (AnalystGrant, CircleTeacher, Enrollment, Invitation, Problem,
                     User, Worksheet, WorksheetIssue, WorksheetItem, Solve, Assignment)


def published_counts(model, user):
    rows = model.objects.filter(published=True)
    if not s.admin(user):
        return {'own': rows.filter(author=user).count()}
    counts = {'total': Count('pk')}
    if 'teacher' in user.roles:
        counts['own'] = Count('pk', filter=Q(author=user))
    return rows.aggregate(**counts)


def overview(user):
    circles = s.circles_for(user)
    active = circles.filter(archived=False)
    teaching = set(CircleTeacher.objects.filter(teacher__user=user, ended_at=None).values_list('circle_id', flat=True)) if 'teacher' in user.roles else set()
    attending = set(Enrollment.objects.filter(student__user=user, left_at=None).values_list('circle_id', flat=True)) if 'student' in user.roles else set()
    analytical = s.analyst_circles_for(user)
    analyst_ids = set(analytical.values_list('pk', flat=True))
    counts = {'total': Count('pk'), 'active': Count('pk', filter=Q(archived=False))}
    for role, ids in [('teacher', teaching), ('student', attending), ('analyst', analyst_ids)]:
        if role in user.roles:
            counts[role] = Count('pk', filter=Q(archived=False, pk__in=ids))
    if 'analyst' in user.roles:
        counts['analyst_cities'] = Count('city', distinct=True, filter=Q(archived=False, pk__in=analyst_ids))
    circle_counts = circles.aggregate(**counts)
    materials = {name: published_counts(model,user) for name,model in [('problems',Problem),('worksheets',Worksheet)]} if s.admin(user) or 'teacher' in user.roles else {}
    result = {'joined_at': user.date_joined.isoformat(), 'circle_count': circle_counts['total'],
              'active_circle_count': circle_counts['active'], 'circles': [], 'student': None,
              'teacher': None, 'analyst': None, 'admin': None}
    for circle in circles.only('id','number','name','city','archived').order_by('archived', 'name')[:8]:
        relations = (['admin'] if s.admin(user) else [])
        relations += (['teacher'] if circle.pk in teaching else [])
        relations += (['student'] if circle.pk in attending else [])
        relations += (['analyst'] if circle.pk in analyst_ids else [])
        result['circles'].append({'id': str(circle.pk), 'public_id': f'C-{circle.number_id}', 'name': circle.name, 'city': circle.city,
                                  'archived': circle.archived, 'relations': relations})
    if 'student' in user.roles:
        # Personal assignments stay personal even when this account also teaches or analyses.
        problems = WorksheetItem.objects.filter(worksheet_id__in=Assignment.objects.filter(student__user=user).values('issue__worksheet_id')).values('problem_id').distinct()
        assigned = problems.count()
        solved = Solve.objects.filter(student__user=user,solved=True,problem_id__in=problems).count()
        result['student'] = {'assigned': assigned, 'solved': solved, 'remaining': assigned-solved,
                             'percent': round(100*solved/assigned, 1) if assigned else None,
                             'active_circles': circle_counts['student']}
    if 'teacher' in user.roles:
        own = active.filter(pk__in=teaching)
        result['teacher'] = {'active_circles': circle_counts['teacher'],
                             'students': Enrollment.objects.filter(circle__in=own, left_at=None).values('student_id').distinct().count(),
                             'issues': WorksheetIssue.objects.filter(circle__in=own).count(),
                             'problems_created': materials['problems']['own'],
                             'worksheets_created': materials['worksheets']['own']}
    if 'analyst' in user.roles:
        result['analyst'] = {'active_circles': circle_counts['analyst'], 'cities': circle_counts['analyst_cities'],
                             'tags': list(AnalystGrant.objects.filter(user=user).values('tag__id', 'tag__name'))}
    if s.admin(user):
        result['admin'] = {'active_circles': circle_counts['active'], 'active_users': User.objects.filter(is_active=True).count(),
                           'problems': materials['problems']['total'],
                           'worksheets': materials['worksheets']['total']}
    if set(user.roles) - {'student'}:
        invitations = Invitation.objects.filter(state='pending', expires_at__gt=timezone.now())
        if not s.admin(user): invitations = invitations.filter(created_by=user)
        result['pending_invitations'] = invitations.count()
    return result


@transaction.atomic
def update_name(user, data):
    if 'student' in user.roles:
        from .people import student_identity
        if set(data)!={'name','graduation_year','no_patronymic'}:raise ValidationError('Для школьника укажите полное ФИО, наличие отчества и год выпуска.')
        identity=student_identity(data)
        account=User.objects.select_for_update().get(pk=user.pk)
        student=account.student
        previous={'name':account.name,'graduation_year':student.graduation_year,'no_patronymic':student.no_patronymic}
        if previous!=identity:
            account.name=identity['name'];account.save(update_fields=['name'])
            student.graduation_year=identity['graduation_year'];student.no_patronymic=identity['no_patronymic'];student.save(update_fields=['graduation_year','no_patronymic'])
            s.audit(user,'account.student_profile',{'previous':previous,**identity})
        user.name=account.name
        user._state.fields_cache.pop('student',None)
        return user
    if set(data) != {'name'} or not isinstance(data['name'], str):
        raise ValidationError('В этом разделе можно изменить только имя.')
    name = data['name'].strip()
    if not name or len(name) > 120:
        raise ValidationError('Укажите имя длиной от 1 до 120 символов.')
    if name != user.name:
        previous = user.name
        user.name = name
        user.save(update_fields=['name'])
        s.audit(user, 'account.name', {'previous_name': previous, 'name': name})
    return user


@transaction.atomic
def change_password(request, data):
    fields = {'current_password', 'new_password', 'confirm_password'}
    if set(data) != fields or any(not isinstance(data[field], str) for field in fields):
        raise ValidationError('Укажите текущий пароль, новый пароль и его подтверждение.')
    account = User.objects.select_for_update().get(pk=request.user.pk)
    if not account.check_password(data['current_password']):
        raise ValidationError('Текущий пароль неверен.')
    if data['new_password'] != data['confirm_password']:
        raise ValidationError('Подтверждение пароля не совпадает.')
    validate_password(data['new_password'], account)
    account.set_password(data['new_password'])
    account.save(update_fields=['password'])
    request.user.password = account.password
    update_session_auth_hash(request, request.user)
    s.audit(account, 'account.password')
